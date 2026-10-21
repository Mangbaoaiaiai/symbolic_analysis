#!/usr/bin/env python3
"""Split an OSF manifest into disjoint, cost-balanced experiment shards."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def estimate_cost(
    row: dict[str, str],
    historical: dict[str, dict[str, str]],
) -> float:
    if row.get("support_status") == "unsupported":
        return 0.01
    prior = historical.get(row.get("case_id", "").casefold(), {})
    score = 1.0
    try:
        paths = int(prior.get("old_path_count", 0) or 0) + int(
            prior.get("new_path_count", 0) or 0
        )
        score += math.sqrt(max(paths, 0))
    except ValueError:
        pass
    try:
        score += min(max(float(prior.get("t_total", 0) or 0), 0.0), 3600.0) / 600
    except ValueError:
        pass
    category = prior.get("failure_category", "")
    if category == "sigkill_or_oom":
        score += 30
    elif category == "symbolic_timeout":
        score += 15
    elif category == "incomplete_symbolic_exploration":
        score += 5
    return score


def split_rows(
    rows: Iterable[dict[str, str]],
    historical: dict[str, dict[str, str]],
    shard_count: int,
) -> list[list[dict[str, str]]]:
    if shard_count <= 0:
        raise ValueError("shard count must be positive")
    bins: list[list[dict[str, str]]] = [[] for _ in range(shard_count)]
    loads = [0.0] * shard_count
    ranked = sorted(
        rows,
        key=lambda row: (
            -estimate_cost(row, historical),
            row.get("case_id", "").casefold(),
        ),
    )
    for row in ranked:
        index = min(range(shard_count), key=lambda item: (loads[item], item))
        bins[index].append(row)
        loads[index] += estimate_cost(row, historical)
    for shard in bins:
        shard.sort(key=lambda row: row.get("case_id", "").casefold())
    return bins


def write_manifest(
    path: Path,
    fields: list[str],
    rows: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--historical-audit", type=Path)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    fields, rows = read_rows(args.manifest)
    historical: dict[str, dict[str, str]] = {}
    if args.historical_audit:
        _fields, prior_rows = read_rows(args.historical_audit)
        historical = {
            row["case_id"].casefold(): row
            for row in prior_rows
            if row.get("case_id")
        }
    shards = split_rows(rows, historical, args.shards)

    args.output_root.mkdir(parents=True, exist_ok=True)
    metadata: list[dict[str, Any]] = []
    for index, shard_rows in enumerate(shards):
        path = args.output_root / f"shard_{index:02d}.csv"
        write_manifest(path, fields, shard_rows)
        metadata.append(
            {
                "index": index,
                "manifest": path.name,
                "cases": len(shard_rows),
                "estimated_cost": round(
                    sum(estimate_cost(row, historical) for row in shard_rows),
                    4,
                ),
                "case_ids": [row["case_id"] for row in shard_rows],
            }
        )
    with (args.output_root / "shards.json").open("w", encoding="utf-8") as stream:
        json.dump(
            {
                "source_cases": len(rows),
                "shards": metadata,
            },
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
    print(
        json.dumps(
            {
                "source_cases": len(rows),
                "shards": [
                    {
                        "manifest": item["manifest"],
                        "cases": item["cases"],
                        "estimated_cost": item["estimated_cost"],
                    }
                    for item in metadata
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
