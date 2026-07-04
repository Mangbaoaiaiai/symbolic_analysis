#!/usr/bin/env python3
"""Build a manifest/ground-truth benchmark from TSVC path constraint files.

The generated benchmark is path-level: each record represents one program under
two optimization levels, and each query path is matched to the same path index
in the target optimization level.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any


PATH_RE = re.compile(r"^(?P<program>.+)_(?P<opt>O[0-3])_path_(?P<idx>\d+)\.txt$")

DEFAULT_SUBSETS = {
    "A": ("O1", "O1"),
    "B": ("O1", "O3"),
    "C": ("O2", "O3"),
    "D": ("O0", "O3"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate TSVC path benchmark manifests.")
    parser.add_argument("--paths-dir", type=Path, default=Path("data/tsvc/paths"))
    parser.add_argument("--vectors", type=Path, default=Path("data/tsvc/path_vectors.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("benchmarks/tsvc_paths"))
    parser.add_argument(
        "--veribin-rankings-dir",
        type=Path,
        default=None,
        help="Optional directory containing VeriBin ranking JSON files laid out as <subset>/<program>.json.",
    )
    args = parser.parse_args()

    root = Path.cwd()
    paths_dir = (root / args.paths_dir).resolve()
    vectors_path = (root / args.vectors).resolve()
    out_dir = (root / args.out_dir).resolve()
    veribin_rankings_dir = (root / args.veribin_rankings_dir).resolve() if args.veribin_rankings_dir else None

    grouped = collect_paths(paths_dir)
    vectors = load_vectors(vectors_path)
    manifest_rows: list[dict[str, Any]] = []
    truth_rows: list[dict[str, Any]] = []

    for subset, (left_opt, right_opt) in DEFAULT_SUBSETS.items():
        for program in sorted(grouped):
            left_paths = grouped[program].get(left_opt, {})
            right_paths = grouped[program].get(right_opt, {})
            common_indices = sorted(set(left_paths) & set(right_paths))
            if not common_indices:
                continue

            pair_id = f"{subset}/{program}_{left_opt}_vs_{right_opt}"
            pair_name = pair_id.split("/", 1)[1]
            left_ids = [path_id(program, left_opt, idx) for idx in common_indices]
            right_ids = [path_id(program, right_opt, idx) for idx in common_indices]
            truth_pairs = dict(zip(left_ids, right_ids))

            ranking_rel = Path("rankings") / subset / f"{pair_name}.json"
            ranking_abs = out_dir / ranking_rel
            ranking_abs.parent.mkdir(parents=True, exist_ok=True)
            ranking_abs.write_text(
                json.dumps(
                    build_ranking(pair_id, left_ids, right_ids, vectors),
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            left_first = left_paths[common_indices[0]]
            right_first = right_paths[common_indices[0]]
            base_row = {
                "pair_id": pair_id,
                "subset": subset,
                "program": pair_name,
                "ground_truth": True,
                "original_path_count": len(left_ids),
                "patched_path_count": len(right_ids),
                "left_opt": left_opt,
                "right_opt": right_opt,
                "left_path_ids": left_ids,
                "right_path_ids": right_ids,
                "ground_truth_pairs": truth_pairs,
            }
            truth_rows.append(base_row)
            manifest_rows.append(
                {
                    **base_row,
                    "left": rel_to(left_first, out_dir),
                    "right": rel_to(right_first, out_dir),
                    "paths_dir": rel_to(paths_dir, out_dir),
                    "left_path_files": [rel_to(left_paths[idx], out_dir) for idx in common_indices],
                    "right_path_files": [rel_to(right_paths[idx], out_dir) for idx in common_indices],
                    "ranking_path": str(ranking_rel),
                    "fmcad_ranking_path": str(ranking_rel),
                    **optional_veribin_ranking(veribin_rankings_dir, subset, pair_name, out_dir),
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(
        json.dumps({"pairs": manifest_rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "groundtruth.json").write_text(
        json.dumps({"pairs": truth_rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(manifest_rows)} TSVC benchmark records to {out_dir}")
    print(f"Ground truth: {out_dir / 'groundtruth.json'}")
    return 0


def collect_paths(paths_dir: Path) -> dict[str, dict[str, dict[int, Path]]]:
    grouped: dict[str, dict[str, dict[int, Path]]] = {}
    for path in sorted(paths_dir.glob("*.txt")):
        match = PATH_RE.match(path.name)
        if not match:
            continue
        program = match.group("program")
        opt = match.group("opt")
        idx = int(match.group("idx"))
        grouped.setdefault(program, {}).setdefault(opt, {})[idx] = path
    return grouped


def load_vectors(vectors_path: Path) -> dict[str, list[float]]:
    if not vectors_path.is_file():
        return {}
    data = json.loads(vectors_path.read_text(encoding="utf-8"))
    raw_vectors = data.get("vectors", data if isinstance(data, dict) else {})
    return {str(key): [float(x) for x in value] for key, value in raw_vectors.items()}


def build_ranking(
    pair_id: str,
    left_ids: list[str],
    right_ids: list[str],
    vectors: dict[str, list[float]],
) -> dict[str, Any]:
    queries = []
    for left_id in left_ids:
        ranked = []
        for right_id in right_ids:
            ranked.append(
                {
                    "path_id": right_id,
                    "similarity": round(cosine(vectors.get(left_id), vectors.get(right_id)), 6),
                }
            )
        ranked.sort(key=lambda item: (-item["similarity"], item["path_id"]))
        queries.append({"query": left_id, "ranking": ranked})
    return {"pair_id": pair_id, "queries": queries}


def optional_veribin_ranking(
    rankings_dir: Path | None,
    subset: str,
    pair_name: str,
    out_dir: Path,
) -> dict[str, str]:
    if rankings_dir is None:
        return {}
    path = rankings_dir / subset / f"{pair_name}.json"
    if not path.is_file():
        return {}
    return {"veribin_ranking_path": rel_to(path, out_dir)}


def cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def path_id(program: str, opt: str, idx: int) -> str:
    return f"{program}_{opt}_path_{idx}"


def rel_to(path: Path, base: Path) -> str:
    return os.path.relpath(path.resolve(), base.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
