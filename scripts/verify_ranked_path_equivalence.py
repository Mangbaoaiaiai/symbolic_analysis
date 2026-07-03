#!/usr/bin/env python3
"""Verify program equivalence by following a ranked path-pair queue."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from z3 import And, BitVec, BitVecVal, BoolVal, Context, Not, Or, Solver, parse_smt2_string, sat, unsat

RETURN_EQ_TIMEOUT_MS = 5_000


def clean_smt(content: str) -> str:
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("(check-sat"):
            continue
        if line.startswith("(") or line == ")":
            lines.append(line)
    return "\n".join(lines)


def formula_from_smt_text(smt_text: str, ctx: Context):
    content = clean_smt(smt_text)
    formulas = parse_smt2_string(content, ctx=ctx)
    if len(formulas) == 0:
        return BoolVal(True, ctx=ctx)
    if len(formulas) == 1:
        return formulas[0]
    return And(*formulas)


def parse_formula(path: Path, ctx: Context):
    return formula_from_smt_text(path.read_text(encoding="utf-8", errors="replace"), ctx)


def verify_path_pair(left: Path, right: Path, timeout_ms: int) -> tuple[bool | None, float]:
    start = time.perf_counter()
    ctx = Context()
    formula_left = parse_formula(left, ctx)
    formula_right = parse_formula(right, ctx)
    solver = Solver(ctx=ctx)
    solver.set("timeout", timeout_ms)
    solver.add(Or(And(formula_left, Not(formula_right)), And(Not(formula_left), formula_right)))
    status = solver.check()
    elapsed = time.perf_counter() - start
    if status == unsat:
        return True, elapsed
    if str(status) == "sat":
        return False, elapsed
    return None, elapsed


def verify_formula_equivalence(left_smt: str, right_smt: str, timeout_ms: int) -> tuple[bool | None, float]:
    start = time.perf_counter()
    ctx = Context()
    formula_left = formula_from_smt_text(left_smt, ctx)
    formula_right = formula_from_smt_text(right_smt, ctx)
    solver = Solver(ctx=ctx)
    solver.set("timeout", timeout_ms)
    solver.add(Or(And(formula_left, Not(formula_right)), And(Not(formula_left), formula_right)))
    status = solver.check()
    elapsed = time.perf_counter() - start
    if status == unsat:
        return True, elapsed
    if str(status) == "sat":
        return False, elapsed
    return None, elapsed


def extract_semantic_summary(path: Path) -> dict[str, Any] | None:
    prefix = "; Semantic summary JSON:"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            try:
                return json.loads(line[len(prefix):].strip())
            except json.JSONDecodeError:
                return None
    return None


def verify_semantic_path_pair(left: Path, right: Path, timeout_ms: int) -> tuple[bool | None, float, dict[str, Any]]:
    left_summary = extract_semantic_summary(left)
    right_summary = extract_semantic_summary(right)
    details: dict[str, Any] = {
        "input_space_equivalent": None,
        "return_value_equivalent": None,
        "memory_state_equivalent": None,
        "global_state_equivalent": None,
        "semantic_mode": "input_return_heap_global",
    }

    input_eq, input_time = verify_path_pair(left, right, timeout_ms)
    details["input_space_equivalent"] = input_eq
    total_time = input_time
    if input_eq is not True:
        return input_eq, total_time, details

    if left_summary is None or right_summary is None:
        details["semantic_mode"] = "fallback_constraint_only"
        return input_eq, total_time, details

    return_eq, return_time = verify_return_equivalence(left_summary, right_summary, timeout_ms)
    total_time += return_time
    details["return_value_equivalent"] = return_eq
    if return_eq is not True:
        return return_eq, total_time, details

    memory_eq = compare_state_summary(left_summary.get("memory_state"), right_summary.get("memory_state"))
    details["memory_state_equivalent"] = memory_eq
    if memory_eq is not True:
        return False, total_time, details

    global_eq = compare_state_summary(left_summary.get("global_state"), right_summary.get("global_state"))
    details["global_state_equivalent"] = global_eq
    if global_eq is not True:
        return False, total_time, details

    return True, total_time, details


def verify_semantic_path_relation(left: Path, right: Path, timeout_ms: int) -> tuple[bool | None, float, int, dict[str, Any]]:
    """Check whether two paths agree on their overlapping input region."""
    start = time.perf_counter()
    ctx = Context()
    left_constraint = parse_formula(left, ctx)
    right_constraint = parse_formula(right, ctx)
    overlap_solver = Solver(ctx=ctx)
    overlap_solver.set("timeout", timeout_ms)
    overlap_solver.add(left_constraint, right_constraint)
    overlap_status = overlap_solver.check()
    elapsed = time.perf_counter() - start
    smt_calls = 1

    details: dict[str, Any] = {
        "input_overlap": str(overlap_status),
        "return_value_equivalent": None,
        "memory_state_equivalent": None,
        "global_state_equivalent": None,
        "semantic_mode": "input_return_heap_global_overlap",
    }
    if overlap_status == unsat:
        return False, elapsed, smt_calls, details
    if overlap_status != sat:
        return None, elapsed, smt_calls, details

    left_summary = extract_semantic_summary(left)
    right_summary = extract_semantic_summary(right)
    if left_summary is None or right_summary is None:
        # Old path files only contain constraints. In that compatibility mode,
        # an overlapping region is considered a possible semantic match.
        details["semantic_mode"] = "fallback_overlap_only"
        return True, elapsed, smt_calls, details

    return_eq, return_time, return_calls = verify_return_equivalence_on_overlap(
        left_summary, right_summary, timeout_ms
    )
    elapsed += return_time
    smt_calls += return_calls
    details["return_value_equivalent"] = return_eq
    if return_eq is not True:
        return return_eq, elapsed, smt_calls, details

    memory_eq = compare_state_summary(left_summary.get("memory_state"), right_summary.get("memory_state"))
    details["memory_state_equivalent"] = memory_eq
    if memory_eq is not True:
        return False, elapsed, smt_calls, details

    global_eq = compare_state_summary(left_summary.get("global_state"), right_summary.get("global_state"))
    details["global_state_equivalent"] = global_eq
    if global_eq is not True:
        return False, elapsed, smt_calls, details

    return True, elapsed, smt_calls, details


def verify_return_equivalence(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
) -> tuple[bool | None, float]:
    left_return = left_summary.get("return_value") or {}
    right_return = right_summary.get("return_value") or {}
    if not left_return.get("available") and not right_return.get("available"):
        return True, 0.0
    if not left_return.get("available") or not right_return.get("available"):
        return False, 0.0
    if int(left_return.get("bits", 0) or 0) != int(right_return.get("bits", 0) or 0):
        return False, 0.0
    left_smt = left_return.get("smt")
    right_smt = right_return.get("smt")
    if not left_smt or not right_smt:
        return (left_return.get("repr") == right_return.get("repr")), 0.0
    equivalent, elapsed, _calls = verify_return_smt_equivalence(
        left_return, right_return, timeout_ms
    )
    return equivalent, elapsed


def verify_return_equivalence_on_overlap(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
) -> tuple[bool | None, float, int]:
    left_return = left_summary.get("return_value") or {}
    right_return = right_summary.get("return_value") or {}
    if not left_return.get("available") and not right_return.get("available"):
        return True, 0.0, 0
    if not left_return.get("available") or not right_return.get("available"):
        return False, 0.0, 0
    if int(left_return.get("bits", 0) or 0) != int(right_return.get("bits", 0) or 0):
        return False, 0.0, 0
    left_smt = left_return.get("smt")
    right_smt = right_return.get("smt")
    left_var = return_variable_name(left_smt)
    right_var = return_variable_name(right_smt)
    if not left_smt or not right_smt or not left_var or not right_var:
        return (left_return.get("repr") == right_return.get("repr")), 0.0, 0
    return verify_return_smt_equivalence(left_return, right_return, timeout_ms)


def verify_return_smt_equivalence(
    left_return: dict[str, Any],
    right_return: dict[str, Any],
    timeout_ms: int,
) -> tuple[bool | None, float, int]:
    left_smt = left_return.get("smt")
    right_smt = right_return.get("smt")
    left_var = return_variable_name(left_smt)
    right_var = return_variable_name(right_smt)
    if not left_smt or not right_smt or not left_var or not right_var:
        return (left_return.get("repr") == right_return.get("repr")), 0.0, 0

    bits = int(left_return["bits"])
    right_var_renamed = f"{right_var}__right"
    right_smt = re.sub(rf"\b{re.escape(right_var)}\b", right_var_renamed, right_smt)
    use_float_numeric_equivalence = should_use_float_numeric_return_equivalence(left_return, right_return)
    if use_float_numeric_equivalence:
        non_nan_assumptions = fp_input_non_nan_assumptions(left_smt, right_smt)
        left_smt = append_smt_assertions(left_smt, non_nan_assumptions)

    start = time.perf_counter()
    ctx = Context()
    left_formula = formula_from_smt_text(left_smt, ctx)
    right_formula = formula_from_smt_text(right_smt, ctx)
    solver = Solver(ctx=ctx)
    solver.set("timeout", min(timeout_ms, RETURN_EQ_TIMEOUT_MS))
    left_ret = BitVec(left_var, bits, ctx=ctx)
    right_ret = BitVec(right_var_renamed, bits, ctx=ctx)
    if use_float_numeric_equivalence:
        neq = float_numeric_not_equal(left_ret, right_ret, bits, ctx)
    else:
        neq = left_ret != right_ret
    solver.add(left_formula, right_formula, neq)
    status = solver.check()
    elapsed = time.perf_counter() - start
    if status == unsat:
        return True, elapsed, 1
    if status == sat:
        return False, elapsed, 1
    return None, elapsed, 1


def should_use_float_numeric_return_equivalence(
    left_return: dict[str, Any],
    right_return: dict[str, Any],
) -> bool:
    bits = int(left_return.get("bits", 0) or 0)
    if bits not in {32, 64}:
        return False
    text = " ".join(
        str(value or "")
        for value in (
            left_return.get("repr"),
            right_return.get("repr"),
            left_return.get("smt"),
            right_return.get("smt"),
        )
    )
    return any(marker in text for marker in ("fpToIEEEBV", "fp.to_ieee_bv", "FPV(", "FloatingPoint"))


def fp_input_non_nan_assumptions(*smt_texts: str) -> list[str]:
    names: set[str] = set()
    pattern = re.compile(r"\(declare-fun\s+([A-Za-z_][A-Za-z0-9_]*)\s+\(\)\s+\(_\s+FloatingPoint\b")
    for smt_text in smt_texts:
        names.update(pattern.findall(smt_text or ""))
    return [f"(assert (not (fp.isNaN {name})))" for name in sorted(names) if name.startswith("FP_arg_")]


def append_smt_assertions(smt_text: str, assertions: list[str]) -> str:
    if not assertions:
        return smt_text
    return "\n".join([smt_text, *assertions])


def float_numeric_not_equal(left_ret, right_ret, bits: int, ctx: Context):
    """Return a BV predicate for IEEE754 numeric inequality.

    This keeps normal bit-equality, treats +0.0 and -0.0 as equal numeric
    zeros, and treats NaN payload/sign differences as one abstract NaN result.
    """
    if bits == 64:
        exponent_bits = 11
        mantissa_bits = 52
    elif bits == 32:
        exponent_bits = 8
        mantissa_bits = 23
    else:
        return left_ret != right_ret

    abs_mask = BitVecVal((1 << (bits - 1)) - 1, bits, ctx=ctx)
    exponent_mask = ((1 << exponent_bits) - 1) << mantissa_bits
    mantissa_mask = (1 << mantissa_bits) - 1

    left_abs = left_ret & abs_mask
    right_abs = right_ret & abs_mask
    both_zero = And(left_abs == BitVecVal(0, bits, ctx=ctx), right_abs == BitVecVal(0, bits, ctx=ctx))

    left_nan = And(
        (left_abs & BitVecVal(exponent_mask, bits, ctx=ctx)) == BitVecVal(exponent_mask, bits, ctx=ctx),
        (left_abs & BitVecVal(mantissa_mask, bits, ctx=ctx)) != BitVecVal(0, bits, ctx=ctx),
    )
    right_nan = And(
        (right_abs & BitVecVal(exponent_mask, bits, ctx=ctx)) == BitVecVal(exponent_mask, bits, ctx=ctx),
        (right_abs & BitVecVal(mantissa_mask, bits, ctx=ctx)) != BitVecVal(0, bits, ctx=ctx),
    )
    numeric_equal = Or(left_ret == right_ret, both_zero, And(left_nan, right_nan))
    return Not(numeric_equal)


def return_variable_name(smt_text: str | None) -> str | None:
    if not smt_text:
        return None
    match = re.search(r"\(declare-fun\s+(__return_value[^\s]*)\s+\(\)", smt_text)
    return match.group(1) if match else None


def check_input_coverage(old_path: Path, covering_new_paths: list[Path], timeout_ms: int) -> tuple[bool | None, float]:
    if not covering_new_paths:
        return False, 0.0
    start = time.perf_counter()
    ctx = Context()
    old_formula = parse_formula(old_path, ctx)
    cover_formulas = [parse_formula(path, ctx) for path in covering_new_paths]
    solver = Solver(ctx=ctx)
    solver.set("timeout", timeout_ms)
    solver.add(old_formula, Not(Or(*cover_formulas)))
    status = solver.check()
    elapsed = time.perf_counter() - start
    if status == unsat:
        return True, elapsed
    if status == sat:
        return False, elapsed
    return None, elapsed


def check_path_union_equal(source_path: Path, target_paths: list[Path], timeout_ms: int) -> tuple[bool | None, float, dict[str, bool | None]]:
    if not target_paths:
        return False, 0.0, {"source_subset_targets": False, "targets_subset_source": None}
    source_subset_targets, forward_time = check_input_coverage(source_path, target_paths, timeout_ms)
    targets_subset_source, reverse_time = check_union_coverage(target_paths, [source_path], timeout_ms)
    if source_subset_targets is None or targets_subset_source is None:
        equal = None
    else:
        equal = bool(source_subset_targets and targets_subset_source)
    return equal, forward_time + reverse_time, {
        "source_subset_targets": source_subset_targets,
        "targets_subset_source": targets_subset_source,
    }


def check_union_coverage(source_paths: list[Path], target_paths: list[Path], timeout_ms: int) -> tuple[bool | None, float]:
    if not source_paths:
        return True, 0.0
    if not target_paths:
        return False, 0.0
    start = time.perf_counter()
    ctx = Context()
    source_formula = Or(*[parse_formula(path, ctx) for path in source_paths])
    target_formula = Or(*[parse_formula(path, ctx) for path in target_paths])
    solver = Solver(ctx=ctx)
    solver.set("timeout", timeout_ms)
    solver.add(source_formula, Not(target_formula))
    status = solver.check()
    elapsed = time.perf_counter() - start
    if status == unsat:
        return True, elapsed
    if status == sat:
        return False, elapsed
    return None, elapsed


def invert_ranking(ranking: dict[str, list[str]], old_paths: list[Path], new_paths: list[Path]) -> dict[str, list[str]]:
    old_ids = [path.stem for path in old_paths]
    new_ids = [path.stem for path in new_paths]
    rank_index: dict[tuple[str, str], int] = {}
    for old_id in old_ids:
        for idx, new_id in enumerate(ranking.get(old_id, new_ids), 1):
            rank_index[(new_id, old_id)] = idx
    inverted: dict[str, list[str]] = {}
    for new_id in new_ids:
        inverted[new_id] = sorted(old_ids, key=lambda old_id: rank_index.get((new_id, old_id), 10**9))
    return inverted


def verify_directional_cover(
    source_paths: list[Path],
    target_paths: list[Path],
    ranking: dict[str, list[str]],
    timeout_ms: int,
    truth_pairs: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    source_by_id = path_index(source_paths)
    target_by_id = path_index(target_paths)
    default_targets = [path.stem for path in target_paths]
    matched_targets: set[str] = set()
    records: list[dict[str, Any]] = []
    smt_calls = 0
    t_smt = 0.0
    unknowns = 0
    semantic_modes: dict[str, int] = {}

    for source_id, source_path in source_by_id.items():
        candidates = ranking.get(source_id, default_targets)
        compatible: list[str] = []
        compatible_ranks: list[int] = []
        intersections: list[dict[str, Any]] = []
        exact_equal = False
        intersection_verified = False
        equality_details: dict[str, bool | None] = {
            "source_subset_targets": False,
            "targets_subset_source": None,
        }

        for rank, target_id in enumerate(candidates, 1):
            target_path = target_by_id.get(target_id)
            if target_path is None:
                continue
            equivalent, elapsed, calls, semantic_details = verify_semantic_path_relation(
                source_path, target_path, timeout_ms
            )
            smt_calls += calls
            t_smt += elapsed
            mode = str(semantic_details.get("semantic_mode", "unknown"))
            semantic_modes[mode] = semantic_modes.get(mode, 0) + 1

            if truth_pairs is not None:
                equivalent = target_id in truth_pairs.get(source_id, set())

            overlap = semantic_details.get("input_overlap")
            if overlap == "sat":
                intersections.append(
                    {
                        "target": target_id,
                        "rank": rank,
                        "semantic_equivalent_on_overlap": equivalent is True,
                        "details": semantic_details,
                    }
                )

            if equivalent is None:
                unknowns += 1
                continue
            if equivalent is not True:
                continue

            compatible.append(target_id)
            compatible_ranks.append(rank)
            matched_targets.add(target_id)

            if truth_pairs is None:
                equal, equality_time, equality_details = check_path_union_equal(
                    source_path,
                    [target_by_id[item] for item in compatible],
                    timeout_ms,
                )
                smt_calls += 1
                t_smt += equality_time
                if equal is None:
                    unknowns += 1
                if equal:
                    exact_equal = True
                    break
                if equality_details.get("source_subset_targets") is True:
                    intersection_verified = True
                    break
            else:
                exact_equal = True
                break

        matched = bool(compatible) and (exact_equal or intersection_verified)
        records.append(
            {
                "query": source_id,
                "match": compatible[0] if len(compatible) == 1 else compatible,
                "rank": compatible_ranks[0] if len(compatible_ranks) == 1 else compatible_ranks,
                "matched": matched,
                "input_space_equal_with_match": exact_equal,
                "intersection_verified": intersection_verified,
                "source_subset_targets": equality_details.get("source_subset_targets"),
                "targets_subset_source": equality_details.get("targets_subset_source"),
                "intersections": intersections,
            }
        )

    return {
        "success": all(record["matched"] for record in records) and unknowns == 0,
        "matched_targets": matched_targets,
        "records": records,
        "smt_calls": smt_calls,
        "t_smt": t_smt,
        "unknowns": unknowns,
        "semantic_modes": semantic_modes,
    }


def merge_counter(dst: dict[str, int], src: dict[str, int]) -> None:
    for key, value in src.items():
        dst[key] = dst.get(key, 0) + value


def compare_state_summary(left_state: Any, right_state: Any) -> bool:
    left_state = left_state or {}
    right_state = right_state or {}
    left_writes = canonical_writes(left_state.get("writes", []))
    right_writes = canonical_writes(right_state.get("writes", []))
    left_regions = left_state.get("regions", {})
    right_regions = right_state.get("regions", {})
    return left_writes == right_writes and left_regions == right_regions


def compare_optional_state_summary(left_state: Any, right_state: Any) -> bool:
    left_state = left_state or {}
    right_state = right_state or {}
    left_available = bool(left_state.get("available"))
    right_available = bool(right_state.get("available"))
    if not left_available and not right_available:
        return True
    if left_available != right_available:
        return False
    return compare_state_summary(left_state, right_state)


def canonical_writes(raw_writes: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_writes, list):
        return []
    return sorted(
        (
            {
                "addr": write.get("addr"),
                "data": write.get("data"),
                "size": write.get("size"),
            }
            for write in raw_writes
            if isinstance(write, dict)
        ),
        key=lambda item: json.dumps(item, sort_keys=True),
    )


def norm_path_id(value: Any) -> str:
    text = str(value)
    return Path(text).stem if "/" in text or "\\" in text else text.rsplit(".", 1)[0]


def candidate_id(item: Any, keys: tuple[str, ...] = ("path_id", "candidate", "target", "match", "path_b")) -> str | None:
    if isinstance(item, str):
        return norm_path_id(item)
    if isinstance(item, dict):
        for key in keys:
            if item.get(key) is not None:
                return norm_path_id(item[key])
    return None


def parse_ranking(data: Any) -> dict[str, list[str]]:
    if not isinstance(data, dict):
        return {}
    if "target" in data and "ranking" in data:
        return {
            norm_path_id(data["target"]): [
                cid for item in data.get("ranking", []) if (cid := candidate_id(item))
            ]
        }
    if "queries" in data:
        out: dict[str, list[str]] = {}
        for query_record in data.get("queries", []):
            query = query_record.get("query") or query_record.get("target") or query_record.get("source")
            ranking = query_record.get("ranking", query_record.get("candidates", []))
            if query:
                out[norm_path_id(query)] = [
                    cid for item in ranking if (cid := candidate_id(item))
                ]
        return out
    if "pairs" in data:
        out: dict[str, list[str]] = {}
        for item in data.get("pairs", []):
            left = candidate_id(item, keys=("path_a", "query", "source", "left_path"))
            right = candidate_id(item, keys=("path_b", "target", "match", "right_path", "candidate"))
            if left and right:
                out.setdefault(left, []).append(right)
        return out
    return {}


def build_naive_ranking(old_paths: list[Path], new_paths: list[Path]) -> dict[str, list[str]]:
    new_ids = [path.stem for path in new_paths]
    return {path.stem: list(new_ids) for path in old_paths}


def path_index(paths: list[Path]) -> dict[str, Path]:
    return {path.stem: path for path in paths}


def path_number(path_id: str) -> int:
    match = re.search(r"(\d+)$", path_id)
    return int(match.group(1)) if match else 0


def verify_ranked_queue(
    paths_dir: Path,
    ranking_path: Path | None,
    timeout_ms: int,
    naive: bool,
    truth_pairs: dict[str, set[str]] | None,
    program_ground_truth: bool | None,
) -> dict[str, Any]:
    old_paths = sorted(paths_dir.glob("symbolic_oldV_path_*.txt"), key=lambda p: path_number(p.stem))
    new_paths = sorted(paths_dir.glob("symbolic_newV_path_*.txt"), key=lambda p: path_number(p.stem))
    old_by_id = path_index(old_paths)
    new_by_id = path_index(new_paths)

    if naive:
        ranking = build_naive_ranking(old_paths, new_paths)
        method = "naive_all_pairs"
        t_align = 0.0
    else:
        if ranking_path is None:
            raise ValueError("--ranking is required unless --naive is used")
        ranking_data = json.loads(ranking_path.read_text(encoding="utf-8"))
        ranking = parse_ranking(ranking_data)
        timing = ranking_data.get("timing", {}) if isinstance(ranking_data, dict) else {}
        t_align = float(timing.get("t_align", ranking_data.get("t_align", 0.0)) or 0.0)
        method = str(ranking_data.get("method", "ranked"))

    smt_calls = 0
    t_smt = 0.0
    unknowns = 0
    semantic_modes: dict[str, int] = {}

    old_subset_new, elapsed = check_union_coverage(old_paths, new_paths, timeout_ms)
    smt_calls += 1
    t_smt += elapsed
    new_subset_old, elapsed = check_union_coverage(new_paths, old_paths, timeout_ms)
    smt_calls += 1
    t_smt += elapsed
    if old_subset_new is None or new_subset_old is None:
        unknowns += 1
    input_space_equal = old_subset_new is True and new_subset_old is True

    reverse_ranking = invert_ranking(ranking, old_paths, new_paths)
    reverse_truth_pairs = None
    if truth_pairs is not None:
        reverse_truth_pairs = {}
        for old_id, new_ids in truth_pairs.items():
            for new_id in new_ids:
                reverse_truth_pairs.setdefault(new_id, set()).add(old_id)

    forward = verify_directional_cover(old_paths, new_paths, ranking, timeout_ms, truth_pairs)
    reverse = verify_directional_cover(new_paths, old_paths, reverse_ranking, timeout_ms, reverse_truth_pairs)

    smt_calls += int(forward["smt_calls"]) + int(reverse["smt_calls"])
    t_smt += float(forward["t_smt"]) + float(reverse["t_smt"])
    unknowns += int(forward["unknowns"]) + int(reverse["unknowns"])
    merge_counter(semantic_modes, forward["semantic_modes"])
    merge_counter(semantic_modes, reverse["semantic_modes"])

    alignment_success = bool(input_space_equal and forward["success"] and reverse["success"] and unknowns == 0)
    prediction = alignment_success

    return {
        "method": method,
        "prediction": prediction,
        "alignment_success": alignment_success,
        "input_space_equal": input_space_equal,
        "old_input_subset_new": old_subset_new,
        "new_input_subset_old": new_subset_old,
        "old_path_count": len(old_paths),
        "new_path_count": len(new_paths),
        "candidate_pairs": len(old_paths) * len(new_paths),
        "aligned_pairs": len(forward["matched_targets"]),
        "smt_calls": smt_calls,
        "t_align": t_align,
        "t_smt": t_smt,
        "t_total": t_align + t_smt,
        "unknowns": unknowns,
        "semantic_definition": [
            "input_space_equivalence",
            "function_return_value_equivalence",
            "heap_and_global_state_equivalence",
        ],
        "semantic_modes": semantic_modes,
        "matches": forward["records"],
        "reverse_matches": reverse["records"],
    }


def parse_truth_pairs(raw: str | None) -> dict[str, set[str]] | None:
    if not raw:
        return None
    data = json.loads(raw)
    out: dict[str, set[str]] = {}
    if isinstance(data, dict):
        for query, targets in data.items():
            target_values = targets if isinstance(targets, list) else [targets]
            out[norm_path_id(query)] = {norm_path_id(target) for target in target_values}
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                query = item.get("query") or item.get("source") or item.get("path_a") or item.get("left_path")
                target = item.get("target") or item.get("match") or item.get("path_b") or item.get("right_path")
            elif isinstance(item, list) and len(item) >= 2:
                query, target = item[0], item[1]
            else:
                continue
            if query and target:
                out.setdefault(norm_path_id(query), set()).add(norm_path_id(target))
    return out


def parse_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in {"1", "true", "yes", "y", "eq", "equivalent"}:
        return True
    if lowered in {"0", "false", "no", "n", "neq", "not_equivalent"}:
        return False
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths-dir", type=Path, required=True)
    parser.add_argument("--ranking", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--naive", action="store_true")
    parser.add_argument("--truth-pairs-json")
    parser.add_argument("--program-ground-truth")
    args = parser.parse_args()

    result = verify_ranked_queue(
        args.paths_dir,
        args.ranking,
        args.timeout_ms,
        args.naive,
        parse_truth_pairs(args.truth_pairs_json),
        parse_bool(args.program_ground_truth),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
