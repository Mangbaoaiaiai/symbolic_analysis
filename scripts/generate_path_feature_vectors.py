#!/usr/bin/env python3
"""
Generate 11-dimensional feature vectors for path constraint files.

Reads path constraint files (SMT-LIB style), extracts 11 features per path,
and writes:
  - Raw and normalized vectors per path (JSON).
  - Optional per-feature min/max for the dataset (for later normalization).

Usage:
  python generate_path_feature_vectors.py --paths-dir data/tsvc/paths --out vectors.json
  python generate_path_feature_vectors.py --path-file data/tsvc/paths/s000_O0_path_1.txt --out single.json
"""

import argparse
import json
import sys
from pathlib import Path

# Allow importing from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from symbolic_analysis.analysis.path_constraint_features import (
    FEATURE_RANGES,
    extract_features,
    normalize_features,
)

FEATURE_NAMES = [
    "assert_count",
    "variable_count",
    "main_bv_width",
    "operator_type_count",
    "comparison_ratio",
    "nest_depth",
    "dominant_constant_type",
    "variable_range_span",
    "shift_coefficient",
    "extend_count",
    "extract_count",
]


def collect_path_files(paths_dir: Path) -> list[tuple[str, Path]]:
    """Return list of (path_id, file_path). path_id = stem, e.g. s000_O0_path_1."""
    out = []
    for f in sorted(paths_dir.iterdir()):
        if f.is_file() and f.suffix.lower() == ".txt" and "path" in f.stem.lower():
            out.append((f.stem, f))
    return out


def compute_dataset_min_max(records: list[dict]) -> dict[str, tuple[float, float]]:
    """Compute per-feature min/max from list of {path_id, raw: [...]}."""
    if not records or not records[0].get("raw"):
        return dict(FEATURE_RANGES)
    n = len(records[0]["raw"])
    mins = [min(r["raw"][i] for r in records) for i in range(n)]
    maxs = [max(r["raw"][i] for r in records) for i in range(n)]
    names = list(FEATURE_RANGES.keys())
    return {names[i]: (mins[i], maxs[i]) for i in range(n)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate path constraint feature vectors (11-dim) for similarity ranking."
    )
    parser.add_argument(
        "--paths-dir",
        type=Path,
        help="Directory containing path_*.txt constraint files.",
    )
    parser.add_argument(
        "--path-file",
        type=Path,
        help="Single path constraint file (alternative to --paths-dir).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("path_feature_vectors.json"),
        help="Output JSON file (vectors + optional min_max).",
    )
    parser.add_argument(
        "--include-min-max",
        action="store_true",
        help="Compute and include per-feature min/max from dataset for normalization.",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Include normalized vectors using dataset min/max (or default ranges).",
    )
    args = parser.parse_args()

    if (args.paths_dir is None) == (args.path_file is None):
        parser.error("Provide exactly one of --paths-dir or --path-file.")

    if args.path_file:
        files = [(args.path_file.stem, args.path_file)]
        if not args.path_file.is_file():
            print(f"Error: file not found: {args.path_file}", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.paths_dir.is_dir():
            print(f"Error: directory not found: {args.paths_dir}", file=sys.stderr)
            sys.exit(1)
        files = collect_path_files(args.paths_dir)

    records = []
    for path_id, path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"Warning: skip {path}: {e}", file=sys.stderr)
            continue
        raw, _ = extract_features(content)
        rec = {"path_id": path_id, "raw": raw}
        records.append(rec)

    if not records:
        print("No path files processed.", file=sys.stderr)
        sys.exit(1)

    min_max = None
    if args.include_min_max or args.normalize:
        min_max = compute_dataset_min_max(records)

    if args.normalize and min_max:
        for r in records:
            r["normalized"] = normalize_features(r["raw"], min_max)

    out_data = {
        "feature_names": FEATURE_NAMES,
        "vectors": {r["path_id"]: r["raw"] for r in records},
        "vectors_by_path": records,
    }
    if min_max:
        out_data["min_max"] = {k: [lo, hi] for k, (lo, hi) in min_max.items()}
    if args.normalize and min_max:
        out_data["normalized_vectors"] = {
            r["path_id"]: r["normalized"] for r in records
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(records)} path vectors to {args.out}")


if __name__ == "__main__":
    main()
