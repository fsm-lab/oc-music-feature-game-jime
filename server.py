from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "events.jsonl"
TEST_LOG_PATH = LOG_DIR / "test_events.jsonl"
ACCESS_CONFIG_PATH = ROOT / "access_control.json"


def load_access_config() -> dict:
    default = {
        "enabled": False,
        "allowed_cidrs": ["127.0.0.1/32", "::1/128"],
        "split_logs_by_scope": True,
        "lab_cidrs": ["127.0.0.1/32", "::1/128"],
        "warp_cidrs": [],
        "deny_message": "This page is only available from the allowed network.",
    }
    if not ACCESS_CONFIG_PATH.exists():
        return default
    try:
        loaded = json.loads(ACCESS_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return {**default, **loaded}


def registry_paths() -> tuple[Path, Path]:
    return LOG_DIR / "device_registry.jsonl", ROOT / "registered_devices.json"


def load_registered_devices() -> dict:
    _log_path, state_path = registry_paths()
    if not state_path.exists():
        return {"devices": []}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"devices": []}
    if not isinstance(data.get("devices"), list):
        return {"devices": []}
    return data


def registered_device_for_ip(client_ip: str) -> dict | None:
    devices = load_registered_devices().get("devices", [])
    matches = [device for device in devices if device.get("client_ip") == client_ip and device.get("active", True)]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.get("registered_at", ""))[-1]


def make_device_id(client_ip: str, label: str, server_time: str) -> str:
    digest = hashlib.sha256(f"{client_ip}|{label}|{server_time}".encode("utf-8")).hexdigest()
    return f"dev-{digest[:16]}"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def client_ip(self) -> ipaddress._BaseAddress | None:
        try:
            return ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return None

    def ip_in_cidrs(self, client_ip: ipaddress._BaseAddress, cidrs: list[str]) -> bool:
        for cidr in cidrs:
            try:
                if client_ip in ipaddress.ip_network(str(cidr), strict=False):
                    return True
            except ValueError:
                continue
        return False

    def access_scope(self) -> str:
        config = load_access_config()
        client_ip = self.client_ip()
        if client_ip is None:
            return "unknown"
        if self.ip_in_cidrs(client_ip, config.get("warp_cidrs", [])):
            return "warp"
        if self.ip_in_cidrs(client_ip, config.get("lab_cidrs", [])):
            return "lab"
        return "external"

    def access_allowed(self) -> bool:
        config = load_access_config()
        if not config.get("enabled"):
            return True
        client_ip = self.client_ip()
        if client_ip is None:
            return False
        if self.ip_in_cidrs(client_ip, config.get("allowed_cidrs", [])):
            return True
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "client": str(client_ip),
            "path": self.path,
            "reason": "ip_not_allowed",
        }
        with (LOG_DIR / "access_denied.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return False

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
        if parsed.path == "/api/register-device":
            self.handle_device_registration()
            return
        if parsed.path != "/api/log":
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

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        registered_device = registered_device_for_ip(self.client_address[0])
        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "client": self.client_address[0],
            "client_ip": self.client_address[0],
            "client_mac": None,
            "client_mac_available": False,
            "client_mac_note": "Client MAC address is not available to this HTTP app after routed/browser access.",
            "proxy_marker": self.headers.get("X-OpenCampus-Proxy"),
            "proxy_client": self.headers.get("X-OpenCampus-Proxy-Client"),
            "access_route": "tailscale_proxy" if self.headers.get("X-OpenCampus-Proxy") == "tailscale-local" else "direct",
            "collection_mode": collection_mode,
            "access_scope": self.access_scope(),
            "registered_device_id": registered_device.get("device_id") if registered_device else None,
            "registered_device_label": registered_device.get("label") if registered_device else None,
            "registered_device_registered_at": registered_device.get("registered_at") if registered_device else None,
            "payload": payload,
        }
        log_path = TEST_LOG_PATH if collection_mode == "test" else LOG_PATH
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
        config = load_access_config()
        if collection_mode == "public" and config.get("split_logs_by_scope", True):
            scoped_path = LOG_DIR / f"events_{record['access_scope']}.jsonl"
            with scoped_path.open("a", encoding="utf-8") as f:
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
        client_ip = self.client_address[0]
        device_id = make_device_id(client_ip, label, now)
        log_path, state_path = registry_paths()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "registered_at": now,
            "device_id": device_id,
            "label": label,
            "client_time": payload.get("clientTime"),
            "client_ip": client_ip,
            "access_scope": self.access_scope(),
            "access_route": "tailscale_proxy" if self.headers.get("X-OpenCampus-Proxy") == "tailscale-local" else "direct",
            "user_agent": self.headers.get("User-Agent"),
            "note": str(payload.get("note") or "")[:240],
            "active": True,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

        state = load_registered_devices()
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
    parser = argparse.ArgumentParser(description="Serve the open campus music match game and collect JSONL logs.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18082)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving {ROOT}")
    print(f"Open {url}")
    print(f"Logs: {LOG_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
