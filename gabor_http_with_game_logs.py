from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


APP_REL = Path(os.environ.get("OPEN_CAMPUS_APP_REL", "10_graduation_current/outputs/20260614_open_campus_feature_game"))


def load_access_config(root: Path) -> dict:
    config_path = root / APP_REL / "access_control.json"
    default = {
        "enabled": False,
        "allowed_cidrs": ["127.0.0.1/32", "::1/128"],
        "split_logs_by_scope": True,
        "lab_cidrs": ["127.0.0.1/32", "::1/128"],
        "warp_cidrs": [],
        "deny_message": "This page is only available from the allowed network.",
    }
    if not config_path.exists():
        return default
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return {**default, **loaded}


def registry_paths(root: Path) -> tuple[Path, Path]:
    app_root = root / APP_REL
    return app_root / "logs" / "device_registry.jsonl", app_root / "registered_devices.json"


def load_registered_devices(root: Path) -> dict:
    _log_path, state_path = registry_paths(root)
    if not state_path.exists():
        return {"devices": []}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"devices": []}
    if not isinstance(data.get("devices"), list):
        return {"devices": []}
    return data


def registered_device_for_ip(root: Path, client_ip: str) -> dict | None:
    devices = load_registered_devices(root).get("devices", [])
    matches = [device for device in devices if device.get("client_ip") == client_ip and device.get("active", True)]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.get("registered_at", ""))[-1]


def make_device_id(client_ip: str, label: str, server_time: str) -> str:
    digest = hashlib.sha256(f"{client_ip}|{label}|{server_time}".encode("utf-8")).hexdigest()
    return f"dev-{digest[:16]}"


