from __future__ import annotations

import csv
import json
import math
import os
import random
import wave
from collections import defaultdict
from pathlib import Path


BASE_DIR = Path(os.environ.get("METHOD_SWEEP_DIR", "/path/to/20260601_method_sweep"))
CORR_PATH = Path(os.environ.get("FEATURE_CORRELATION_CSV", "/path/to/feature_correlation_all_pairs_fixed_window_2p0.csv"))
WEB_BASE = os.environ.get("METHOD_SWEEP_WEB_BASE", "http://localhost:8000/20260601_method_sweep")
GAME_WEB_BASE = os.environ.get("GAME_WEB_BASE", "http://localhost:18082")
MODE = "fixed_window_2p0"
OUT_DIR = Path(__file__).resolve().parent
CLIP_DIR = OUT_DIR / "clips"
OUT_JS = OUT_DIR / "cards_2sec.js"
OUT_SUMMARY = OUT_DIR / "feature_probe_rounds_summary.csv"
OUT_README = OUT_DIR / "FEATURE_PROBE_DATASET.md"

RANDOM_SEED = 20260614
ROUNDS_PER_SESSION = 4
CARDS_PER_ROUND = 4
MIN_TIME_GAP_SEC = 6.0
PREFERRED_ROUND_PAIR_CORR = 0.30
ACCEPTABLE_ROUND_PAIR_CORR = 0.70


