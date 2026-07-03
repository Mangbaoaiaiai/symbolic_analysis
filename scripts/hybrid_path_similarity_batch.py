#!/usr/bin/env python3
"""
Hybrid path matching entry point.

It first ranks candidate paths with the existing 11-dimensional feature-vector
cosine similarity. Low-confidence queries are reranked over all candidates with
VeriBin/BinDiff-style graph overlap. If graph evidence is unavailable or weak,
the feature ranking is kept.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from symbolic_analysis.analysis.hybrid_path_matching import (  # noqa: E402
    HybridConfig,
    hybrid_rank_paths,
    load_matching_bb_map,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid feature-vector + BinDiff graph path matching.")
    parser.add_argument("--old-paths-dir", type=Path, help="Directory containing original path constraint files.")
    parser.add_argument("--new-paths-dir", type=Path, help="Directory containing patched path constraint files.")
    parser.add_argument("--old-prefix", default=None, help="Optional filename prefix for original paths.")
    parser.add_argument("--new-prefix", default=None, help="Optional filename prefix for patched paths.")
    parser.add_argument("--old-path", type=Path, action="append", default=[], help="Single original path file.")
    parser.add_argument("--new-path", type=Path, action="append", default=[], help="Single patched path file.")
    parser.add_argument("--matching-bb-map", type=Path, default=None, help="JSON map of old basic-block/instruction addresses to new addresses.")
    parser.add_argument("--high-threshold", type=float, default=0.80)
    parser.add_argument("--margin-threshold", type=float, default=0.05)
    parser.add_argument("--graph-min-score", type=float, default=0.01)
    parser.add_argument("--graph-weight", type=float, default=1.0)
    parser.add_argument("--feature-weight", type=float, default=0.0)
    parser.add_argument("--out", type=Path, default=Path("hybrid_path_ranking.json"))
    args = parser.parse_args()

    old_paths = list(args.old_path)
    new_paths = list(args.new_path)
    if args.old_paths_dir:
        old_paths.extend(collect_paths(args.old_paths_dir, args.old_prefix))
    if args.new_paths_dir:
        new_paths.extend(collect_paths(args.new_paths_dir, args.new_prefix))
    old_paths = sorted(set(old_paths))
    new_paths = sorted(set(new_paths))

    if not old_paths or not new_paths:
        parser.error("Provide non-empty old and new path inputs.")
    for path in old_paths + new_paths:
        if not path.is_file():
            parser.error(f"Path file not found: {path}")

    config = HybridConfig(
        high_threshold=args.high_threshold,
        margin_threshold=args.margin_threshold,
        graph_min_score=args.graph_min_score,
        graph_weight=args.graph_weight,
        feature_weight=args.feature_weight,
    )
    matching_bb_map = load_matching_bb_map(args.matching_bb_map)
    result = hybrid_rank_paths(old_paths, new_paths, config=config, matching_bb_map=matching_bb_map)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote hybrid ranking for {len(result['queries'])} queries to {args.out}")


def collect_paths(paths_dir: Path, prefix: str | None) -> list[Path]:
    if not paths_dir.is_dir():
        raise SystemExit(f"Directory not found: {paths_dir}")
    out = []
    for path in paths_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".txt" or "path" not in path.stem.lower():
            continue
        if prefix and not path.name.startswith(prefix):
            continue
        out.append(path)
    return out


if __name__ == "__main__":
    main()
