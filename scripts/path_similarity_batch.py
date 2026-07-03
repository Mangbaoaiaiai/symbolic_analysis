#!/usr/bin/env python3
"""
Batch path similarity: cosine similarity between path feature vectors, output ranking only (no threshold).

Loads a JSON of path_id -> 11-dim vector (from generate_path_feature_vectors.py), optionally
normalizes using min_max in the file, then:
  - One target: rank all other paths by similarity to target (descending).
  - All-pairs: compute full similarity matrix and output sorted pairs (descending).

Usage:
  python path_similarity_batch.py --vectors path_feature_vectors.json --target s000_O0_path_1 --out ranking.json
  python path_similarity_batch.py --vectors path_feature_vectors.json --all-pairs --top 100 --out pairs.json
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

# Allow importing from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from symbolic_analysis.analysis.path_constraint_features import (
    FEATURE_RANGES,
    normalize_features,
)
from symbolic_analysis.tracing import time_block


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [0, 1] for non-negative vectors; 1 = identical direction."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    # Clamp to [0, 1] for non-negative features
    return max(0.0, min(1.0, dot / (na * nb)))


def _write_report(
    report_path: Path,
    target: str,
    ranking: list[dict],
    vectors: dict[str, list[float]],
    feature_names: list[str],
) -> None:
    """Write a text report: ranking table + 11-dim feature comparison for target vs top-1."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    target_vec = vectors.get(target)
    top_id = ranking[0]["path_id"]
    top_sim = ranking[0]["similarity"]
    top_vec = vectors.get(top_id) or []

    lines = [
        "=" * 80,
        "Path similarity report (normalized feature vectors, cosine similarity)",
        "=" * 80,
        "",
        f"Target path: {target}",
        f"Candidate paths: {len(ranking)} (sorted by similarity descending)",
        "",
        "Ranking (target vs candidates):",
        "-" * 60,
        "Rank\tPath\tSimilarity",
    ]
    for i, r in enumerate(ranking, 1):
        lines.append(f"{i}\t{r['path_id']}\t{r['similarity']}")
    lines.extend([
        "-" * 60,
        "",
        f"Top match: {top_id}  (cosine similarity = {top_sim})",
        "",
        "11-dim feature comparison (normalized [0,1]): target vs top match",
        "-" * 60,
        f"{'Feature':<28}\t{target}\t{top_id}",
        "-" * 60,
    ])
    for j, name in enumerate(feature_names):
        if j < len(target_vec) and j < len(top_vec):
            lines.append(f"{name:<28}\t{target_vec[j]:.4f}\t{top_vec[j]:.4f}")
    lines.append("-" * 60)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report to {report_path}")


def load_vectors(path: Path) -> tuple[dict[str, list[float]], Optional[dict], list[str]]:
    """
    Load vectors JSON. Returns (path_id -> vector, min_max or None, feature_names).
    Prefer normalized_vectors if present; else use vectors and optionally normalize with min_max.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    feature_names = data.get("feature_names", list(FEATURE_RANGES.keys()))
    min_max = None
    if "min_max" in data:
        min_max = {k: tuple(v) for k, v in data["min_max"].items()}

    if "normalized_vectors" in data:
        return data["normalized_vectors"], min_max, feature_names
    vectors = dict(data["vectors"])
    # Optionally normalize with min_max
    if min_max and vectors:
        first = next(iter(vectors.values()))
        if first and (min(first) < 0 or max(first) > 1.01):
            vectors = {
                pid: normalize_features(vec, min_max)
                for pid, vec in vectors.items()
            }
    return vectors, min_max, feature_names


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch path similarity by cosine (ranking only, no threshold)."
    )
    parser.add_argument(
        "--vectors",
        type=Path,
        required=True,
        help="JSON from generate_path_feature_vectors.py (path_id -> 11-dim vector).",
    )
    parser.add_argument(
        "--target",
        type=str,
        help="Path ID to use as target; rank all others by similarity to this.",
    )
    parser.add_argument(
        "--all-pairs",
        action="store_true",
        help="Compute all-pairs similarity and output sorted pairs (no single target).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Limit output to top N by similarity (for --target: N others; for --all-pairs: N pairs).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("path_similarity_ranking.json"),
        help="Output JSON file.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format: json or human-readable table (for --target only).",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="When using --target: only rank paths whose path_id matches this regex (e.g. s000_O1).",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=None,
        help="When using --target: write a text report (ranking + top-1 feature comparison) to this file.",
    )
    args = parser.parse_args()

    if (args.target is None) == (not args.all_pairs):
        parser.error("Provide exactly one of --target or --all-pairs.")

    if not args.vectors.is_file():
        print(f"Error: vectors file not found: {args.vectors}", file=sys.stderr)
        sys.exit(1)

    vectors, min_max, feature_names = load_vectors(args.vectors)
    if not vectors:
        print("No vectors in file.", file=sys.stderr)
        sys.exit(1)

    if args.target:
        if args.target not in vectors:
            print(f"Error: target '{args.target}' not in vectors. Available: {list(vectors.keys())[:5]}...", file=sys.stderr)
            sys.exit(1)
        target_vec = vectors[args.target]
        ranking = []
        filter_re = re.compile(args.filter) if args.filter else None
        with time_block(
            "align",
            "fmcad_cosine_similarity_ranking",
            mode="target",
            target=args.target,
            vector_count=len(vectors),
        ) as trace:
            for pid, vec in vectors.items():
                if pid == args.target:
                    continue
                if filter_re and not filter_re.search(pid):
                    continue
                sim = cosine_similarity(target_vec, vec)
                ranking.append({"path_id": pid, "similarity": round(sim, 4)})
            ranking.sort(key=lambda x: -x["similarity"])
            if args.top is not None:
                ranking = ranking[: args.top]
            trace["candidate_count"] = len(ranking)

        out_data = {
            "target": args.target,
            "ranking": ranking,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "table":
            lines = [
                "Rank\tPath\tSimilarity",
                *[
                    f"{i+1}\t{r['path_id']}\t{r['similarity']}"
                    for i, r in enumerate(ranking)
                ],
            ]
            args.out.write_text("\n".join(lines), encoding="utf-8")
            print("\n".join(lines))
        else:
            args.out.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Wrote ranking of {len(ranking)} paths (target={args.target}) to {args.out}")

        if args.report_out and ranking:
            _write_report(
                args.report_out,
                args.target,
                ranking,
                vectors,
                feature_names,
            )

    else:
        # All-pairs
        ids = sorted(vectors.keys())
        pairs = []
        with time_block(
            "align",
            "fmcad_cosine_similarity_ranking",
            mode="all_pairs",
            vector_count=len(ids),
        ) as trace:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    sim = cosine_similarity(vectors[a], vectors[b])
                    pairs.append({"path_a": a, "path_b": b, "similarity": round(sim, 4)})
            pairs.sort(key=lambda x: -x["similarity"])
            if args.top is not None:
                pairs = pairs[: args.top]
            trace["candidate_count"] = len(pairs)
        out_data = {
            "mode": "all_pairs",
            "pairs": pairs,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {len(pairs)} pairs (all-pairs similarity) to {args.out}")


if __name__ == "__main__":
    main()
