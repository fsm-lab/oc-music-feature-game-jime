from __future__ import annotations

import csv
import json
import os
import urllib.request
from pathlib import Path


BASE = os.environ.get("METHOD_SWEEP_WEB_BASE", "http://localhost:8000/20260601_method_sweep")
OUT = Path(__file__).resolve().parent / "cards_2sec.js"

ROUND_SPECS = [
    {
        "id": "pitch_vs_chroma_2sec",
        "prompt": "2秒前後のまとまりで、メロディや音の高さが近いと感じるカードを上へ。",
        "items": [
            ("Bach_BWV849-01_001_20090916-SMD", "pitch_interval_euclidean", "pitch_interval"),
            ("Bach_BWV849-01_001_20090916-SMD", "pitch_contour_euclidean", "pitch_contour"),
            ("Mozart_KV265_006_20110315-SMD", "chroma_cosine", "notename_distribution"),
            ("Haydn_HobXVINo52-03_008_20110315-SMD", "audio_chroma_cosine", "audio_chroma"),
        ],
    },
    {
        "id": "rhythm_vs_timbre_2sec",
        "prompt": "2秒前後のまとまりで、リズムや音の質感が近いと感じるカードを上へ。",
        "items": [
            ("Mozart_KV265_006_20110315-SMD", "rhythm_density_euclidean", "rhythm_density"),
            ("Beethoven_Op027No1-02_003_20090916-SMD", "rhythm_periodicity_euclidean", "rhythm_periodicity"),
            ("Haydn_HobXVINo52-03_008_20110315-SMD", "spectral_timbre_euclidean", "spectral_timbre"),
            ("Mozart_KV265_006_20110315-SMD", "spectral_contrast_euclidean", "spectral_contrast"),
        ],
    },
    {
        "id": "attack_vs_summary_2sec",
        "prompt": "2秒前後のまとまりで、全体として同じ感じに聞こえるカードを上へ。",
        "items": [
            ("Beethoven_Op027No1-02_003_20090916-SMD", "onset_strength_euclidean", "onset_strength"),
            ("Mozart_KV265_006_20110315-SMD", "mfcc_timbre_euclidean", "mfcc_timbre"),
            ("Haydn_HobXVINo52-03_008_20110315-SMD", "tonnetz_key_euclidean", "tonnetz_key"),
            ("Bach_BWV849-01_001_20090916-SMD", "euclidean_current_6features", "current_6features"),
        ],
    },
]


def read_csv_url(url: str) -> list[dict[str, str]]:
    with urllib.request.urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


def choose_pair(piece: str, method: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    mode = "fixed_window_2p0"
    root = f"{BASE}/{piece}/{mode}"
    nodes = {row["node_id"]: row for row in read_csv_url(f"{root}/nodes_features.csv")}
    edges = read_csv_url(f"{root}/edges_{method}_topk2.csv")
    for edge in edges:
        source = nodes.get(edge["source"])
        target = nodes.get(edge["target"])
        if not source or not target:
            continue
        source_start = float(source["start_sec"])
        target_start = float(target["start_sec"])
        if abs(source_start - target_start) < 4.0:
            continue
        return edge, source, target
    edge = edges[0]
    return edge, nodes[edge["source"]], nodes[edge["target"]]


def media_fragment(piece: str, node: dict[str, str]) -> str:
    start = float(node["start_sec"])
    end = float(node["end_sec"])
    return f"{BASE}/subjective_objective_test/full_audio/{piece}.wav#t={start:.3f},{end:.3f}"


def main() -> None:
    output_rounds = []
    for round_spec in ROUND_SPECS:
        cards = []
        for piece, method, group in round_spec["items"]:
            edge, source, target = choose_pair(piece, method)
            cards.append(
                {
                    "feature": method,
                    "group": group,
                    "publicLabel": "Card",
                    "piece": piece,
                    "mode": "fixed_window_2p0",
                    "pair": f"source{edge['source']}_target{edge['target']}",
                    "distance": edge["distance"],
                    "source": media_fragment(piece, source),
                    "target": media_fragment(piece, target),
                    "sourceStartSec": float(source["start_sec"]),
                    "sourceEndSec": float(source["end_sec"]),
                    "targetStartSec": float(target["start_sec"]),
                    "targetEndSec": float(target["end_sec"]),
                }
            )
        output_rounds.append({"id": round_spec["id"], "prompt": round_spec["prompt"], "cards": cards})

    OUT.write_text(
        "window.MUSIC_MATCH_ROUNDS = " + json.dumps(output_rounds, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
