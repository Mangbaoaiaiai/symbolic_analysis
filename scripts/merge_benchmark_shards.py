#!/usr/bin/env python3
"""Merge independently generated benchmark shards without copying artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ABSOLUTE_KEYS = (
    "left",
    "right",
    "paths_dir",
    "naive_ranking_path",
    "veribin_ranking_path",
    "fmcad_ranking_path",
    "basic_block_map_path",
    "source_case",
    "old_binary",
    "new_binary",
)


def resolve(path: Path, shard: Path) -> str:
    return str(path if path.is_absolute() else (shard / path).resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--duplicate-policy",
        choices=("error", "first", "last"),
        default="error",
        help="How to handle a pair_id present in more than one shard.",
    )
    args = parser.parse_args()

    pairs: list[dict[str, Any]] = []
    truth: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    pair_indexes: dict[str, int] = {}
    for shard_order, shard in enumerate(args.shard):
        manifest_path = shard / "manifest.json"
        if not manifest_path.is_file():
            manifest_path = shard / "manifest.partial.json"
        if not manifest_path.is_file():
            print(f"skip missing manifest: {manifest_path}")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for row in manifest.get("pairs", []):
            pair_id = str(row["pair_id"])
            merged = dict(row)
            for key in ABSOLUTE_KEYS:
                if merged.get(key):
                    merged[key] = resolve(Path(merged[key]), shard)
            truth_row = {
                "pair_id": pair_id,
                "ground_truth": row.get("ground_truth"),
                "ground_truth_pairs": row.get("ground_truth_pairs", {}),
                "path_truth": row.get("path_truth", {}),
                "source_shard": str(shard.resolve()),
                "source_shard_order": shard_order,
            }
            if pair_id in pair_indexes:
                if args.duplicate_policy == "error":
                    raise SystemExit(f"duplicate pair_id across shards: {pair_id}")
                if args.duplicate_policy == "first":
                    continue
                index = pair_indexes[pair_id]
                pairs[index] = merged
                truth[index] = truth_row
                continue
            pair_indexes[pair_id] = len(pairs)
            pairs.append(merged)
            truth.append(truth_row)
        for failure in manifest.get("failures", []):
            item = dict(failure)
            item["source_shard"] = str(shard.resolve())
            failures.append(item)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(
        json.dumps({"pairs": pairs, "failures": failures}, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "groundtruth.json").write_text(
        json.dumps({"pairs": truth}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"merged {len(pairs)} pairs and {len(failures)} failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