METADATA_COLUMNS = {"node_id", "start_sec", "end_sec", "duration_sec"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_float(value: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(out):
        return 0.0
    return out


def load_rows() -> tuple[list[dict[str, object]], list[str]]:
    rows: list[dict[str, object]] = []
    feature_names: list[str] | None = None
    for path in sorted(BASE_DIR.glob(f"*/{MODE}/nodes_features.csv")):
        piece = path.parents[1].name
        raw_rows = read_csv(path)
        if not raw_rows:
            continue
        if feature_names is None:
            feature_names = [name for name in raw_rows[0].keys() if name not in METADATA_COLUMNS]
        for raw in raw_rows:
            row = {
                "piece": piece,
                "node_id": str(raw["node_id"]),
                "start_sec": to_float(raw["start_sec"]),
                "end_sec": to_float(raw["end_sec"]),
                "values": {feature: to_float(raw.get(feature, "0")) for feature in feature_names},
            }
            rows.append(row)
    if feature_names is None:
        raise RuntimeError(f"no nodes_features.csv under {BASE_DIR}")
    return rows, feature_names


def standardize(rows: list[dict[str, object]], features: list[str]) -> dict[str, dict[str, float]]:
    stats = {}
    for feature in features:
        values = [float(row["values"][feature]) for row in rows]  # type: ignore[index]
        mean = sum(values) / len(values)
        var = sum((value - mean) ** 2 for value in values) / max(len(values) - 1, 1)
        stats[feature] = {"mean": mean, "std": math.sqrt(var), "min": min(values), "max": max(values)}
    for row in rows:
        z = {}
        values = row["values"]  # type: ignore[assignment]
        for feature in features:
            std = stats[feature]["std"]
            z[feature] = 0.0 if std <= 1e-12 else (float(values[feature]) - stats[feature]["mean"]) / std
        row["z"] = z
    return stats


def load_redundancy(features: list[str]) -> tuple[dict[str, dict[str, object]], dict[tuple[str, str], float]]:
    max_corr = {feature: 0.0 for feature in features}
    max_partner = {feature: "" for feature in features}
    pair_corr: dict[tuple[str, str], float] = {}
    for row in read_csv(CORR_PATH):
        a = row["feature_a"]
        b = row["feature_b"]
        r = abs(to_float(row["abs_r"]))
        pair_corr[tuple(sorted((a, b)))] = r
        if a in max_corr and r > max_corr[a]:
            max_corr[a] = r
            max_partner[a] = b
        if b in max_corr and r > max_corr[b]:
            max_corr[b] = r
            max_partner[b] = a
    result = {}
    for feature in features:
        corr = max_corr.get(feature, 0.0)
        if corr >= 0.85:
            bucket = "high_redundancy_excluded"
        elif corr <= 0.30:
            bucket = "very_low_redundancy_priority"
        elif corr >= 0.70:
            bucket = "medium_redundancy_candidate"
        else:
            bucket = "low_redundancy_candidate"
        result[feature] = {"max_abs_corr": corr, "max_corr_partner": max_partner.get(feature, ""), "bucket": bucket}
    return result, pair_corr


def feature_pair_corr(pair_corr: dict[tuple[str, str], float], a: str, b: str) -> float:
    if a == b:
        return 1.0
    return pair_corr.get(tuple(sorted((a, b))), 0.0)


def group_max_pair_corr(pair_corr: dict[tuple[str, str], float], group: list[str]) -> float:
    max_corr = 0.0
    for index, a in enumerate(group):
        for b in group[index + 1:]:
            max_corr = max(max_corr, feature_pair_corr(pair_corr, a, b))
    return max_corr


def pack_feature_groups(
    features: list[str],
    redundancy: dict[str, dict[str, object]],
    pair_corr: dict[tuple[str, str], float],
) -> list[list[str]]:
    remaining = features[:]
    groups: list[list[str]] = []
    while remaining:
        group = [remaining.pop(0)]
        for threshold in [PREFERRED_ROUND_PAIR_CORR, 0.50, ACCEPTABLE_ROUND_PAIR_CORR, 0.85]:
            changed = True
            while len(group) < CARDS_PER_ROUND and changed:
                changed = False
                candidates = [
                    feature for feature in remaining
                    if all(feature_pair_corr(pair_corr, feature, selected) < threshold for selected in group)
                ]
                if not candidates:
                    continue
                candidates.sort(
                    key=lambda feature: (
                        0 if redundancy[feature]["bucket"] == "very_low_redundancy_priority" else
                        1 if redundancy[feature]["bucket"] == "low_redundancy_candidate" else 2,
                        group_max_pair_corr(pair_corr, group + [feature]),
                        str(redundancy[feature]["max_abs_corr"]),
                        public_group(feature),
                        feature,
                    )
                )
                chosen = candidates[0]
                remaining.remove(chosen)
                group.append(chosen)
                changed = True
        if len(group) < CARDS_PER_ROUND:
            # This only happens for the final tail; duplicate from the safest previous features.
            filler = sorted(
                features,
                key=lambda feature: (
                    group_max_pair_corr(pair_corr, group + [feature]),
                    float(redundancy[feature]["max_abs_corr"]),
                    feature,
                )
            )
            for feature in filler:
                if feature not in group:
                    group.append(feature)
                if len(group) >= CARDS_PER_ROUND:
                    break
        groups.append(group)
    return groups


def source_audio_path(piece: str) -> Path:
    return BASE_DIR / "subjective_objective_test" / "full_audio" / f"{piece}.wav"


def make_clip(piece: str, node: dict[str, object], role: str, round_id: str, feature: str = "reference") -> str:
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    start = float(node["start_sec"])
    end = float(node["end_sec"])
    node_id = str(node["node_id"])
    safe_feature = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in feature)
    name = f"{round_id}_{role}_{safe_feature}_{piece}_node{node_id}_{start:.3f}_{end:.3f}.wav"
    out_path = CLIP_DIR / name
    if not out_path.exists():
        with wave.open(str(source_audio_path(piece)), "rb") as src:
            params = src.getparams()
            frame_rate = src.getframerate()
            start_frame = max(0, int(start * frame_rate))
            end_frame = max(start_frame + 1, int(end * frame_rate))
            src.setpos(min(start_frame, src.getnframes()))
            frames = src.readframes(max(0, min(end_frame, src.getnframes()) - start_frame))
        with wave.open(str(out_path), "wb") as dst:
            dst.setparams(params)
            dst.writeframes(frames)
    return f"{GAME_WEB_BASE}/clips/{name}"


def media_fragment(piece: str, node: dict[str, object]) -> str:
    start = float(node["start_sec"])
    end = float(node["end_sec"])
    return f"{WEB_BASE}/subjective_objective_test/full_audio/{piece}.wav#t={start:.3f},{end:.3f}"


def feature_rank(source: dict[str, object], target: dict[str, object], features: list[str], feature: str) -> tuple[int, float]:
    diffs = []
    source_z = source["z"]  # type: ignore[assignment]
    target_z = target["z"]  # type: ignore[assignment]
    for name in features:
        diffs.append((abs(float(source_z[name]) - float(target_z[name])), name))
    diffs.sort(key=lambda item: (item[0], item[1]))
    for index, (diff, name) in enumerate(diffs, start=1):
        if name == feature:
            return index, diff
    return len(features), float("inf")


def nearest_target_for_feature(
    source: dict[str, object],
    candidates: list[dict[str, object]],
    features: list[str],
    feature: str,
) -> tuple[dict[str, object], int, float, float]:
    source_z = source["z"]  # type: ignore[assignment]
    best: tuple[float, int, dict[str, object], float] | None = None
    for target in candidates:
        if target["node_id"] == source["node_id"]:
            continue
        if abs(float(target["start_sec"]) - float(source["start_sec"])) < MIN_TIME_GAP_SEC:
            continue
        target_z = target["z"]  # type: ignore[assignment]
        diff = abs(float(source_z[feature]) - float(target_z[feature]))
        rank, ranked_diff = feature_rank(source, target, features, feature)
        # Prefer cards where the target feature is one of the clearest similarity axes.
        score = rank * 2.0 + diff
        if best is None or score < best[0]:
            best = (score, rank, target, ranked_diff)
    if best is None:
        raise RuntimeError(f"no target for {feature} in {source['piece']}")
    score, rank, target, diff = best
    return target, rank, diff, score


def choose_round_source(
    group: list[str],
    rows_by_piece: dict[str, list[dict[str, object]]],
    features: list[str],
    rng: random.Random,
) -> tuple[dict[str, object], list[tuple[str, dict[str, object], int, float, float]]]:
    best: tuple[float, dict[str, object], list[tuple[str, dict[str, object], int, float, float]]] | None = None
    pieces = [piece for piece, rows in rows_by_piece.items() if len(rows) >= 20]
    for _attempt in range(260):
        piece = rng.choice(pieces)
        piece_rows = rows_by_piece[piece]
        source = rng.choice(piece_rows)
        cards = []
        total_score = 0.0
        ok = True
        for feature in group:
            try:
                target, rank, diff, score = nearest_target_for_feature(source, piece_rows, features, feature)
            except RuntimeError:
                ok = False
                break
            cards.append((feature, target, rank, diff, score))
            total_score += score
        if not ok:
            continue
        if best is None or total_score < best[0]:
            best = (total_score, source, cards)
    if best is None:
        raise RuntimeError(f"could not build round for {group}")
    _score, source, cards = best
    return source, cards


def public_group(feature: str) -> str:
    if feature.startswith("chroma_"):
        return "note_name"
    if feature.startswith("audio_chroma_"):
        return "audio_note_name"
    if feature.startswith("tonnetz_") or feature.startswith("mode_") or feature == "key_clarity":
        return "harmony"
    if feature.startswith("mfcc") or feature.startswith("spectral") or feature in {"zcr", "rms"}:
        return "timbre"
    if feature.startswith("pitch") or feature.startswith("interval"):
        return "melody"
    if feature.startswith("ioi") or feature.startswith("note_duration") or feature.startswith("onset") or feature.startswith("tempogram"):
        return "rhythm"
    if feature.startswith("velocity"):
        return "strength"
    return "other"


def build_rounds() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rng = random.Random(RANDOM_SEED)
    rows, all_features = load_rows()
    stats = standardize(rows, all_features)
    active_features = [feature for feature in all_features if stats[feature]["std"] > 1e-12]
    redundancy, pair_corr = load_redundancy(active_features)
    target_features = [
        feature for feature in active_features
        if redundancy[feature]["bucket"] != "high_redundancy_excluded"
    ]
    bucket_order = {
        "very_low_redundancy_priority": 0,
        "low_redundancy_candidate": 1,
        "medium_redundancy_candidate": 2,
    }
    target_features.sort(key=lambda name: (bucket_order[str(redundancy[name]["bucket"])], public_group(name), name))
    very_low = [feature for feature in target_features if redundancy[feature]["bucket"] == "very_low_redundancy_priority"]
    low = [feature for feature in target_features if redundancy[feature]["bucket"] == "low_redundancy_candidate"]
    medium = [feature for feature in target_features if redundancy[feature]["bucket"] == "medium_redundancy_candidate"]
    ordered_features = []
    while very_low:
        ordered_features.append(very_low.pop(0))
    while low or medium:
        if low:
            ordered_features.append(low.pop(0))
        if medium:
            ordered_features.append(medium.pop(0))
    feature_groups = pack_feature_groups(ordered_features, redundancy, pair_corr)

    rows_by_piece: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        rows_by_piece[str(row["piece"])].append(row)

    rounds = []
    summary_rows = []
    for round_index, group in enumerate(feature_groups, start=1):
        round_max_corr = group_max_pair_corr(pair_corr, group)
        source, card_specs = choose_round_source(group, rows_by_piece, active_features, rng)
        piece = str(source["piece"])
        round_id = f"feature_probe_{round_index:02d}"
        cards = []
        very_low_count = 0
        low_count = 0
        medium_count = 0
        for feature, target, rank, diff, score in card_specs:
            red = redundancy[feature]
            if red["bucket"] == "very_low_redundancy_priority":
                very_low_count += 1
            if red["bucket"] in {"very_low_redundancy_priority", "low_redundancy_candidate"}:
                low_count += 1
            if red["bucket"] == "medium_redundancy_candidate":
                medium_count += 1
            card = {
                "feature": feature,
                "group": public_group(feature),
                "publicLabel": "Candidate",
                "piece": piece,
                "mode": MODE,
                "pair": f"source{source['node_id']}_target{target['node_id']}",
                "distance": round(diff, 6),
                "source": make_clip(piece, source, "source", round_id),
                "target": make_clip(piece, target, "target", round_id, feature),
                "sourceStartSec": round(float(source["start_sec"]), 3),
                "sourceEndSec": round(float(source["end_sec"]), 3),
                "targetStartSec": round(float(target["start_sec"]), 3),
                "targetEndSec": round(float(target["end_sec"]), 3),
                "targetNodeId": str(target["node_id"]),
                "sourceNodeId": str(source["node_id"]),
                "targetFeature": feature,
                "featureContributionRank": rank,
                "targetFeatureAbsZDiff": round(diff, 6),
                "featureSelectionScore": round(score, 6),
                "redundancyBucket": red["bucket"],
                "maxAbsCorrelation": round(float(red["max_abs_corr"]), 6),
                "maxCorrelationPartner": red["max_corr_partner"],
            }
            cards.append(card)
            summary_rows.append(
                {
                    "round_id": round_id,
                    "feature": feature,
                    "group": public_group(feature),
                    "piece": piece,
                    "source_node_id": source["node_id"],
                    "target_node_id": target["node_id"],
                    "source_start_sec": card["sourceStartSec"],
                    "target_start_sec": card["targetStartSec"],
                    "feature_contribution_rank": rank,
                    "target_feature_abs_z_diff": card["targetFeatureAbsZDiff"],
                    "redundancy_bucket": red["bucket"],
                    "max_abs_correlation": card["maxAbsCorrelation"],
                    "max_correlation_partner": red["max_corr_partner"],
                    "round_max_feature_pair_abs_corr": round(round_max_corr, 6),
                }
            )
        rounds.append(
            {
                "id": round_id,
                "prompt": "お手本にいちばん近い短い音を選んでください。",
                "piece": piece,
                "mode": MODE,
                "priorityWeight": 1.0 + very_low_count * 0.15 + low_count * 0.05,
                "veryLowFeatureCount": very_low_count,
                "lowOrVeryLowFeatureCount": low_count,
                "mediumFeatureCount": medium_count,
                "roundMaxFeaturePairAbsCorr": round(round_max_corr, 6),
                "roundPairCorrPolicy": {
                    "preferred_lt": PREFERRED_ROUND_PAIR_CORR,
                    "acceptable_lt": ACCEPTABLE_ROUND_PAIR_CORR,
                },
                "sharedSource": {
                    "piece": piece,
                    "nodeId": str(source["node_id"]),
                    "src": make_clip(piece, source, "reference", round_id),
                    "startSec": round(float(source["start_sec"]), 3),
                    "endSec": round(float(source["end_sec"]), 3),
                },
                "cards": cards,
            }
        )
    return rounds, summary_rows


def write_summary(rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "round_id", "feature", "group", "piece", "source_node_id", "target_node_id",
        "source_start_sec", "target_start_sec", "feature_contribution_rank",
        "target_feature_abs_z_diff", "redundancy_bucket", "max_abs_correlation",
        "max_correlation_partner", "round_max_feature_pair_abs_corr",
    ]
    with OUT_SUMMARY.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_readme(rounds: list[dict[str, object]], summary_rows: list[dict[str, object]]) -> None:
    bucket_counts: dict[str, int] = defaultdict(int)
    rank_sum = 0
    for row in summary_rows:
        bucket_counts[str(row["redundancy_bucket"])] += 1
        rank_sum += int(row["feature_contribution_rank"])
    mean_rank = rank_sum / len(summary_rows) if summary_rows else 0.0
    lines = [
        "# Feature Probe 2秒区間カードデータ",
        "",
        "## 目的",
        "",
        "曲全体ではなく、同じ曲内の2秒前後の基準区間に対して、候補区間A-Dのどれが近く聞こえるかを集めるためのカードデータ。",
        "参加者には特徴量名を見せず、ログには候補を作った特徴量、重複度、寄与度順位を保存する。",
        "",
        "## 生成条件",
        "",
        f"- 入力: `{BASE_DIR}`",
        f"- 区間: `{MODE}`",
        "- 対象: `abs(r) < 0.85` の非高重複特徴量",
        f"- ラウンド内の特徴量相関: できる限り `{PREFERRED_ROUND_PAIR_CORR}` 未満、少なくとも `{ACCEPTABLE_ROUND_PAIR_CORR}` 未満を優先",
        f"- ラウンドプール: {len(rounds)}",
        f"- カード数: {len(summary_rows)}",
        f"- 1セッション表示ラウンド数: {ROUNDS_PER_SESSION}",
        f"- 平均寄与度順位: {mean_rank:.2f}",
        "",
        "## 重複度別カード数",
        "",
        "| bucket | cards |",
        "| --- | ---: |",
    ]
    for bucket in sorted(bucket_counts):
        lines.append(f"| `{bucket}` | {bucket_counts[bucket]} |")
    lines += [
        "",
        "## 出力",
        "",
        "- `cards_2sec.js`: Webページが読み込むカードデータ。",
        "- `feature_probe_rounds_summary.csv`: 特徴量ごとのカード選定根拠。",
    ]
    OUT_README.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rounds, summary_rows = build_rounds()
    payload = {
        "schema": "feature_probe_rounds.v1",
        "roundsPerSession": ROUNDS_PER_SESSION,
        "rounds": rounds,
    }
    OUT_JS.write_text("window.MUSIC_MATCH_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    write_summary(summary_rows)
    write_readme(rounds, summary_rows)
    print(f"wrote {OUT_JS} rounds={len(rounds)} cards={len(summary_rows)}")


if __name__ == "__main__":
    main()
