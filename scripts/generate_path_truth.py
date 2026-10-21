#!/usr/bin/env python3
"""Generate path-overlap ranking truth independently of path numbering."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from z3 import Context, Solver, sat, unsat


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _parse(path: Path, ctx: Context):
    from verify_ranked_path_equivalence import parse_formula

    return parse_formula(path, ctx)


def classify_overlap(
    left: Path, right: Path, timeout_ms: int
) -> tuple[str, str]:
    try:
        ctx = Context()
        left_formula = _parse(left, ctx)
        right_formula = _parse(right, ctx)
        solver = Solver(ctx=ctx)
        solver.set("timeout", timeout_ms)
        solver.add(left_formula, right_formula)
        status = solver.check()
        if status == sat:
            return "sat", ""
        if status == unsat:
            return "unsat", ""
        return "unknown", str(solver.reason_unknown())
    except Exception as exc:
        return "unknown", f"parse_or_solver_error:{exc}"


def _parsed_paths(paths: list[Path], ctx: Context) -> list[tuple[Path, Any, str]]:
    parsed: list[tuple[Path, Any, str]] = []
    for path in paths:
        try:
            parsed.append((path, _parse(path, ctx), ""))
        except Exception as exc:  # noqa: BLE001
            parsed.append((path, None, f"parse_error:{exc}"))
    return parsed


def compute_pair_truth(
    old_paths: list[Path],
    new_paths: list[Path],
    timeout_ms: int,
) -> tuple[dict[str, set[str]], dict[str, Any]]:
    queries = []
    related_by_query: dict[str, set[str]] = {}
    ctx = Context()
    parsed_old = _parsed_paths(sorted(old_paths), ctx)
    parsed_new = _parsed_paths(sorted(new_paths), ctx)
    for old_path, old_formula, old_parse_error in parsed_old:
        targets = []
        related = set()
        unknown = []
        unrelated = []
        solver = Solver(ctx=ctx)
        solver.set("timeout", timeout_ms)
        if old_formula is not None:
            solver.add(old_formula)
        for new_path, new_formula, new_parse_error in parsed_new:
            if old_formula is None:
                status, reason = "unknown", old_parse_error
            elif new_formula is None:
                status, reason = "unknown", new_parse_error
            else:
                solver.push()
                solver.add(new_formula)
                result = solver.check()
                unknown_reason = (
                    str(solver.reason_unknown())
                    if result != sat and result != unsat
                    else ""
                )
                solver.pop()
                if result == sat:
                    status, reason = "sat", ""
                elif result == unsat:
                    status, reason = "unsat", ""
                else:
                    status, reason = "unknown", unknown_reason
            record = {"target": new_path.stem, "status": status}
            if reason:
                record["reason"] = reason
            targets.append(record)
            if status == "sat":
                related.add(new_path.stem)
            elif status == "unknown":
                unknown.append(new_path.stem)
            else:
                unrelated.append(new_path.stem)
        related_by_query[old_path.stem] = related
        queries.append(
            {
                "query": old_path.stem,
                "targets": targets,
                "related_targets": sorted(related),
                "unknown_targets": unknown,
                "unrelated_targets": unrelated,
            }
        )
    return related_by_query, {
        "schema": "symbolicana.path_truth.v1",
        "semantics": "sat_input_overlap",
        "timeout_ms": timeout_ms,
        "queries": queries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths-dir", type=Path, required=True)
    parser.add_argument("--old-prefix", default="symbolic_oldV")
    parser.add_argument("--new-prefix", default="symbolic_newV")
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    old_paths = sorted(
        args.paths_dir.glob(f"{args.old_prefix}_path_*.txt"),
        key=lambda path: _path_number(path.stem),
    )
    new_paths = sorted(
        args.paths_dir.glob(f"{args.new_prefix}_path_*.txt"),
        key=lambda path: _path_number(path.stem),
    )
    related, output = compute_pair_truth(old_paths, new_paths, args.timeout_ms)
    output["pair_truth"] = {
        query: sorted(targets) for query, targets in related.items()
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote path truth for {len(output['queries'])} queries to {args.out}")
    return 0


def _path_number(path_id: str) -> int:
    try:
        return int(path_id.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
