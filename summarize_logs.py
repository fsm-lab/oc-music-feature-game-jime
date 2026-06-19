from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def iter_payloads(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        payload = record.get("payload", record)
        if payload.get("final") and payload.get("results"):
            yield payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Music Match Challenge JSONL logs.")
    parser.add_argument("--input", default="logs/events.jsonl")
    parser.add_argument("--out-dir", default="logs/summary")
    args = parser.parse_args()

    src = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    feature_stats = defaultdict(lambda: {"count": 0, "rank_sum": 0.0, "top1": 0, "top2": 0})
    session_count = 0

    for payload in iter_payloads(src):
        session_count += 1
        for result in payload["results"]:
            for item in result["ranking"]:
                rank = int(item["rank"])
                row = {
                    "session_id": payload["sessionId"],
                    "participant_code": payload["participantCode"],
                    "age_group": payload.get("ageGroup", ""),
                    "round_id": result["roundId"],
                    "elapsed_ms": result["elapsedMs"],
                    "confidence": result["confidence"],
                    "rank": rank,
                    "feature": item["feature"],
                    "group": item["group"],
                    "piece": item["piece"],
                    "segment_mode": item["segmentMode"],
                    "pair": item["pair"],
                }
                rows.append(row)
                stats = feature_stats[item["feature"]]
                stats["count"] += 1
                stats["rank_sum"] += rank
                if rank == 1:
                    stats["top1"] += 1
                if rank <= 2:
                    stats["top2"] += 1

    detail_path = out_dir / "ranking_detail.csv"
    with detail_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "session_id",
            "participant_code",
            "age_group",
            "round_id",
            "elapsed_ms",
            "confidence",
            "rank",
            "feature",
            "group",
            "piece",
            "segment_mode",
            "pair",
        ])
        writer.writeheader()
        writer.writerows(rows)

    summary_rows = []
    for feature, stats in sorted(feature_stats.items()):
        count = stats["count"]
        summary_rows.append({
            "feature": feature,
            "responses": count,
            "mean_rank": round(stats["rank_sum"] / count, 4) if count else "",
            "top1_rate": round(stats["top1"] / count, 4) if count else "",
            "top2_rate": round(stats["top2"] / count, 4) if count else "",
        })

    summary_path = out_dir / "feature_summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["feature", "responses", "mean_rank", "top1_rate", "top2_rate"])
        writer.writeheader()
        writer.writerows(summary_rows)

    report_path = out_dir / "README.md"
    report_path.write_text(
        "\n".join([
            "# Music Match Challenge log summary",
            "",
            f"- sessions: {session_count}",
            f"- ranking rows: {len(rows)}",
            f"- detail: `{detail_path.name}`",
            f"- feature summary: `{summary_path.name}`",
            "",
            "Interpretation:",
            "",
            "- `mean_rank` が小さい特徴量は、参加者が似ていると感じた上位に置かれやすい。",
            "- `top1_rate` は、各ラウンド内で最も似ていると判断された割合である。",
            "- `top2_rate` は、候補として残しやすい特徴量を広めに見るための割合である。",
        ]),
        encoding="utf-8",
    )

    print(f"sessions={session_count}")
    print(f"detail={detail_path}")
    print(f"summary={summary_path}")
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
