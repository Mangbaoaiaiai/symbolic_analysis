#!/usr/bin/env python3
"""Verify program equivalence by following a ranked path-pair queue."""

from __future__ import annotations

import ast
import argparse
import json
import re
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

from z3 import (
    And,
    BitVec,
    BitVecVal,
    BoolVal,
    Context,
    FPNumRef,
    Not,
    Or,
    Solver,
    fpToIEEEBV,
    parse_smt2_string,
    sat,
    simplify,
    unsat,
)
from z3.z3util import get_vars

# Paper Section 4.1 uses 60 seconds for every path-pair SMT comparison.
RETURN_EQ_TIMEOUT_MS = 60_000
# A bounded, SMT-guided pre-scan only looks for a replayable NEQ witness.
# Failure to find one is non-authoritative and falls back to full coverage
# verification.
NEQ_PRESCAN_BUDGET_MS = 15_000
NEQ_PRESCAN_PAIR_TIMEOUT_MS = 2_000


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
        "program_output_equivalent": None,
        "memory_state_equivalent": None,
        "global_state_equivalent": None,
        "semantic_mode": "input_return_output_global_state",
    }

    input_eq, input_time = verify_path_pair(left, right, timeout_ms)
    details["input_space_equivalent"] = input_eq
    total_time = input_time
    if input_eq is not True:
        return input_eq, total_time, details

    if left_summary is None or right_summary is None:
        details["semantic_mode"] = "missing_semantic_summary"
        return None, total_time, details

    return_eq, return_time = verify_return_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    total_time += return_time
    details["return_value_equivalent"] = return_eq
    if return_eq is not True:
        return return_eq, total_time, details

    output_eq, output_time, _output_calls = verify_output_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    total_time += output_time
    details["program_output_equivalent"] = output_eq
    if output_eq is not True:
        return output_eq, total_time, details

    details["memory_state_equivalent"] = "auxiliary_not_checked"
    global_eq, global_time, _global_calls = verify_global_state_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    total_time += global_time
    details["global_state_equivalent"] = global_eq
    if global_eq is not True:
        return global_eq, total_time, details

    return True, total_time, details


def verify_semantic_path_relation(
    left: Path,
    right: Path,
    timeout_ms: int,
    *,
    replay_mismatches: bool = True,
    counterexample_only: bool = False,
) -> tuple[bool | None, float, int, dict[str, Any]]:
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
    overlap_model = overlap_solver.model() if overlap_status == sat else None

    details: dict[str, Any] = {
        "input_overlap": str(overlap_status),
        "return_value_equivalent": None,
        "program_output_equivalent": None,
        "memory_state_equivalent": None,
        "global_state_equivalent": None,
        "semantic_mode": "input_return_output_global_state_overlap",
    }
    if overlap_status == unsat:
        return False, elapsed, smt_calls, details
    if overlap_status != sat:
        return None, elapsed, smt_calls, details

    left_summary = extract_semantic_summary(left)
    right_summary = extract_semantic_summary(right)
    if left_summary is None or right_summary is None:
        details["semantic_mode"] = "missing_semantic_summary"
        return None, elapsed, smt_calls, details

    left_return = left_summary.get("return_value") or {}
    right_return = right_summary.get("return_value") or {}
    return_eq: bool | None = None
    return_time = 0.0
    return_calls = 0
    if (
        overlap_model is not None
        and not return_expressions_identical(left_return, right_return)
    ):
        seed_inputs = concrete_inputs_from_variables(
            overlap_model,
            collect_variables(left_constraint, right_constraint),
        )
        if seed_inputs:
            seeded = find_return_counterexample(
                left_summary,
                right_summary,
                min(timeout_ms, 5_000),
                left,
                right,
                seed_inputs=seed_inputs,
            )
            return_calls += 1
            if seeded and seeded.get("inputs"):
                return_eq = False
                details["counterexample"] = seeded
                details["counterexample_source"] = "concrete_overlap_model"
    if return_eq is None and counterexample_only:
        return None, elapsed + return_time, smt_calls + return_calls, details
    if return_eq is None:
        return_eq, return_time, return_calls = verify_return_equivalence_on_overlap(
            left_summary, right_summary, timeout_ms, left, right
        )
    elapsed += return_time
    smt_calls += return_calls
    details["return_value_equivalent"] = return_eq
    if return_eq is not True:
        if return_eq is False and replay_mismatches:
            counterexample = details.get("counterexample")
            if not counterexample:
                counterexample = find_return_counterexample(
                    left_summary, right_summary, timeout_ms, left, right
                )
            details["counterexample"] = counterexample
            details["replay"] = replay_counterexample(left, right, counterexample)
        return return_eq, elapsed, smt_calls, details

    output_eq, output_time, output_calls = verify_output_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    elapsed += output_time
    smt_calls += output_calls
    details["program_output_equivalent"] = output_eq
    if output_eq is not True:
        if output_eq is False and replay_mismatches:
            counterexample = find_output_counterexample(
                left_summary,
                right_summary,
                timeout_ms,
                left,
                right,
            )
            details["output_counterexample"] = counterexample
            details["replay"] = replay_counterexample(left, right, counterexample)
        return output_eq, elapsed, smt_calls, details

    details["memory_state_equivalent"] = "auxiliary_not_checked"
    global_eq, global_time, global_calls = verify_global_state_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    elapsed += global_time
    smt_calls += global_calls
    details["global_state_equivalent"] = global_eq
    if global_eq is not True:
        return global_eq, elapsed, smt_calls, details

    return True, elapsed, smt_calls, details