class Handler(SimpleHTTPRequestHandler):
    root: Path = Path(".")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.root), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def client_ip(self) -> ipaddress._BaseAddress | None:
        try:
            return ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return None

    def observed_client(self) -> tuple[str, str]:
        cf_connecting_ip = (self.headers.get("CF-Connecting-IP") or "").strip()
        if cf_connecting_ip:
            return cf_connecting_ip, "cf_connecting_ip"
        forwarded_for = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if forwarded_for:
            return forwarded_for, "x_forwarded_for"
        real_ip = (self.headers.get("X-Real-IP") or "").strip()
        if real_ip:
            return real_ip, "x_real_ip"
        return self.client_address[0], "peer"

    def ip_in_cidrs(self, client_ip: ipaddress._BaseAddress, cidrs: list[str]) -> bool:
        for cidr in cidrs:
            try:
                if client_ip in ipaddress.ip_network(str(cidr), strict=False):
                    return True
            except ValueError:
                continue
        return False

    def access_scope(self, client_ip_text: str | None = None) -> str:
        config = load_access_config(self.root)
        if client_ip_text is None:
            client_ip = self.client_ip()
        else:
            try:
                client_ip = ipaddress.ip_address(client_ip_text)
            except ValueError:
                client_ip = None
        if client_ip is None:
            return "unknown"
        if self.ip_in_cidrs(client_ip, config.get("warp_cidrs", [])):
            return "warp"
        if self.ip_in_cidrs(client_ip, config.get("lab_cidrs", [])):
            return "lab"
        return "external"

    def access_allowed(self) -> bool:
        config = load_access_config(self.root)
        if not config.get("enabled"):
            return True
        client_ip = self.client_ip()
        if client_ip is None:
            return False
        if self.ip_in_cidrs(client_ip, config.get("allowed_cidrs", [])):
            return True
        self.write_access_denied_log(client_ip=str(client_ip), config=config)
        return False

    def write_access_denied_log(self, client_ip: str, config: dict) -> None:
        if not config.get("log_denied", True):
            return
        log_dir = self.root / APP_REL / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "client": client_ip,
            "path": self.path,
            "reason": "ip_not_allowed",
        }
        with (log_dir / "access_denied.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def deny_access(self) -> None:
        body = b"Forbidden: this page is only available from the allowed network.\n"
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self.access_allowed():
            self.deny_access()
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if not self.access_allowed():
            self.deny_access()
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        if not self.access_allowed():
            self.deny_access()
            return
        parsed = urlparse(self.path)
        path = Path(unquote(parsed.path).lstrip("/"))
        if path.as_posix() in {
            "api/register-device",
            (APP_REL / "api/register-device").as_posix(),
        }:
            self.handle_device_registration()
            return
        if path.as_posix() not in {
            "api/log",
            (APP_REL / "api/log").as_posix(),
        }:
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "invalid json")
            return

        query_mode = parse_qs(parsed.query).get("mode", [""])[0]
        collection_mode = str(payload.get("collectionMode") or payload.get("runMode") or query_mode or "public").lower()
        if collection_mode not in {"public", "test"}:
            collection_mode = "public"

        log_dir = self.root / APP_REL / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        observed_ip, observed_source = self.observed_client()
        registered_device = registered_device_for_ip(self.root, observed_ip)
        cloudflare_present = bool(self.headers.get("CF-Ray") or self.headers.get("CF-Connecting-IP"))
        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "client": observed_ip,
            "client_ip": observed_ip,
            "client_ip_source": observed_source,
            "peer_ip": self.client_address[0],
            "client_mac": None,
            "client_mac_available": False,
            "client_mac_note": "Client MAC address is not available to this HTTP app after routed/browser access.",
            "cf_connecting_ip": self.headers.get("CF-Connecting-IP"),
            "cf_ray": self.headers.get("CF-Ray"),
            "x_forwarded_for": self.headers.get("X-Forwarded-For"),
            "x_real_ip": self.headers.get("X-Real-IP"),
            "proxy_marker": self.headers.get("X-OpenCampus-Proxy"),
            "proxy_client": self.headers.get("X-OpenCampus-Proxy-Client"),
            "access_route": "cloudflare_tunnel"
            if cloudflare_present
            else ("tailscale_proxy" if self.headers.get("X-OpenCampus-Proxy") == "tailscale-local" else "direct"),
            "collection_mode": collection_mode,
            "access_scope": self.access_scope(observed_ip),
            "registered_device_id": registered_device.get("device_id") if registered_device else None,
            "registered_device_label": registered_device.get("label") if registered_device else None,
            "registered_device_registered_at": registered_device.get("registered_at") if registered_device else None,
            "payload": payload,
        }
        log_name = "test_events.jsonl" if collection_mode == "test" else "events.jsonl"
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with (log_dir / log_name).open("a", encoding="utf-8") as f:
            f.write(line)
        config = load_access_config(self.root)
        if collection_mode == "public" and config.get("split_logs_by_scope", True):
            scoped_name = f"events_{record['access_scope']}.jsonl"
            with (log_dir / scoped_name).open("a", encoding="utf-8") as f:
                f.write(line)

        body = b'{"ok":true}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_device_registration(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "invalid json")
            return

        label = str(payload.get("label") or payload.get("identifierText") or "").strip()
        if not label:
            self.send_error(400, "label required")
            return
        if len(label) > 120:
            label = label[:120]

        now = datetime.now(timezone.utc).isoformat()
        client_ip, client_ip_source = self.observed_client()
        cloudflare_present = bool(self.headers.get("CF-Ray") or self.headers.get("CF-Connecting-IP"))
        device_id = make_device_id(client_ip, label, now)
        log_path, state_path = registry_paths(self.root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "registered_at": now,
            "device_id": device_id,
            "label": label,
            "client_time": payload.get("clientTime"),
            "client_ip": client_ip,
            "client_ip_source": client_ip_source,
            "peer_ip": self.client_address[0],
            "cf_connecting_ip": self.headers.get("CF-Connecting-IP"),
            "cf_ray": self.headers.get("CF-Ray"),
            "x_forwarded_for": self.headers.get("X-Forwarded-For"),
            "x_real_ip": self.headers.get("X-Real-IP"),
            "access_scope": self.access_scope(client_ip),
            "access_route": "cloudflare_tunnel"
            if cloudflare_present
            else ("tailscale_proxy" if self.headers.get("X-OpenCampus-Proxy") == "tailscale-local" else "direct"),
            "user_agent": self.headers.get("User-Agent"),
            "note": str(payload.get("note") or "")[:240],
            "active": True,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

        state = load_registered_devices(self.root)
        devices = [device for device in state.get("devices", []) if device.get("device_id") != device_id]
        devices.append(record)
        state = {
            "updated_at": now,
            "devices": devices,
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        body_obj = {
            "ok": True,
            "device_id": device_id,
            "label": label,
            "client_ip": client_ip,
            "access_scope": record["access_scope"],
            "registered_at": now,
        }
        body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    global APP_REL
    parser = argparse.ArgumentParser(description="Serve the gabor public tree and collect open campus game logs.")
    parser.add_argument("--root", default=os.environ.get("OPEN_CAMPUS_ROOT", "."))
    parser.add_argument("--app-rel", default=os.environ.get("OPEN_CAMPUS_APP_REL", str(APP_REL)))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18381)
    args = parser.parse_args()

    APP_REL = Path(args.app_rel)
    root = Path(args.root).resolve()
    Handler.root = root
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving {root}")
    print(f"Log path: {root / APP_REL / 'logs' / 'events.jsonl'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