def verify_return_equivalence(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
) -> tuple[bool | None, float]:
    left_return = left_summary.get("return_value") or {}
    right_return = right_summary.get("return_value") or {}
    if not left_return.get("available") and not right_return.get("available"):
        return None, 0.0
    if not left_return.get("available") or not right_return.get("available"):
        return False, 0.0
    if int(left_return.get("bits", 0) or 0) != int(right_return.get("bits", 0) or 0):
        return False, 0.0
    left_smt = left_return.get("smt")
    right_smt = right_return.get("smt")
    if not left_smt or not right_smt:
        return (left_return.get("repr") == right_return.get("repr")), 0.0
    equivalent, elapsed, _calls = verify_return_smt_equivalence(
        left_return, right_return, timeout_ms, left_path, right_path
    )
    return equivalent, elapsed


def flatten_output_segments(
    summary: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Return the ordered byte-producing observations of a path.

    Event boundaries and call names are intentionally discarded.  Several
    stdio calls that produce the same ordered text therefore remain equivalent,
    while missing metadata is represented conservatively as unknown.
    """
    output = summary.get("program_output") or {}
    if (
        not output.get("available")
        or output.get("unresolved")
        or not isinstance(output.get("events"), list)
    ):
        return None
    segments: list[dict[str, Any]] = []
    for event in output["events"]:
        if not isinstance(event, dict) or not isinstance(event.get("segments"), list):
            return None
        sink = str(event.get("sink") or "stdio")
        for segment in event["segments"]:
            if not isinstance(segment, dict):
                return None
            normalized = {**segment, "sink": sink}
            if (
                normalized.get("kind") == "text"
                and segments
                and segments[-1].get("kind") == "text"
                and segments[-1].get("sink") == sink
            ):
                segments[-1]["value"] = str(segments[-1].get("value") or "") + str(
                    normalized.get("value") or ""
                )
            else:
                segments.append(normalized)
    return segments


def verify_output_equivalence(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
) -> tuple[bool | None, float, int]:
    left_segments = flatten_output_segments(left_summary)
    right_segments = flatten_output_segments(right_summary)
    if left_segments is None or right_segments is None:
        return None, 0.0, 0
    if len(left_segments) != len(right_segments):
        return False, 0.0, 0

    total_time = 0.0
    calls = 0
    for left, right in zip(left_segments, right_segments):
        if str(left.get("sink")) != str(right.get("sink")):
            return False, total_time, calls
        left_kind = str(left.get("kind") or "")
        right_kind = str(right.get("kind") or "")
        if left_kind != right_kind:
            return False, total_time, calls
        if left_kind == "text":
            if left.get("value") != right.get("value"):
                return False, total_time, calls
            continue
        if left_kind != "formatted_value":
            return None, total_time, calls
        if (
            str(left.get("specifier") or "") != str(right.get("specifier") or "")
            or int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0)
            or int(left.get("bits", 0) or 0) <= 0
        ):
            return False, total_time, calls
        if (
            left.get("repr")
            and right.get("repr")
            and left.get("repr") == right.get("repr")
        ):
            continue
        equivalent, elapsed = verify_observable_expr_equivalence(
            left,
            right,
            timeout_ms,
            left_path,
            right_path,
        )
        calls += int(bool(left.get("smt") and right.get("smt")))
        total_time += elapsed
        if equivalent is not True:
            return equivalent, total_time, calls
    return True, total_time, calls


def output_segments_identical(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
) -> bool:
    left_segments = flatten_output_segments(left_summary)
    right_segments = flatten_output_segments(right_summary)
    if left_segments is None or right_segments is None:
        return False
    if len(left_segments) != len(right_segments):
        return False
    for left, right in zip(left_segments, right_segments):
        if str(left.get("sink")) != str(right.get("sink")):
            return False
        if str(left.get("kind") or "") != str(right.get("kind") or ""):
            return False
        if left.get("kind") == "text":
            if left.get("value") != right.get("value"):
                return False
            continue
        if (
            left.get("kind") != "formatted_value"
            or left.get("specifier") != right.get("specifier")
            or int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0)
            or left.get("repr") != right.get("repr")
        ):
            return False
    return True


def find_output_counterexample(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
) -> dict[str, Any] | None:
    left_segments = flatten_output_segments(left_summary)
    right_segments = flatten_output_segments(right_summary)
    if left_segments is None or right_segments is None:
        return None

    ctx = Context()
    formulas = []
    solver = Solver(ctx=ctx)
    solver.set("timeout", min(timeout_ms, 10_000))
    try:
        if left_path is not None and right_path is not None:
            path_formulas = [parse_formula(left_path, ctx), parse_formula(right_path, ctx)]
            formulas.extend(path_formulas)
            solver.add(*path_formulas)
        mismatch = None
        for left, right in zip(left_segments, right_segments):
            if str(left.get("sink")) != str(right.get("sink")):
                break
            if str(left.get("kind") or "") != str(right.get("kind") or ""):
                break
            if left.get("kind") == "text":
                if left.get("value") != right.get("value"):
                    break
                continue
            if (
                left.get("kind") != "formatted_value"
                or left.get("specifier") != right.get("specifier")
                or int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0)
            ):
                break
            if left.get("repr") == right.get("repr"):
                continue
            left_smt = left.get("smt")
            right_smt = right.get("smt")
            left_var = left.get("variable")
            right_var = right.get("variable")
            if not all(
                isinstance(value, str) and value
                for value in (left_smt, right_smt, left_var, right_var)
            ):
                continue
            right_var_renamed = f"{right_var}__right"
            right_smt = re.sub(
                rf"\b{re.escape(right_var)}\b",
                right_var_renamed,
                right_smt,
            )
            left_formula = formula_from_smt_text(left_smt, ctx)
            right_formula = formula_from_smt_text(right_smt, ctx)
            formulas.extend((left_formula, right_formula))
            bits = int(left["bits"])
            mismatch = (
                BitVec(left_var, bits, ctx=ctx)
                != BitVec(right_var_renamed, bits, ctx=ctx)
            )
            break
        if mismatch is not None:
            solver.add(mismatch)
        if solver.check() != sat:
            return None
        model = solver.model()
        variables = collect_variables(*formulas)
        inputs = concrete_inputs_from_variables(model, variables)
        if not inputs and left_path is not None:
            inputs = sample_inputs_from_path(left_path)
        inputs.sort(key=lambda item: input_symbol_order(item["name"]))
        return {"inputs": inputs}
    except Exception as exc:
        return {"inputs": [], "error": str(exc)}


def return_expressions_identical(
    left_return: dict[str, Any],
    right_return: dict[str, Any],
) -> bool:
    return bool(
        left_return.get("available")
        and right_return.get("available")
        and left_return.get("bits") == right_return.get("bits")
        and left_return.get("repr")
        and right_return.get("repr")
        and left_return.get("repr") == right_return.get("repr")
    )


def verify_return_equivalence_on_overlap(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
) -> tuple[bool | None, float, int]:
    left_return = left_summary.get("return_value") or {}
    right_return = right_summary.get("return_value") or {}
    if not left_return.get("available") and not right_return.get("available"):
        return None, 0.0, 0
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
    return verify_return_smt_equivalence(
        left_return, right_return, timeout_ms, left_path, right_path
    )


def verify_return_smt_equivalence(
    left_return: dict[str, Any],
    right_return: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
) -> tuple[bool | None, float, int]:
    if return_expressions_identical(left_return, right_return):
        # This is a reflexive proof of equality. In particular, SMT-LIB
        # encodings from the same expression differ only in generated ``let``
        # variable names, which otherwise make Z3 spend the full timeout on
        # nonlinear floating-point reasoning even when both sides are
        # syntactically identical.
        return True, 0.0, 0

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
        # Each summary declares only the input symbols occurring in its return
        # expression.  Add assumptions to the summary that owns the declaration
        # so parsing remains valid when one side returns a constant/subset.
        left_smt = append_smt_assertions(left_smt, fp_input_non_nan_assumptions(left_smt))
        right_smt = append_smt_assertions(right_smt, fp_input_non_nan_assumptions(right_smt))

    start = time.perf_counter()
    ctx = Context()
    left_formula = formula_from_smt_text(left_smt, ctx)
    right_formula = formula_from_smt_text(right_smt, ctx)
    solver = Solver(ctx=ctx)
    solver.set("timeout", min(timeout_ms, RETURN_EQ_TIMEOUT_MS))
    if left_path is not None and right_path is not None:
        solver.add(parse_formula(left_path, ctx), parse_formula(right_path, ctx))
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


def verify_global_state_equivalence(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
) -> tuple[bool | None, float, int]:
    left_state = left_summary.get("global_state") or {}
    right_state = right_summary.get("global_state") or {}
    if not left_state.get("available") or not right_state.get("available"):
        return None, 0.0, 0
    left_regions = left_state.get("regions")
    right_regions = right_state.get("regions")
    if not isinstance(left_regions, dict) or not isinstance(right_regions, dict):
        return None, 0.0, 0
    if not left_regions and not right_regions:
        return True, 0.0, 0

    pairs = map_global_regions(left_regions, right_regions)
    if pairs is None:
        return None, 0.0, 0
    total_time = 0.0
    calls = 0
    for left_cell, right_cell in pairs:
        equivalent, elapsed = verify_observable_expr_equivalence(
            left_cell, right_cell, timeout_ms, left_path, right_path
        )
        total_time += elapsed
        calls += int(bool(left_cell.get("smt") and right_cell.get("smt")))
        if equivalent is not True:
            return equivalent, total_time, calls
    return True, total_time, calls


def map_global_regions(
    left_regions: dict[str, Any], right_regions: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]] | None:
    """Map normalized global cells, then fall back to structural position.

    Exact section-relative keys implement fixed-address/consistent-shift
    normalization.  Structural fallback is accepted only for a unique ordered
    mapping with identical cell widths.
    """
    if set(left_regions) == set(right_regions):
        return [(left_regions[key], right_regions[key]) for key in sorted(left_regions)]
    if len(left_regions) != len(right_regions):
        return None
    left_items = sorted(left_regions.items())
    right_items = sorted(right_regions.items())
    pairs = []
    for (_left_key, left), (_right_key, right) in zip(left_items, right_items):
        if not isinstance(left, dict) or not isinstance(right, dict):
            return None
        if int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0):
            return None
        pairs.append((left, right))
    return pairs


def verify_observable_expr_equivalence(
    left: dict[str, Any],
    right: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
) -> tuple[bool | None, float]:
    if not left.get("available") or not right.get("available"):
        return None, 0.0
    bits = int(left.get("bits", 0) or 0)
    if bits <= 0 or bits != int(right.get("bits", 0) or 0):
        return False, 0.0
    left_smt = left.get("smt")
    right_smt = right.get("smt")
    left_var = left.get("variable")
    right_var = right.get("variable")
    if not all(isinstance(value, str) and value for value in (left_smt, right_smt, left_var, right_var)):
        return None, 0.0
    right_var_renamed = f"{right_var}__right"
    right_smt = re.sub(rf"\b{re.escape(right_var)}\b", right_var_renamed, right_smt)
    start = time.perf_counter()
    ctx = Context()
    try:
        left_formula = formula_from_smt_text(left_smt, ctx)
        right_formula = formula_from_smt_text(right_smt, ctx)
        solver = Solver(ctx=ctx)
        solver.set("timeout", timeout_ms)
        path_formulas = []
        if left_path is not None and right_path is not None:
            path_formulas = [parse_formula(left_path, ctx), parse_formula(right_path, ctx)]
            solver.add(*path_formulas)
        solver.add(
            left_formula,
            right_formula,
            BitVec(left_var, bits, ctx=ctx) != BitVec(right_var_renamed, bits, ctx=ctx),
        )
        status = solver.check()
    except Exception:
        return None, time.perf_counter() - start
    elapsed = time.perf_counter() - start
    if status == unsat:
        return True, elapsed
    if status == sat:
        return False, elapsed
    return None, elapsed


def find_return_counterexample(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
    seed_inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    left = left_summary.get("return_value") or {}
    right = right_summary.get("return_value") or {}
    bits = int(left.get("bits", 0) or 0)
    if bits <= 0 or bits != int(right.get("bits", 0) or 0):
        return None
    left_smt = left.get("smt")
    right_smt = right.get("smt")
    left_var = return_variable_name(left_smt)
    right_var = return_variable_name(right_smt)
    if not left_smt or not right_smt or not left_var or not right_var:
        return None
    right_var_renamed = f"{right_var}__right"
    right_smt = re.sub(rf"\b{re.escape(right_var)}\b", right_var_renamed, right_smt)
    use_float_numeric_equivalence = should_use_float_numeric_return_equivalence(left, right)
    if use_float_numeric_equivalence:
        left_smt = append_smt_assertions(left_smt, fp_input_non_nan_assumptions(left_smt))
        right_smt = append_smt_assertions(right_smt, fp_input_non_nan_assumptions(right_smt))
    ctx = Context()
    try:
        left_formula = formula_from_smt_text(left_smt, ctx)
        right_formula = formula_from_smt_text(right_smt, ctx)
        solver = Solver(ctx=ctx)
        solver.set("timeout", timeout_ms)
        path_formulas = []
        if left_path is not None and right_path is not None:
            path_formulas = [parse_formula(left_path, ctx), parse_formula(right_path, ctx)]
            solver.add(*path_formulas)
        left_ret = BitVec(left_var, bits, ctx=ctx)
        right_ret = BitVec(right_var_renamed, bits, ctx=ctx)
        solver.add(
            left_formula,
            right_formula,
            (
                float_numeric_not_equal(left_ret, right_ret, bits, ctx)
                if use_float_numeric_equivalence
                else left_ret != right_ret
            ),
        )
        seed_inputs = seed_inputs or []
        for item in seed_inputs:
            name = str(item.get("name") or "")
            kind = str(item.get("kind") or "")
            bits_for_input = int(item.get("bits", 0) or 0)
            if not name or bits_for_input <= 0:
                continue
            if kind == "bitvec":
                fixed = parse_smt2_string(
                    f"(declare-fun {name} () (_ BitVec {bits_for_input}))\n"
                    f"(assert (= {name} "
                    f"(_ bv{int(item.get('unsigned', 0))} {bits_for_input})))",
                    ctx=ctx,
                )
                solver.add(*fixed)
            elif kind == "float":
                exponent_bits = 8 if bits_for_input == 32 else 11
                significand_bits = 24 if bits_for_input == 32 else 53
                fixed = parse_smt2_string(
                    f"(declare-fun {name} () "
                    f"(_ FloatingPoint {exponent_bits} {significand_bits}))\n"
                    f"(assert (= (fp.to_ieee_bv {name}) "
                    f"(_ bv{int(item.get('ieee_bits', 0))} {bits_for_input})))",
                    ctx=ctx,
                )
                solver.add(*fixed)
        if solver.check() != sat:
            return None
        model = solver.model()
        variables = collect_variables(
            left_formula,
            right_formula,
            *path_formulas,
        )
        inputs = concrete_inputs_from_variables(model, variables)
        if not inputs and left_path is not None:
            # Z3 legitimately omits unconstrained inputs from a model.  A
            # constant return mismatch still needs concrete arguments for
            # native replay, so use the path artifact's satisfying sample.
            inputs = sample_inputs_from_path(left_path)
        inputs.sort(key=lambda item: input_symbol_order(item["name"]))
        return {"inputs": inputs}
    except Exception as exc:
        return {"inputs": [], "error": str(exc)}


def sample_inputs_from_path(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r";\s*Symbolic variable values:\s*(\{.*\})", content)
    if not match:
        return []
    try:
        values = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError):
        return []
    if not isinstance(values, dict):
        return []
    out = []
    for name, value in values.items():
        if not isinstance(name, str) or not re.match(r"^(?:arg_|scanf_)\d+$", name):
            continue
        try:
            integer = int(value or 0)
        except (TypeError, ValueError):
            integer = 0
        out.append(
            {
                "name": name,
                "kind": "bitvec",
                "bits": 32,
                "value": integer,
                "unsigned": integer & 0xFFFFFFFF,
            }
        )
    return out


def is_input_symbol(name: str) -> bool:
    return bool(re.match(r"^(?:arg_|FP_arg_|scanf_)", name))


def input_symbol_order(name: str) -> tuple[int, str]:
    match = re.search(r"(?:arg_|scanf_)(\d+)", name)
    return (int(match.group(1)) if match else 10**9, name)


def z3_value_to_concrete(model, value) -> dict[str, Any] | None:
    sort_text = str(value.sort())
    if sort_text.startswith("BitVec("):
        bits = int(value.size())
        unsigned = int(value.as_long())
        signed = unsigned - (1 << bits) if bits and unsigned >= (1 << (bits - 1)) else unsigned
        return {"kind": "bitvec", "bits": bits, "value": signed, "unsigned": unsigned}
    if "FPSort" in sort_text or "FloatingPoint" in sort_text:
        if not isinstance(value, FPNumRef):
            return None
        bits = int(value.ebits()) + int(value.sbits())
        if bits not in {32, 64}:
            return None
        raw = (
            (int(bool(value.sign())) << (bits - 1))
            | (int(value.exponent_as_long()) << (bits - value.ebits() - 1))
            | int(value.significand_as_long())
        )
        number = struct.unpack(
            ">f" if bits == 32 else ">d",
            raw.to_bytes(bits // 8, "big"),
        )[0]
        return {"kind": "float", "bits": bits, "value": number, "ieee_bits": raw}
    return None


def collect_variables(*formulas: Any) -> list[Any]:
    variables = []
    seen: set[tuple[str, str]] = set()
    for formula in formulas:
        for variable in get_vars(formula):
            key = (variable.decl().name(), str(variable.sort()))
            if key in seen:
                continue
            seen.add(key)
            variables.append(variable)
    return variables


def concrete_inputs_from_variables(
    model,
    variables: list[Any],
) -> list[dict[str, Any]]:
    inputs = []
    seen: set[str] = set()
    for variable in variables:
        name = variable.decl().name()
        if not is_input_symbol(name):
            continue
        if name in seen:
            continue
        seen.add(name)
        value = model.eval(variable, model_completion=True)
        concrete = z3_value_to_concrete(model, value)
        if concrete is not None:
            inputs.append({"name": name, **concrete})
    inputs.sort(key=lambda item: input_symbol_order(item["name"]))
    return inputs


def replay_counterexample(
    left_path: Path, right_path: Path, counterexample: dict[str, Any] | None
) -> dict[str, Any]:
    if not counterexample or not counterexample.get("inputs"):
        return {"confirmed": False, "reason": "counterexample_inputs_unavailable"}
    left_binary = binary_for_path(left_path)
    right_binary = binary_for_path(right_path)
    if left_binary is None or right_binary is None:
        return {"confirmed": False, "reason": "binary_unavailable"}
    tokens = [format_replay_value(item) for item in counterexample["inputs"]]
    stdin = " ".join(tokens) + "\n"
    left_run = run_binary(left_binary, stdin)
    right_run = run_binary(right_binary, stdin)
    if not left_run.get("completed") or not right_run.get("completed"):
        return {
            "confirmed": False,
            "reason": "replay_failed",
            "stdin": stdin,
            "left": left_run,
            "right": right_run,
        }
    confirmed = (
        left_run.get("returncode") != right_run.get("returncode")
        or left_run.get("stdout") != right_run.get("stdout")
        or left_run.get("stderr") != right_run.get("stderr")
    )
    return {
        "confirmed": confirmed,
        "reason": "observable_output_diff" if confirmed else "no_observable_output_diff",
        "stdin": stdin,
        "left": left_run,
        "right": right_run,
    }


def binary_for_path(path: Path) -> Path | None:
    stem = "symbolic_oldV" if path.stem.startswith("symbolic_oldV") else "symbolic_newV"
    bin_dir = path.parent.parent / "bin"
    for candidate in (bin_dir / stem, bin_dir / f"{stem}.exe"):
        if candidate.is_file():
            return candidate
    return None


def format_replay_value(item: dict[str, Any]) -> str:
    value = item.get("value")
    if isinstance(value, float):
        if value != value:
            return "nan"
        if value == float("inf"):
            return "inf"
        if value == float("-inf"):
            return "-inf"
        return value.hex()
    return str(value)


def run_binary(binary: Path, stdin: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(binary)],
            input=stdin,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        return {
            "completed": True,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except Exception as exc:
        return {"completed": False, "error": str(exc)}


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
    old_key = str(simplify(old_formula))
    if any(old_key == str(simplify(formula)) for formula in cover_formulas):
        return True, 0.0
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
    source_formulas = [parse_formula(path, ctx) for path in source_paths]
    target_formulas = [parse_formula(path, ctx) for path in target_paths]
    source_keys = {str(simplify(formula)) for formula in source_formulas}
    target_keys = {str(simplify(formula)) for formula in target_formulas}
    if source_keys == target_keys:
        return True, 0.0
    source_formula = Or(*source_formulas)
    target_formula = Or(*target_formulas)
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


def filter_definitely_unsat_paths(
    paths: list[Path], timeout_ms: int
) -> tuple[list[Path], int, int, float]:
    """Drop paths with an UNSAT input constraint before coverage matching.

    angr may preserve infeasible floating-point states when LAZY_SOLVES is
    enabled.  Such states denote an empty input region and must not force a
    coverage mismatch in the bidirectional matcher.  Unknown feasibility is
    kept conservative and left for the normal verifier to handle.
    """
    feasible: list[Path] = []
    unsat_count = 0
    unknown_count = 0
    elapsed_total = 0.0
    for path in paths:
        start = time.perf_counter()
        ctx = Context()
        solver = Solver(ctx=ctx)
        solver.set("timeout", timeout_ms)
        solver.add(parse_formula(path, ctx))
        status = solver.check()
        elapsed_total += time.perf_counter() - start
        if status == unsat:
            unsat_count += 1
        else:
            feasible.append(path)
            if status != sat:
                unknown_count += 1
    return feasible, unsat_count, unknown_count, elapsed_total


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
    allow_one_to_many: bool = True,
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
    confirmed_mismatches: list[dict[str, Any]] = []

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
        candidate_unknowns = 0

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
            replay = semantic_details.get("replay") or {}
            if replay.get("confirmed"):
                confirmed_mismatches.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "rank": rank,
                        "counterexample": (
                            semantic_details.get("counterexample")
                            or semantic_details.get("output_counterexample")
                        ),
                        "replay": replay,
                    }
                )
                # A single concretely replayed observable difference is
                # sufficient to authorize NEQ. Further coverage candidates
                # cannot overturn that witness and need not be explored.
                break

            if equivalent is None:
                candidate_unknowns += 1
                continue
            if equivalent is not True:
                continue

            compatible.append(target_id)
            compatible_ranks.append(rank)
            matched_targets.add(target_id)

            if truth_pairs is None:
                cover_ids = compatible if allow_one_to_many else [target_id]
                equal, equality_time, equality_details = check_path_union_equal(
                    source_path,
                    [target_by_id[item] for item in cover_ids],
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
                    if not allow_one_to_many:
                        compatible = [target_id]
                        compatible_ranks = [rank]
                    intersection_verified = True
                    break
                if not allow_one_to_many:
                    compatible.pop()
                    compatible_ranks.pop()
            else:
                exact_equal = True
                break

        matched = bool(compatible) and (exact_equal or intersection_verified)
        if not matched:
            unknowns += candidate_unknowns
        if not matched:
            match_type = "unmatched"
        elif len(compatible) == 1 and exact_equal:
            match_type = "one_to_one_exact"
        elif len(compatible) == 1:
            match_type = "one_to_one_source_subset_target"
        elif exact_equal:
            match_type = "one_to_many_exact_cover"
        else:
            match_type = "one_to_many_source_subset_target_union"
        records.append(
            {
                "query": source_id,
                "match": compatible[0] if len(compatible) == 1 else compatible,
                "rank": compatible_ranks[0] if len(compatible_ranks) == 1 else compatible_ranks,
                "matched": matched,
                "match_type": match_type,
                "input_space_equal_with_match": exact_equal,
                "intersection_verified": intersection_verified,
                "source_subset_targets": equality_details.get("source_subset_targets"),
                "targets_subset_source": equality_details.get("targets_subset_source"),
                "intersections": intersections,
            }
        )
        if confirmed_mismatches:
            break

    return {
        "success": all(record["matched"] for record in records) and unknowns == 0,
        "matched_targets": matched_targets,
        "records": records,
        "smt_calls": smt_calls,
        "t_smt": t_smt,
        "unknowns": unknowns,
        "semantic_modes": semantic_modes,
        "confirmed_mismatches": confirmed_mismatches,
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


def exact_path_bijection_proves_equivalence(
    old_paths: list[Path],
    new_paths: list[Path],
) -> list[dict[str, Any]] | None:
    """Return exact match records when the two path sets are identical by rank."""
    if not old_paths or len(old_paths) != len(new_paths):
        return None
    records = []
    for old_path, new_path in zip(old_paths, new_paths):
        if canonical_smt_text(old_path.read_text(encoding="utf-8", errors="replace")) != canonical_smt_text(
            new_path.read_text(encoding="utf-8", errors="replace")
        ):
            return None
        old_summary = extract_semantic_summary(old_path)
        new_summary = extract_semantic_summary(new_path)
        if old_summary is None or new_summary is None:
            return None
        if not return_expressions_identical(
            old_summary.get("return_value") or {},
            new_summary.get("return_value") or {},
        ):
            return None
        if not output_segments_identical(old_summary, new_summary):
            return None
        old_global = old_summary.get("global_state") or {}
        new_global = new_summary.get("global_state") or {}
        if (
            not old_global.get("available")
            or not new_global.get("available")
            or old_global.get("unresolved")
            or new_global.get("unresolved")
            or old_global.get("regions") != new_global.get("regions")
        ):
            return None
        records.append(
            {
                "query": old_path.stem,
                "match": new_path.stem,
                "rank": 1,
                "matched": True,
                "match_type": "one_to_one_exact",
                "input_space_equal_with_match": True,
                "intersection_verified": False,
                "source_subset_targets": True,
                "targets_subset_source": True,
                "intersections": [],
                "proof": "simplified_path_return_output_state_identity",
            }
        )
    return records


def canonical_smt_text(text: str) -> str:
    """Canonicalize fresh `let` names by first occurrence for alpha equality."""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("(check-sat"):
            continue
        lines.append(line)
    joined = "\n".join(lines)
    names: dict[str, str] = {}

    def replacement(match: re.Match[str]) -> str:
        original = match.group(0)
        canonical = names.setdefault(original, f"?v{len(names)}")
        return canonical

    return re.sub(r"\?x\d+", replacement, joined)


def prescan_replayable_counterexample(
    source_paths: list[Path],
    target_paths: list[Path],
    ranking: dict[str, list[str]],
    timeout_ms: int,
    *,
    budget_ms: int = NEQ_PRESCAN_BUDGET_MS,
) -> dict[str, Any]:
    source_by_id = path_index(source_paths)
    target_by_id = path_index(target_paths)
    default_targets = [path.stem for path in target_paths]
    started = time.perf_counter()
    deadline = started + budget_ms / 1000.0
    smt_calls = 0
    t_smt = 0.0
    semantic_modes: dict[str, int] = {}
    records: list[dict[str, Any]] = []
    for source_id, source_path in source_by_id.items():
        candidates = ranking.get(source_id, default_targets)
        for rank, target_id in enumerate(candidates, 1):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return {
                    "mismatch": None,
                    "records": records,
                    "smt_calls": smt_calls,
                    "t_smt": t_smt,
                    "semantic_modes": semantic_modes,
                    "exhausted_budget": True,
                }
            target_path = target_by_id.get(target_id)
            if target_path is None:
                continue
            per_pair_ms = max(
                1,
                min(
                    timeout_ms,
                    NEQ_PRESCAN_PAIR_TIMEOUT_MS,
                    int(remaining * 1000),
                ),
            )
            equivalent, elapsed, calls, details = verify_semantic_path_relation(
                source_path,
                target_path,
                per_pair_ms,
                counterexample_only=True,
            )
            smt_calls += calls
            t_smt += elapsed
            mode = str(details.get("semantic_mode", "unknown"))
            semantic_modes[mode] = semantic_modes.get(mode, 0) + 1
            record = {
                "query": source_id,
                "target": target_id,
                "rank": rank,
                "semantic_equivalent_on_overlap": equivalent is True,
                "details": details,
                "prescan": True,
            }
            records.append(record)
            replay = details.get("replay") or {}
            if replay.get("confirmed"):
                return {
                    "mismatch": record,
                    "records": records,
                    "smt_calls": smt_calls,
                    "t_smt": t_smt,
                    "semantic_modes": semantic_modes,
                    "exhausted_budget": False,
                }
    return {
        "mismatch": None,
        "records": records,
        "smt_calls": smt_calls,
        "t_smt": t_smt,
        "semantic_modes": semantic_modes,
        "exhausted_budget": False,
    }


def verify_ranked_queue(
    paths_dir: Path,
    ranking_path: Path | None,
    timeout_ms: int,
    naive: bool,
    truth_pairs: dict[str, set[str]] | None,
    program_ground_truth: bool | None,
    allow_legacy_artifacts: bool = False,
    allow_one_to_many: bool = True,
) -> dict[str, Any]:
    old_paths = sorted(paths_dir.glob("symbolic_oldV_path_*.txt"), key=lambda p: path_number(p.stem))
    new_paths = sorted(paths_dir.glob("symbolic_newV_path_*.txt"), key=lambda p: path_number(p.stem))
    old_by_id = path_index(old_paths)
    new_by_id = path_index(new_paths)
    exploration = load_exploration_status(paths_dir)
    exploration_ready = all(
        record is not None and record.get("complete") is True
        for record in exploration.values()
    )
    if not exploration_ready and not allow_legacy_artifacts:
        return {
            "method": "unselected",
            "verdict": "UNK",
            "prediction": None,
            "failure_stage": "symbolic_execution",
            "failure_reason": "missing_or_incomplete_exploration_manifest",
            "exploration": exploration,
            "old_path_count": len(old_paths),
            "new_path_count": len(new_paths),
            "candidate_pairs": len(old_paths) * len(new_paths),
            "aligned_pairs": 0,
            "smt_calls": 0,
            "t_align": 0.0,
            "t_smt": 0.0,
            "t_total": 0.0,
            "unknowns": 1,
            "matches": [],
            "reverse_matches": [],
        }

    exact_records = exact_path_bijection_proves_equivalence(old_paths, new_paths)
    if exact_records is not None:
        return {
            "method": "exact_path_bijection",
            "prediction": True,
            "verdict": "EQ",
            "failure_stage": None,
            "alignment_success": True,
            "input_space_equal": True,
            "old_input_subset_new": True,
            "new_input_subset_old": True,
            "old_path_count": len(old_paths),
            "new_path_count": len(new_paths),
            "raw_old_path_count": len(old_paths),
            "raw_new_path_count": len(new_paths),
            "candidate_pairs": len(old_paths) * len(new_paths),
            "aligned_pairs": len(old_paths),
            "smt_calls": 0,
            "t_align": 0.0,
            "t_smt": 0.0,
            "t_total": 0.0,
            "unknowns": 0,
            "semantic_definition": [
                "input_space_equivalence",
                "function_return_value_equivalence",
                "program_output_equivalence",
                "globally_observable_memory_state_equivalence",
            ],
            "semantic_modes": {
                "simplified_path_return_output_state_identity": len(old_paths)
            },
            "matches": exact_records,
            "reverse_matches": [
                {
                    **record,
                    "query": record["match"],
                    "match": record["query"],
                }
                for record in exact_records
            ],
            "confirmed_mismatches": [],
            "exploration": exploration,
            "path_feasibility_filter": {
                "raw_old_path_count": len(old_paths),
                "raw_new_path_count": len(new_paths),
                "removed_unsat_old": 0,
                "removed_unsat_new": 0,
                "unknown_old": 0,
                "unknown_new": 0,
                "timeout_ms": 0,
                "skipped_reason": "exact_path_bijection",
            },
            "allow_one_to_many": allow_one_to_many,
            "exact_path_bijection": True,
        }

    raw_old_path_count = len(old_paths)
    raw_new_path_count = len(new_paths)
    feasibility_timeout_ms = min(timeout_ms, 10_000)
    old_paths, old_unsat, old_feasibility_unknown, old_filter_time = filter_definitely_unsat_paths(
        old_paths, feasibility_timeout_ms
    )
    new_paths, new_unsat, new_feasibility_unknown, new_filter_time = filter_definitely_unsat_paths(
        new_paths, feasibility_timeout_ms
    )
    feasibility_filter = {
        "raw_old_path_count": raw_old_path_count,
        "raw_new_path_count": raw_new_path_count,
        "removed_unsat_old": old_unsat,
        "removed_unsat_new": new_unsat,
        "unknown_old": old_feasibility_unknown,
        "unknown_new": new_feasibility_unknown,
        "timeout_ms": feasibility_timeout_ms,
    }
    if not old_paths or not new_paths:
        return {
            "method": str(ranking_path) if ranking_path else "naive_all_pairs",
            "verdict": "UNK",
            "prediction": None,
            "failure_stage": "path_feasibility",
            "failure_reason": "no_definitely_feasible_paths",
            "old_path_count": len(old_paths),
            "new_path_count": len(new_paths),
            "raw_old_path_count": raw_old_path_count,
            "raw_new_path_count": raw_new_path_count,
            "candidate_pairs": len(old_paths) * len(new_paths),
            "aligned_pairs": 0,
            "smt_calls": raw_old_path_count + raw_new_path_count,
            "t_align": 0.0,
            "t_smt": old_filter_time + new_filter_time,
            "t_total": old_filter_time + new_filter_time,
            "unknowns": 1,
            "matches": [],
            "reverse_matches": [],
            "confirmed_mismatches": [],
            "semantic_modes": {},
            "exploration": exploration,
            "path_feasibility_filter": feasibility_filter,
        }

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

    smt_calls = raw_old_path_count + raw_new_path_count
    t_smt = old_filter_time + new_filter_time
    unknowns = old_feasibility_unknown + new_feasibility_unknown
    semantic_modes: dict[str, int] = {}

    reverse_ranking = invert_ranking(ranking, old_paths, new_paths)
    reverse_truth_pairs = None
    if truth_pairs is not None:
        reverse_truth_pairs = {}
        for old_id, new_ids in truth_pairs.items():
            for new_id in new_ids:
                reverse_truth_pairs.setdefault(new_id, set()).add(old_id)

    if truth_pairs is None:
        prescan = prescan_replayable_counterexample(
            old_paths,
            new_paths,
            ranking,
            timeout_ms,
        )
        if prescan["mismatch"] is None:
            reverse_prescan = prescan_replayable_counterexample(
                new_paths,
                old_paths,
                reverse_ranking,
                timeout_ms,
            )
        else:
            reverse_prescan = {
                "mismatch": None,
                "records": [],
                "smt_calls": 0,
                "t_smt": 0.0,
                "semantic_modes": {},
            }
        smt_calls += int(prescan["smt_calls"]) + int(reverse_prescan["smt_calls"])
        t_smt += float(prescan["t_smt"]) + float(reverse_prescan["t_smt"])
        merge_counter(semantic_modes, prescan["semantic_modes"])
        merge_counter(semantic_modes, reverse_prescan["semantic_modes"])
        mismatch = prescan["mismatch"] or reverse_prescan["mismatch"]
        if mismatch is not None:
            return {
                "method": method,
                "prediction": False,
                "verdict": "NEQ",
                "failure_stage": None,
                "alignment_success": False,
                "input_space_equal": None,
                "old_input_subset_new": None,
                "new_input_subset_old": None,
                "old_path_count": len(old_paths),
                "new_path_count": len(new_paths),
                "candidate_pairs": len(old_paths) * len(new_paths),
                "aligned_pairs": 0,
                "smt_calls": smt_calls,
                "t_align": t_align,
                "t_smt": t_smt,
                "t_total": t_align + t_smt,
                "unknowns": unknowns,
                "semantic_definition": [
                    "input_space_equivalence",
                    "function_return_value_equivalence",
                    "program_output_equivalence",
                    "globally_observable_memory_state_equivalence",
                ],
                "semantic_modes": semantic_modes,
                "matches": prescan["records"],
                "reverse_matches": reverse_prescan["records"],
                "confirmed_mismatches": [mismatch],
                "exploration": exploration,
                "path_feasibility_filter": feasibility_filter,
                "allow_one_to_many": allow_one_to_many,
                "counterexample_prescan": True,
            }

    old_subset_new, elapsed = check_union_coverage(old_paths, new_paths, timeout_ms)
    smt_calls += 1
    t_smt += elapsed
    new_subset_old, elapsed = check_union_coverage(new_paths, old_paths, timeout_ms)
    smt_calls += 1
    t_smt += elapsed
    if old_subset_new is None or new_subset_old is None:
        unknowns += 1
    input_space_equal = old_subset_new is True and new_subset_old is True

    forward = verify_directional_cover(
        old_paths, new_paths, ranking, timeout_ms, truth_pairs, allow_one_to_many
    )
    reverse = verify_directional_cover(
        new_paths, old_paths, reverse_ranking, timeout_ms, reverse_truth_pairs, allow_one_to_many
    )

    smt_calls += int(forward["smt_calls"]) + int(reverse["smt_calls"])
    t_smt += float(forward["t_smt"]) + float(reverse["t_smt"])
    unknowns += int(forward["unknowns"]) + int(reverse["unknowns"])
    merge_counter(semantic_modes, forward["semantic_modes"])
    merge_counter(semantic_modes, reverse["semantic_modes"])

    alignment_success = bool(input_space_equal and forward["success"] and reverse["success"] and unknowns == 0)
    confirmed_mismatches = [
        *forward.get("confirmed_mismatches", []),
        *reverse.get("confirmed_mismatches", []),
    ]
    if alignment_success:
        verdict = "EQ"
        prediction = True
        failure_stage = None
    elif confirmed_mismatches:
        verdict = "NEQ"
        prediction = False
        failure_stage = None
    else:
        verdict = "UNK"
        prediction = None
        failure_stage = "coverage_or_semantic_verification"

    return {
        "method": method,
        "prediction": prediction,
        "verdict": verdict,
        "failure_stage": failure_stage,
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
            "program_output_equivalence",
            "globally_observable_memory_state_equivalence",
        ],
        "semantic_modes": semantic_modes,
        "matches": forward["records"],
        "reverse_matches": reverse["records"],
        "confirmed_mismatches": confirmed_mismatches,
        "exploration": exploration,
            "path_feasibility_filter": feasibility_filter,
        "allow_one_to_many": allow_one_to_many,
    }


def load_exploration_status(paths_dir: Path) -> dict[str, dict[str, Any] | None]:
    out = {}
    for prefix in ("symbolic_oldV", "symbolic_newV"):
        path = paths_dir / f"{prefix}_exploration.json"
        if not path.is_file():
            out[prefix] = None
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            out[prefix] = value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            out[prefix] = None
    return out


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
    parser.add_argument(
        "--allow-legacy-artifacts",
        action="store_true",
        help="Permit path files without exploration manifests (cannot authorize paper-grade EQ).",
    )
    parser.add_argument(
        "--one-to-one-only",
        action="store_true",
        help="Ablation: disable accumulation of one-to-many covering sets.",
    )
    args = parser.parse_args()

    result = verify_ranked_queue(
        args.paths_dir,
        args.ranking,
        args.timeout_ms,
        args.naive,
        parse_truth_pairs(args.truth_pairs_json),
        parse_bool(args.program_ground_truth),
        args.allow_legacy_artifacts,
        not args.one_to_one_only,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
