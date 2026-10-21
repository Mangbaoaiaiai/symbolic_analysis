#!/usr/bin/env python3
"""Verify program equivalence by following a ranked path-pair queue."""

from __future__ import annotations

import ast
import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from z3 import (
    And,
    BitVec,
    BitVecVal,
    BoolVal,
    Context,
    ExprRef,
    FPNumRef,
    Not,
    Or,
    Solver,
    fpToIEEEBV,
    is_app,
    is_bv_value,
    is_fp_value,
    is_int_value,
    is_quantifier,
    parse_smt2_string,
    sat,
    unsat,
)
from z3.z3util import get_vars
from symbolic_analysis.profile import (
    FULL_INPUT_SPACE,
    PAPER_PROFILE_ID,
    SEMANTIC_CONTRACT,
    SMT_TIMEOUT_MS,
    profile_for_input_domains,
)

# Paper Section 4.1 uses 60 seconds for every path-pair SMT comparison.
RETURN_EQ_TIMEOUT_MS = 60_000
# A bounded, SMT-guided pre-scan only looks for a replayable NEQ witness.
# Failure to find one is non-authoritative and falls back to full coverage
# verification.
NEQ_PRESCAN_BUDGET_MS = 15_000
NEQ_PRESCAN_PAIR_TIMEOUT_MS = 2_000

# Source-free UB heuristic. A concrete replay is rejected only when both
# sides independently look like undefined behaviour. Unknown execution
# status is intentionally treated as NEQ under the current experimental
# policy; this is an empirical policy, not a proof of C undefined behaviour.
DEFINEDNESS_POLICY = "anomaly_v1_unknown_as_neq"
REPLAY_REPETITIONS = 3
UB_LIKE_FLAGS = {"crash", "inf", "nan", "subnormal", "unstable"}
_HEX_FLOAT_RE = re.compile(
    r"(?<![A-Za-z0-9_.])[-+]?0x(?:[0-9a-f]+(?:\.[0-9a-f]*)?|\.[0-9a-f]+)p[-+]?\d+(?![A-Za-z0-9_.])",
    re.IGNORECASE,
)


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
        "semantic_contract": dict(SEMANTIC_CONTRACT),
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
    global_eq, global_time, _global_calls, global_mapping = verify_global_state_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    total_time += global_time
    details["global_mapping"] = global_mapping
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
    input_specs = concrete_input_specs(
        collect_variables(left_constraint, right_constraint)
    )
    concrete_replay = replay_standard_inputs(left, right, input_specs)
    standard_observations = (
        list(concrete_replay.get("observations", []))
        if concrete_replay is not None
        else []
    )
    if (
        concrete_replay is not None
        and concrete_replay.get("counterexample") is not None
    ):
        details = {
            "input_overlap": "sat",
            "return_value_equivalent": False,
            "program_output_equivalent": False,
            "memory_state_equivalent": None,
            "global_state_equivalent": None,
            "semantic_mode": "concrete_program_domain_replay",
            "semantic_contract": dict(SEMANTIC_CONTRACT),
            "counterexample": {"inputs": concrete_replay["counterexample"]},
            "counterexample_source": "standard_domain_seed_replay",
            "replay": concrete_replay["replay"],
            "definedness_observations": standard_observations,
        }
        return (
            False,
            time.perf_counter() - start,
            0,
            details,
        )
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
        "semantic_contract": dict(SEMANTIC_CONTRACT),
        "definedness_policy": DEFINEDNESS_POLICY,
    }
    if standard_observations:
        details["definedness_observations"] = standard_observations
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
    if overlap_model is not None:
        seed_inputs = concrete_inputs_from_variables(
            overlap_model,
            collect_variables(left_constraint, right_constraint),
        )
        for inputs in unique_input_seeds(
            [
                seed_inputs,
                sample_inputs_from_path(left),
                sample_inputs_from_path(right),
            ]
        ):
            replay = replay_counterexample(
                left,
                right,
                {"inputs": inputs},
            )
            if replay.get("confirmed"):
                details["return_value_equivalent"] = False
                details["counterexample"] = {"inputs": inputs}
                details["counterexample_source"] = (
                    "path_overlap_model_replay"
                )
                details["replay"] = replay
                return (
                    False,
                    elapsed,
                    smt_calls,
                    details,
                )
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
            replay = replay_counterexample(left, right, counterexample)
            details["replay"] = replay
            if replay_rejected_as_both_ub(replay):
                details["definedness_rejected_return"] = counterexample
                details["definedness_reason"] = "both_ub_like"
                details["conditional_eq"] = True
                merge_replay_observations(
                    details,
                    replay,
                    source="return_counterexample_replay",
                    inputs=(counterexample or {}).get("inputs"),
                )
                return_eq = True
        if return_eq is not True:
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
            replay = replay_counterexample(left, right, counterexample)
            details["replay"] = replay
            if replay_rejected_as_both_ub(replay):
                details["definedness_rejected_output"] = counterexample
                details["definedness_reason"] = "both_ub_like"
                details["conditional_eq"] = True
                merge_replay_observations(
                    details,
                    replay,
                    source="output_counterexample_replay",
                    inputs=(counterexample or {}).get("inputs"),
                )
                output_eq = True
        if output_eq is not True:
            return output_eq, elapsed, smt_calls, details

    details["memory_state_equivalent"] = "auxiliary_not_checked"
    global_eq, global_time, global_calls, global_mapping = verify_global_state_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    elapsed += global_time
    smt_calls += global_calls
    details["global_mapping"] = global_mapping
    details["global_state_equivalent"] = global_eq
    if global_eq is not True:
        details["global_state_reason"] = (
            "symbolic_global_difference_unreplayed"
            if global_eq is False
            else "symbolic_global_evidence_incomplete"
        )
        return global_eq, elapsed, smt_calls, details

    return True, elapsed, smt_calls, details


def replay_rejected_as_both_ub(replay: dict[str, Any]) -> bool:
    return bool(replay) and replay.get("reason") == "both_ub_like"


def compact_replay_run(run: Any) -> dict[str, Any] | None:
    if not isinstance(run, dict):
        return None
    return {
        "completed": run.get("completed"),
        "returncode": run.get("returncode"),
        "stdout": run.get("stdout"),
        "stderr": run.get("stderr"),
    }


def make_replay_observation(
    replay: dict[str, Any],
    *,
    source: str = "counterexample_replay",
    inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a stable, compact event suitable for the final audit report."""
    samples = {
        "left": [
            compact_replay_run(sample)
            for sample in replay.get("left_samples", [])
        ],
        "right": [
            compact_replay_run(sample)
            for sample in replay.get("right_samples", [])
        ],
    }
    variant_payload = {
        "classification": replay.get("classification"),
        "reason": replay.get("reason"),
        "stdin": replay.get("stdin"),
        "observable_output_diff": replay.get("observable_output_diff"),
        "left_flags": replay.get("left_flags", []),
        "right_flags": replay.get("right_flags", []),
        "left": compact_replay_run(replay.get("left")),
        "right": compact_replay_run(replay.get("right")),
        "samples": samples,
    }
    variant_digest = hashlib.sha256(
        json.dumps(
            variant_payload,
            sort_keys=True,
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    logical_payload = {
        "classification": replay.get("classification"),
        "stdin": replay.get("stdin"),
        "inputs": inputs,
    }
    logical_digest = hashlib.sha256(
        json.dumps(
            logical_payload,
            sort_keys=True,
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    variant = {
        "variant_id": f"replay-variant:{variant_digest}",
        "source": source,
        "left_flags": list(replay.get("left_flags", [])),
        "right_flags": list(replay.get("right_flags", [])),
        "left": compact_replay_run(replay.get("left")),
        "right": compact_replay_run(replay.get("right")),
        "samples": samples,
    }
    event = {
        "event_id": f"witness:{logical_digest}",
        "source": source,
        "sources": [source],
        "occurrences": 1,
        "classification": replay.get("classification"),
        "reason": replay.get("reason"),
        "definedness_policy": replay.get(
            "definedness_policy", DEFINEDNESS_POLICY
        ),
        "stdin": replay.get("stdin"),
        "observable_output_diff": replay.get("observable_output_diff"),
        "left_flags": list(replay.get("left_flags", [])),
        "right_flags": list(replay.get("right_flags", [])),
        "left": compact_replay_run(replay.get("left")),
        "right": compact_replay_run(replay.get("right")),
        "samples": samples,
        "variants": [variant],
    }
    if inputs is not None:
        event["inputs"] = inputs
    return event


def merge_replay_observations(
    target: dict[str, Any],
    replay: dict[str, Any],
    *,
    source: str,
    inputs: list[dict[str, Any]] | None = None,
) -> None:
    event = make_replay_observation(
        replay,
        source=source,
        inputs=inputs,
    )
    observations = target.setdefault("definedness_observations", [])
    if not any(
        existing.get("event_id") == event["event_id"]
        for existing in observations
        if isinstance(existing, dict)
    ):
        observations.append(event)


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
        return None, 0.0
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
        left_smt = left.get("smt")
        right_smt = right.get("smt")
        left_var = summary_variable_name(
            left_smt, left.get("variable")
        )
        right_var = summary_variable_name(
            right_smt, right.get("variable")
        )
        signatures_complete = all(
            isinstance(value, str) and value
            for value in (left_smt, right_smt, left_var, right_var)
        )
        if signatures_complete:
            left_signature = _smt_defined_expr_signature(left_smt, left_var)
            right_signature = _smt_defined_expr_signature(right_smt, right_var)
            if (
                left_signature is not None
                and left_signature == right_signature
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
        ):
            return False
        left_smt = left.get("smt")
        right_smt = right.get("smt")
        left_var = summary_variable_name(
            left_smt, left.get("variable")
        )
        right_var = summary_variable_name(
            right_smt, right.get("variable")
        )
        if not all(
            isinstance(value, str) and value
            for value in (left_smt, right_smt, left_var, right_var)
        ):
            return False
        left_signature = _smt_defined_expr_signature(left_smt, left_var)
        right_signature = _smt_defined_expr_signature(right_smt, right_var)
        if (
            left_signature is None
            or right_signature is None
            or left_signature != right_signature
        ):
            return False
    return True


def global_regions_identical(
    left_state: dict[str, Any],
    right_state: dict[str, Any],
) -> bool:
    left_regions = left_state.get("regions")
    right_regions = right_state.get("regions")
    if not isinstance(left_regions, dict) or not isinstance(right_regions, dict):
        return False
    if set(left_regions) != set(right_regions):
        return False
    for key in sorted(left_regions):
        left = left_regions[key]
        right = right_regions[key]
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False
        if int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0):
            return False
        left_smt = left.get("smt")
        right_smt = right.get("smt")
        left_var = summary_variable_name(
            left_smt, left.get("variable")
        )
        right_var = summary_variable_name(
            right_smt, right.get("variable")
        )
        if not all(
            isinstance(value, str) and value
            for value in (left_smt, right_smt, left_var, right_var)
        ):
            return False
        left_signature = _smt_defined_expr_signature(left_smt, left_var)
        right_signature = _smt_defined_expr_signature(right_smt, right_var)
        if (
            left_signature is None
            or right_signature is None
            or left_signature != right_signature
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
            left_smt = left.get("smt")
            right_smt = right.get("smt")
            left_var = summary_variable_name(
                left_smt, left.get("variable")
            )
            right_var = summary_variable_name(
                right_smt, right.get("variable")
            )
            if not all(
                isinstance(value, str) and value
                for value in (left_smt, right_smt, left_var, right_var)
            ):
                return None
            left_signature = _smt_defined_expr_signature(left_smt, left_var)
            right_signature = _smt_defined_expr_signature(right_smt, right_var)
            if (
                left_signature is not None
                and left_signature == right_signature
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
    if not (
        left_return.get("available")
        and right_return.get("available")
        and left_return.get("bits") == right_return.get("bits")
    ):
        return False
    left_smt = left_return.get("smt")
    right_smt = right_return.get("smt")
    left_var = return_variable_name(left_smt)
    right_var = return_variable_name(right_smt)
    if not left_smt or not right_smt or not left_var or not right_var:
        return False
    left_signature = _smt_defined_expr_signature(left_smt, left_var)
    right_signature = _smt_defined_expr_signature(right_smt, right_var)
    return left_signature is not None and left_signature == right_signature


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
        return None, 0.0, 0
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
        return None, 0.0, 0

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
) -> tuple[bool | None, float, int, dict[str, Any]]:
    left_state = left_summary.get("global_state") or {}
    right_state = right_summary.get("global_state") or {}
    if not left_state.get("available") or not right_state.get("available"):
        return None, 0.0, 0, {
            "method": "unavailable",
            "reason": "global_state_unavailable",
        }
    left_regions = left_state.get("regions")
    right_regions = right_state.get("regions")
    if not isinstance(left_regions, dict) or not isinstance(right_regions, dict):
        return None, 0.0, 0, {
            "method": "unavailable",
            "reason": "global_regions_malformed",
        }
    if not left_regions and not right_regions:
        return True, 0.0, 0, {
            "method": "empty_observation_scope",
            "assumptions": [],
        }

    pairs, mapping_evidence = map_global_regions_with_evidence(
        left_regions, right_regions
    )
    if pairs is None:
        return None, 0.0, 0, mapping_evidence
    total_time = 0.0
    calls = 0
    for left_cell, right_cell in pairs:
        equivalent, elapsed = verify_observable_expr_equivalence(
            left_cell, right_cell, timeout_ms, left_path, right_path
        )
        total_time += elapsed
        calls += int(bool(left_cell.get("smt") and right_cell.get("smt")))
        if equivalent is not True:
            return equivalent, total_time, calls, mapping_evidence
    return True, total_time, calls, mapping_evidence


def map_global_regions(
    left_regions: dict[str, Any], right_regions: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]] | None:
    """Map normalized global cells, then fall back to structural position.

    Exact section-relative keys implement fixed-address/consistent-shift
    normalization.  Structural fallback is accepted only for a unique ordered
    mapping with identical cell widths.
    """
    pairs, _evidence = map_global_regions_with_evidence(
        left_regions, right_regions
    )
    return pairs


READ_ONLY_SECTIONS = {".rodata", ".data.rel.ro", ".text"}


def _cell_content_sha256(cell: dict[str, Any]) -> str | None:
    content = cell.get("initial_content_sha256")
    if isinstance(content, dict):
        value = content.get("sha256")
        return str(value) if value else None
    return None


def _cell_ast_signature(cell: dict[str, Any]) -> tuple[Any, ...] | None:
    smt = cell.get("smt")
    expected = cell.get("variable")
    variable = summary_variable_name(smt, expected)
    if not smt or not variable:
        return None
    return _smt_defined_expr_signature(smt, variable)


def _global_candidate_evidence(
    left_items: list[dict[str, Any]],
    right_items: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], dict[str, Any], str]]]:
    layout_pairs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    readonly_pairs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    ast_targets: dict[int, list[dict[str, Any]]] = {}
    for left in left_items:
        left_hash = _cell_content_sha256(left)
        left_section = str(left.get("section") or "")
        left_signature = _cell_ast_signature(left)
        for right in right_items:
            if int(left.get("bits", 0) or 0) != int(
                right.get("bits", 0) or 0
            ):
                continue
            right_hash = _cell_content_sha256(right)
            right_section = str(right.get("section") or "")
            if (
                left_section
                and left_section == right_section
                and int(left.get("offset", -1) or 0)
                == int(right.get("offset", -2) or 0)
                and int(left.get("size_bytes", 0) or 0)
                == int(right.get("size_bytes", 0) or 0)
                and left_hash is not None
                and left_hash == right_hash
            ):
                layout_pairs.append((left, right, "layout_content"))
            if (
                left_section in READ_ONLY_SECTIONS
                and left_section == right_section
                and left_hash is not None
                and left_hash == right_hash
            ):
                readonly_pairs.append((left, right, "readonly_content"))
            if (
                left_signature is not None
                and left_signature == _cell_ast_signature(right)
            ):
                ast_targets.setdefault(id(left), []).append(right)

    evidence = {
        "layout_content_candidates": len(layout_pairs),
        "readonly_content_candidates": len(readonly_pairs),
        "ast_context_candidates": sum(
            len(targets) for targets in ast_targets.values()
        ),
        "ambiguous_ast_candidates": sum(
            len(targets)
            for targets in ast_targets.values()
            if len(targets) > 1
        ),
    }
    unique_pairs = []
    for candidates in (readonly_pairs, layout_pairs):
        left_counts = Counter(id(left) for left, _right, _kind in candidates)
        right_counts = Counter(id(right) for _left, right, _kind in candidates)
        for left, right, kind in candidates:
            if left_counts[id(left)] == 1 and right_counts[id(right)] == 1:
                unique_pairs.append((left, right, kind))
    return evidence, unique_pairs


def map_global_regions_with_evidence(
    left_regions: dict[str, Any], right_regions: dict[str, Any]
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]] | None, dict[str, Any]]:
    if set(left_regions) == set(right_regions):
        pairs = [
            (left_regions[key], right_regions[key])
            for key in sorted(left_regions)
        ]
        return pairs, {
            "method": "exact_canonical_key",
            "assumptions": [],
            "mapped_regions": len(pairs),
        }

    left_items = sorted(left_regions.items())
    right_items = sorted(right_regions.items())
    left_by_id = {}
    right_by_id = {}
    for index, (_key, cell) in enumerate(left_items):
        identity = _region_identity(cell, index)
        left_by_id.setdefault(identity, []).append(cell)
    for index, (_key, cell) in enumerate(right_items):
        identity = _region_identity(cell, index)
        right_by_id.setdefault(identity, []).append(cell)

    used_left = set()
    used_right = set()
    pairs = []
    assumptions = []
    methods = []
    for identity, left_cells in left_by_id.items():
        right_cells = right_by_id.get(identity, [])
        if len(left_cells) != 1 or len(right_cells) != 1:
            continue
        left = left_cells[0]
        right = right_cells[0]
        if int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0):
            continue
        pairs.append((left, right))
        used_left.add(id(left))
        used_right.add(id(right))
        methods.append("identity_key")
        if identity[0] == "position":
            assumptions.append("position_identity")

    remaining_left = [
        cell for _key, cell in left_items if id(cell) not in used_left
    ]
    remaining_right = [
        cell for _key, cell in right_items if id(cell) not in used_right
    ]
    if len(remaining_left) != len(remaining_right):
        return None, {
            "method": "failed",
            "reason": "region_count_mismatch_after_identity_mapping",
            "assumptions": assumptions,
            "left_unmapped": len(remaining_left),
            "right_unmapped": len(remaining_right),
        }

    candidate_evidence, unique_candidates = _global_candidate_evidence(
        remaining_left,
        remaining_right,
    )
    for left, right, kind in unique_candidates:
        remaining_left_ids = {id(item) for item in remaining_left}
        remaining_right_ids = {id(item) for item in remaining_right}
        if id(left) not in remaining_left_ids or id(right) not in remaining_right_ids:
            continue
        pairs.append((left, right))
        methods.append(kind)
        assumptions.append(f"{kind}_unique_pair")
        remaining_left = [
            item for item in remaining_left if item is not left
        ]
        remaining_right = [
            item for item in remaining_right if item is not right
        ]

    if len(remaining_left) != len(remaining_right):
        return None, {
            "method": "failed",
            "reason": "region_count_mismatch_after_evidence_mapping",
            "assumptions": assumptions,
            "candidate_evidence": candidate_evidence,
            "left_unmapped": len(remaining_left),
            "right_unmapped": len(remaining_right),
        }

    for left, right in zip(remaining_left, remaining_right):
        if not isinstance(left, dict) or not isinstance(right, dict):
            return None, {
                "method": "failed",
                "reason": "malformed_region",
                "assumptions": assumptions,
            }
        if int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0):
            return None, {
                "method": "failed",
                "reason": "width_conflict",
                "assumptions": assumptions,
            }
        pairs.append((left, right))
        methods.append("sorted_width_compatible_fallback")
    if remaining_left:
        assumptions.extend(
            [
                "sorted_region_position",
                "compatible_width",
                "identity_not_proved_by_fallback",
            ]
        )
    return pairs, {
        "method": "exact_then_sorted_width_fallback",
        "methods": sorted(set(methods)),
        "assumptions": assumptions,
        "mapped_regions": len(pairs),
        "candidate_evidence": candidate_evidence,
        "fallback_regions": len(remaining_left),
        "fallback_order": "sorted_canonical_key" if remaining_left else None,
    }


def _region_identity(cell: Any, fallback_index: int) -> tuple[Any, ...]:
    if not isinstance(cell, dict):
        return ("position", fallback_index)
    object_name = cell.get("object")
    offset = cell.get("offset")
    size_bytes = cell.get("size_bytes")
    if object_name is not None and offset is not None and size_bytes is not None:
        return ("object", str(object_name), int(offset), int(size_bytes))
    key = cell.get("key")
    if isinstance(key, str):
        return ("key", key)
    return ("position", fallback_index)


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
    left_var = summary_variable_name(left_smt, left.get("variable"))
    right_var = summary_variable_name(right_smt, right.get("variable"))
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


def complete_replay_inputs(
    left_path: Path,
    right_path: Path,
    inputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill arguments omitted by an unconstrained SMT model.

    A model only assigns input variables that occur in the queried formulas.
    Replaying that partial assignment directly leaves later ``scanf``
    parameters uninitialized.  Path artifacts retain a complete satisfying
    sample, so use it for omitted argument positions while keeping every
    counterexample-provided value unchanged.
    """

    def key(item: dict[str, Any]) -> tuple[int, str]:
        return input_symbol_order(str(item.get("name") or ""))

    supplied = {key(item)[0]: item for item in inputs}
    signature_samples = {
        key(item)[0]: item
        for item in (
            sample_inputs_from_path(left_path)
            + sample_inputs_from_path(right_path)
        )
    }
    if not supplied:
        return []

    max_index = max(
        [*supplied.keys(), *signature_samples.keys()],
        default=-1,
    )
    if max_index < 0:
        return inputs

    template = min(supplied.values(), key=key)
    template_name = str(template.get("name") or "")
    template_bits = int(template.get("bits", 32) or 32)
    prefix = (
        "FP_arg"
        if template_name.startswith("FP_arg_")
        else "scanf"
        if template_name.startswith("scanf_")
        else "arg"
    )
    completed: list[dict[str, Any]] = []
    for index in range(max_index + 1):
        item = supplied.get(index)
        if item is not None:
            completed.append(item)
            continue
        sample = signature_samples.get(index)
        if sample is not None:
            if prefix == "FP_arg":
                completed.append(
                    {
                        "name": f"FP_arg_{index}_{index}_{template_bits}",
                        "kind": "float",
                        "bits": template_bits,
                        "value": 0.0,
                        "ieee_bits": int(sample.get("unsigned", 0)) & ((1 << template_bits) - 1),
                    }
                )
            else:
                integer = int(sample.get("value", 0))
                completed.append(
                    {
                        "name": f"arg_{index}_{index}_{template_bits}",
                        "kind": "bitvec",
                        "bits": template_bits,
                        "value": integer,
                        "unsigned": integer & ((1 << template_bits) - 1),
                    }
                )
            continue
        if prefix == "FP_arg":
            completed.append(
                {
                    "name": f"FP_arg_{index}_{index}_{template_bits}",
                    "kind": "float",
                    "bits": template_bits,
                    "value": 0.0,
                }
            )
        else:
            completed.append(
                {
                    "name": f"arg_{index}_{index}_{template_bits}",
                    "kind": "bitvec",
                    "bits": template_bits,
                    "value": 0,
                    "unsigned": 0,
                }
            )
    return completed


def unique_input_seeds(
    candidates: list[list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    unique = []
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        key = tuple(
            sorted(
                (
                    str(item.get("name") or ""),
                    str(item.get("kind") or ""),
                    repr(item.get("value")),
                )
                for item in candidate
            )
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def concrete_input_specs(
    variables: list[Any],
) -> tuple[tuple[str, str, int, int], ...]:
    specs = {}
    for variable in variables:
        name = variable.decl().name()
        if not is_input_symbol(name):
            continue
        sort_text = str(variable.sort())
        bitvec = re.fullmatch(r"BitVec\((\d+)\)", sort_text)
        if bitvec:
            specs[name] = ("bitvec", int(bitvec.group(1)), 0)
            continue
        floating = re.fullmatch(
            r"(?:FloatingPoint|FPSort)\((\d+), (\d+)\)",
            sort_text,
        )
        if floating:
            exponent_bits = int(floating.group(1))
            significand_bits = int(floating.group(2))
            specs[name] = (
                "float",
                exponent_bits + significand_bits,
                0,
            )
    return tuple(
        (name, kind, bits, precision)
        for name, (kind, bits, precision) in sorted(
            specs.items(),
            key=lambda item: input_symbol_order(item[0]),
        )
    )


def standard_input_seeds(
    specs: tuple[tuple[str, str, int, int], ...],
) -> list[list[dict[str, Any]]]:
    def make_seed(values: list[int | float]) -> list[dict[str, Any]]:
        seed = []
        for (name, kind, bits, _precision), value in zip(specs, values):
            if kind == "bitvec":
                integer = int(value)
                seed.append(
                    {
                        "name": name,
                        "kind": "bitvec",
                        "bits": bits,
                        "value": integer,
                        "unsigned": integer & ((1 << bits) - 1),
                    }
                )
            else:
                seed.append(
                    {
                        "name": name,
                        "kind": "float",
                        "bits": bits,
                        "value": float(value),
                    }
                )
        return seed

    if not specs:
        return []
    count = len(specs)
    seeds = [
        make_seed([0] * count),
        make_seed([1] * count),
    ]
    for index in range(count):
        for value in (-1, 0, 1, 2, 10, 11):
            values: list[int | float] = [1] * count
            values[index] = value
            seeds.append(make_seed(values))
    return unique_input_seeds(seeds)


_STANDARD_SEED_REPLAY_CACHE: dict[
    tuple[str, str, tuple[tuple[str, str, int, int], ...]],
    dict[str, Any],
] = {}


def replay_result_is_auditable(replay: dict[str, Any]) -> bool:
    return bool(replay.get("confirmed")) or replay.get("classification") in {
        "both_ub_like",
        "asymmetric_ub_like",
        "ub_status_unknown",
    }


def replay_standard_inputs(
    left: Path,
    right: Path,
    specs: tuple[tuple[str, str, int, int], ...],
) -> dict[str, Any] | None:
    left_binary = binary_for_path(left)
    right_binary = binary_for_path(right)
    if left_binary is None or right_binary is None:
        return None
    cache_key = (str(left_binary), str(right_binary), specs)
    if cache_key in _STANDARD_SEED_REPLAY_CACHE:
        return _STANDARD_SEED_REPLAY_CACHE[cache_key]
    observations: list[dict[str, Any]] = []
    for seed in standard_input_seeds(specs):
        replay = replay_counterexample(
            left,
            right,
            {"inputs": seed},
        )
        if replay_result_is_auditable(replay):
            observations.append(
                make_replay_observation(
                    replay,
                    source="standard_domain_seed_replay",
                    inputs=seed,
                )
            )
        if replay.get("confirmed"):
            result = {
                "counterexample": seed,
                "replay": replay,
                "observations": observations,
            }
            _STANDARD_SEED_REPLAY_CACHE[cache_key] = result
            return result
    result = {
        "counterexample": None,
        "replay": None,
        "observations": observations,
    }
    _STANDARD_SEED_REPLAY_CACHE[cache_key] = result
    return result


def program_domain_counterexample(
    source_paths: list[Path],
    target_paths: list[Path],
) -> dict[str, Any] | None:
    if not source_paths or not target_paths:
        return None
    left = source_paths[0]
    right = target_paths[0]
    ctx = Context()
    left_constraint = parse_formula(left, ctx)
    right_constraint = parse_formula(right, ctx)
    specs = concrete_input_specs(
        collect_variables(left_constraint, right_constraint)
    )
    replay = replay_standard_inputs(left, right, specs)
    if replay is None or replay.get("counterexample") is None:
        return None
    return {
        "source": left.stem,
        "target": right.stem,
        "rank": 1,
        "counterexample": {"inputs": replay["counterexample"]},
        "replay": replay["replay"],
        "counterexample_source": "standard_domain_seed_replay",
    }


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
        if str(value).strip() == "NaN":
            # Z3 rejects sign/significand accessors for NaN numerals.
            raw = (
                ((1 << int(value.ebits())) - 1)
                << (int(value.sbits()) - 1)
            ) | (1 << (int(value.sbits()) - 2))
        else:
            raw = (
                (int(bool(value.sign())) << (bits - 1))
                | (
                    int(value.exponent_as_long())
                    << (bits - value.ebits() - 1)
                )
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
    inputs = complete_replay_inputs(
        left_path,
        right_path,
        counterexample["inputs"],
    )
    tokens = [format_replay_value(item) for item in inputs]
    stdin = " ".join(tokens) + "\n"
    left_run = run_binary(left_binary, stdin)
    right_run = run_binary(right_binary, stdin)

    left_samples = [left_run]
    right_samples = [right_run]
    output_diff = not replay_observables_equal(left_run, right_run)
    left_flags = replay_anomaly_flags(left_run)
    right_flags = replay_anomaly_flags(right_run)

    # Stability checks are only needed for a concrete mismatch or an already
    # suspicious value. This keeps the common clean-replay path cheap.
    needs_stability_check = bool(
        output_diff
        or left_flags
        or right_flags
        or not left_run.get("completed")
        or not right_run.get("completed")
    )
    if needs_stability_check:
        for _ in range(max(0, REPLAY_REPETITIONS - 1)):
            left_samples.append(run_binary(left_binary, stdin))
            right_samples.append(run_binary(right_binary, stdin))

    if replay_samples_unstable(left_samples):
        left_flags.add("unstable")
    if replay_samples_unstable(right_samples):
        right_flags.add("unstable")

    left_ub_like = bool(left_flags & UB_LIKE_FLAGS)
    right_ub_like = bool(right_flags & UB_LIKE_FLAGS)
    unknown = bool(
        (left_flags | right_flags) & {"execution_unknown"}
    )
    if left_ub_like and right_ub_like:
        confirmed = False
        reason = "both_ub_like"
        classification = "both_ub_like"
    elif unknown:
        # Experimental policy chosen for deployment on binaries whose source
        # is unavailable: unresolved UB status confirms a candidate NEQ.
        confirmed = True
        reason = "ub_status_unknown"
        classification = "ub_status_unknown"
    elif left_ub_like or right_ub_like:
        confirmed = True
        reason = "asymmetric_ub_like"
        classification = "asymmetric_ub_like"
    elif output_diff:
        confirmed = True
        reason = "observable_output_diff"
        classification = "defined_neq"
    else:
        confirmed = False
        reason = "no_observable_output_diff"
        classification = "defined_equal"

    return {
        "confirmed": confirmed,
        "reason": reason,
        "classification": classification,
        "definedness_policy": DEFINEDNESS_POLICY,
        "stdin": stdin,
        "observable_output_diff": output_diff,
        "replay_count": max(len(left_samples), len(right_samples)),
        "left_flags": sorted(left_flags),
        "right_flags": sorted(right_flags),
        "left": left_run,
        "right": right_run,
        "left_samples": left_samples,
        "right_samples": right_samples,
    }


def replay_anomaly_flags(run: dict[str, Any]) -> set[str]:
    """Return source-free heuristic evidence for undefined-like execution."""
    if not run.get("completed"):
        return {"execution_unknown"}

    flags: set[str] = set()
    returncode = run.get("returncode")
    if isinstance(returncode, int) and returncode < 0:
        flags.add("crash")

    text = f"{run.get('stdout') or ''}\n{run.get('stderr') or ''}"
    if re.search(r"(?i)(?<![A-Za-z0-9_.])[-+]?nan(?![A-Za-z0-9_])", text):
        flags.add("nan")
    if re.search(
        r"(?i)(?<![A-Za-z0-9_.])[-+]?(?:inf(?:inity)?)(?![A-Za-z0-9_])",
        text,
    ):
        flags.add("inf")

    minimum_normal = 2.2250738585072014e-308
    for token in _HEX_FLOAT_RE.findall(text):
        try:
            value = float.fromhex(token)
        except (OverflowError, ValueError):
            continue
        if math.isfinite(value) and value != 0.0 and abs(value) < minimum_normal:
            flags.add("subnormal")
            break
    return flags


def replay_samples_unstable(samples: list[dict[str, Any]]) -> bool:
    if len(samples) < 2:
        return False
    signatures = {
        (
            sample.get("completed"),
            sample.get("returncode"),
            normalize_replay_nan_text(sample.get("stdout")),
            normalize_replay_nan_text(sample.get("stderr")),
        )
        for sample in samples
    }
    return len(signatures) > 1


def normalize_replay_nan_text(value: Any) -> str:
    """Treat IEEE NaN sign/payload formatting as one abstract observable."""
    return re.sub(
        r"(?i)(?<![A-Za-z0-9_.])[-+]?nan(?![A-Za-z0-9_])",
        "nan",
        str(value or ""),
    )


def replay_observables_equal(
    left_run: dict[str, Any],
    right_run: dict[str, Any],
) -> bool:
    return (
        left_run.get("returncode") == right_run.get("returncode")
        and normalize_replay_nan_text(left_run.get("stdout"))
        == normalize_replay_nan_text(right_run.get("stdout"))
        and normalize_replay_nan_text(left_run.get("stderr"))
        == normalize_replay_nan_text(right_run.get("stderr"))
    )


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


@lru_cache(maxsize=4096)
def _smt_defined_expr_signature(
    smt_text: str,
    definition_variable: str,
) -> tuple[Any, ...] | None:
    """Return an alpha-normalized signature for a summary-defined expression.

    SMT-LIB is parsed in a fresh context so a malformed summary cannot poison
    later comparisons. The defined variable is renamed to a canonical marker;
    all free input symbols retain their names and sorts.
    """
    try:
        ctx = Context()
        formula = formula_from_smt_text(smt_text, ctx)
    except Exception:
        return None

    stack = [formula]
    while stack:
        current = stack.pop()
        if is_app(current) and current.decl().name() == "and":
            stack.extend(current.arg(i) for i in range(current.num_args()))
            continue
        if not (is_app(current) and current.decl().name() == "="):
            continue
        if current.num_args() != 2:
            continue
        left, right = current.arg(0), current.arg(1)
        if str(left) == definition_variable or str(right) == definition_variable:
            expression = right if str(left) == definition_variable else left
            return _canonical_expr_signature(
                expression,
                definition_variable=definition_variable,
            )
    return None


def _canonical_expr_signature(
    expr: ExprRef,
    *,
    definition_variable: str,
) -> tuple[Any, ...]:
    if is_app(expr) and expr.num_args() == 0:
        if is_bv_value(expr):
            return ("const", "bitvec", int(expr.size()), int(expr.as_long()))
        if is_int_value(expr):
            return ("const", "int", str(expr))
        if is_fp_value(expr):
            return ("const", "fp", str(expr.sort()), expr.sexpr())
        name = "__SUMMARY_VALUE__" if str(expr) == definition_variable else str(expr)
        return ("symbol", name, str(expr.sort()))
    if is_app(expr):
        return (
            "app",
            str(expr.decl().name()),
            str(expr.sort()),
            tuple(
                _canonical_expr_signature(
                    expr.arg(index),
                    definition_variable=definition_variable,
                )
                for index in range(expr.num_args())
            ),
        )
    if is_quantifier(expr):
        return ("quantifier", expr.sexpr())
    return ("other", expr.sexpr())


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


def summary_variable_name(
    smt_text: str | None,
    expected_name: str | None,
) -> str | None:
    """Resolve the backend-mangled definition symbol for a summary cell."""
    if not smt_text or not expected_name:
        return None
    declared = re.findall(r"\(declare-fun\s+([^\s()]+)\s+\(\)", smt_text)
    if expected_name in declared:
        return expected_name
    matching = [
        name
        for name in declared
        if name.startswith(expected_name + "_")
    ]
    return matching[0] if len(matching) == 1 else None


def check_input_coverage(old_path: Path, covering_new_paths: list[Path], timeout_ms: int) -> tuple[bool | None, float]:
    if not covering_new_paths:
        return False, 0.0
    old_text = exact_path_condition_text(old_path)
    if any(
        old_text == exact_path_condition_text(path)
        for path in covering_new_paths
    ):
        return True, 0.0
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
    if sorted(exact_path_condition_text(path) for path in source_paths) == sorted(
        exact_path_condition_text(path) for path in target_paths
    ):
        return True, 0.0
    start = time.perf_counter()
    ctx = Context()
    source_formulas = [parse_formula(path, ctx) for path in source_paths]
    target_formulas = [parse_formula(path, ctx) for path in target_paths]
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
                if semantic_details.get("global_state_reason") in {
                    "symbolic_global_difference_unreplayed",
                    "symbolic_global_evidence_incomplete",
                }:
                    candidate_unknowns += 1
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
        if exact_path_condition_text(old_path) != exact_path_condition_text(new_path):
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
            or not global_regions_identical(old_global, new_global)
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
                "proof": "exact_path_formula_and_observable_summary_identity",
            }
        )
    return records


def exact_path_condition_text(path: Path) -> str:
    """Return the unnormalized SMT formula without benchmark metadata."""
    content = path.read_text(encoding="utf-8", errors="replace")
    marker = "\n; Path signature:"
    if marker in content:
        return content.split(marker, 1)[0]
    return content


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
            "semantic_contract": dict(SEMANTIC_CONTRACT),
            "profile_id": PAPER_PROFILE_ID,
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
            "semantic_contract": dict(SEMANTIC_CONTRACT),
            "profile_id": PAPER_PROFILE_ID,
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
            "matching_counts": {
                "old_to_new_records": len(exact_records),
                "new_to_old_records": len(exact_records),
                "one_to_many_old_to_new": 0,
                "one_to_many_new_to_old": 0,
                "one_to_many_cases": 0,
            },
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

    if truth_pairs is None:
        replay_started = time.perf_counter()
        domain_mismatch = program_domain_counterexample(
            old_paths,
            new_paths,
        )
        replay_elapsed = time.perf_counter() - replay_started
        if domain_mismatch is not None:
            if naive:
                method = "naive_all_pairs"
                t_align = 0.0
            else:
                if ranking_path is None:
                    raise ValueError("--ranking is required unless --naive is used")
                ranking_data = json.loads(
                    ranking_path.read_text(encoding="utf-8")
                )
                timing = (
                    ranking_data.get("timing", {})
                    if isinstance(ranking_data, dict)
                    else {}
                )
                t_align = float(
                    timing.get(
                        "t_align",
                        ranking_data.get("t_align", 0.0),
                    )
                    or 0.0
                )
                method = str(ranking_data.get("method", "ranked"))
            record_details = {
                "input_overlap": "sat",
                "return_value_equivalent": False,
                "program_output_equivalent": False,
                "memory_state_equivalent": None,
                "global_state_equivalent": None,
                "semantic_mode": "concrete_program_domain_replay",
                "semantic_contract": dict(SEMANTIC_CONTRACT),
                "counterexample": domain_mismatch["counterexample"],
                "counterexample_source": "standard_domain_seed_replay",
                "replay": domain_mismatch["replay"],
            }
            match_record = {
                "query": domain_mismatch["source"],
                "target": domain_mismatch["target"],
                "rank": 1,
                "semantic_equivalent_on_overlap": False,
                "details": record_details,
                "prescan": True,
            }
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
                "smt_calls": 0,
                "t_align": t_align,
                "t_smt": replay_elapsed,
                "t_total": t_align + replay_elapsed,
                "unknowns": 0,
                "semantic_contract": dict(SEMANTIC_CONTRACT),
                "profile_id": PAPER_PROFILE_ID,
                "semantic_definition": [
                    "input_space_equivalence",
                    "function_return_value_equivalence",
                    "program_output_equivalence",
                    "globally_observable_memory_state_equivalence",
                ],
                "semantic_modes": {
                    "concrete_program_domain_replay": 1
                },
                "matches": [match_record],
                "reverse_matches": [],
                "confirmed_mismatches": [
                    {
                        "source": domain_mismatch["source"],
                        "target": domain_mismatch["target"],
                        "rank": 1,
                        "counterexample": domain_mismatch["counterexample"],
                        "replay": domain_mismatch["replay"],
                    }
                ],
                "matching_counts": {
                    "old_to_new_records": 0,
                    "new_to_old_records": 0,
                    "one_to_many_old_to_new": 0,
                    "one_to_many_new_to_old": 0,
                    "one_to_many_cases": 0,
                },
                "exploration": exploration,
                "path_feasibility_filter": {
                    "raw_old_path_count": len(old_paths),
                    "raw_new_path_count": len(new_paths),
                    "removed_unsat_old": 0,
                    "removed_unsat_new": 0,
                    "unknown_old": 0,
                    "unknown_new": 0,
                    "timeout_ms": 0,
                    "skipped_reason": "neq_program_domain_replay",
                },
                "allow_one_to_many": allow_one_to_many,
                "counterexample_prescan": True,
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
            "semantic_contract": dict(SEMANTIC_CONTRACT),
            "profile_id": PAPER_PROFILE_ID,
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
                "semantic_contract": dict(SEMANTIC_CONTRACT),
                "profile_id": PAPER_PROFILE_ID,
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

    matching_counts = {
        "old_to_new_records": sum(
            1 for record in forward["records"] if record["matched"]
        ),
        "new_to_old_records": sum(
            1 for record in reverse["records"] if record["matched"]
        ),
        "one_to_many_old_to_new": sum(
            1
            for record in forward["records"]
            if record["matched"]
            and str(record.get("match_type", "")).startswith("one_to_many")
        ),
        "one_to_many_new_to_old": sum(
            1
            for record in reverse["records"]
            if record["matched"]
            and str(record.get("match_type", "")).startswith("one_to_many")
        ),
        "one_to_many_cases": len(
            {
                record["query"]
                for record in forward["records"] + reverse["records"]
                if record["matched"]
                and str(record.get("match_type", "")).startswith("one_to_many")
            }
        ),
    }

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
        "semantic_contract": dict(SEMANTIC_CONTRACT),
        "profile_id": PAPER_PROFILE_ID,
        "profile": profile_from_exploration(exploration),
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
        "matching_counts": matching_counts,
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


def profile_from_exploration(
    exploration: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    """Read the input domain actually recorded by path generation."""
    integer_domain: Any = None
    floating_domain: Any = None
    for side in exploration.values():
        if not side:
            continue
        ranges = side.get("input_ranges") or {}
        if integer_domain is None:
            integer_domain = ranges.get("integer")
        if floating_domain is None:
            floating_domain = ranges.get("floating_point")

    def bounds(value: Any) -> tuple[int | float | None, int | float | None]:
        if value in (None, FULL_INPUT_SPACE, "unbounded"):
            return None, None
        if isinstance(value, list) and len(value) == 2:
            return value[0], value[1]
        return None, None

    int_min, int_max = bounds(integer_domain)
    float_min, float_max = bounds(floating_domain)
    return profile_for_input_domains(
        int_min,
        int_max,
        float_min,
        float_max,
    )


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


def collect_definedness_audit(result: Any) -> dict[str, Any]:
    """Summarize replay classifications without changing the verdict."""
    events: dict[str, dict[str, Any]] = {}
    stack = [result]
    seen: set[int] = set()
    seen_replays: set[int] = set()

    def add_event(event: dict[str, Any]) -> None:
        event_id = event.get("event_id")
        classification = event.get("classification")
        if not isinstance(event_id, str) or not classification:
            return
        if event_id not in events:
            normalized = dict(event)
            normalized.setdefault("occurrences", 1)
            normalized.setdefault("sources", [normalized.get("source")])
            normalized.setdefault("variants", [])
            events[event_id] = normalized
            return

        existing = events[event_id]
        existing["occurrences"] = int(existing.get("occurrences", 1)) + int(
            event.get("occurrences", 1)
        )
        source = event.get("source")
        if source and source not in existing.setdefault("sources", []):
            existing["sources"].append(source)
        if not existing.get("inputs") and event.get("inputs"):
            existing["inputs"] = event["inputs"]
        known_variants = {
            variant.get("variant_id")
            for variant in existing.setdefault("variants", [])
            if isinstance(variant, dict)
        }
        for variant in event.get("variants", []):
            if (
                isinstance(variant, dict)
                and variant.get("variant_id") not in known_variants
            ):
                existing["variants"].append(variant)
                known_variants.add(variant.get("variant_id"))
        existing["left_flags"] = sorted(
            set(existing.get("left_flags", []))
            | set(event.get("left_flags", []))
        )
        existing["right_flags"] = sorted(
            set(existing.get("right_flags", []))
            | set(event.get("right_flags", []))
        )

    while stack:
        value = stack.pop()
        if isinstance(value, dict) and id(value) in seen_replays:
            continue
        if isinstance(value, (dict, list)):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
        if isinstance(value, dict):
            if value.get("event_id") and value.get("classification"):
                add_event(value)
            replay = value.get("replay")
            if isinstance(replay, dict):
                counterexample = (
                    value.get("counterexample")
                    or value.get("output_counterexample")
                )
                inputs = (
                    counterexample.get("inputs")
                    if isinstance(counterexample, dict)
                    else None
                )
                add_event(
                    make_replay_observation(
                        replay,
                        source="verification_counterexample_replay",
                        inputs=inputs,
                    )
                )
                seen_replays.add(id(replay))
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)

    counts: Counter[str] = Counter(
        str(event.get("classification"))
        for event in events.values()
        if event.get("classification")
    )
    return {
        "policy": DEFINEDNESS_POLICY,
        "checks": len(events),
        "classification_counts": dict(sorted(counts.items())),
        "rejected_witnesses": counts.get("both_ub_like", 0),
        "unknown_as_neq": counts.get("ub_status_unknown", 0),
        "events": sorted(
            events.values(),
            key=lambda event: (
                str(event.get("classification")),
                str(event.get("event_id")),
            ),
        ),
    }


def finalize_definedness_audit(result: dict[str, Any]) -> dict[str, Any]:
    result["definedness_policy"] = DEFINEDNESS_POLICY
    result["definedness_audit"] = collect_definedness_audit(result)
    result["conditional_eq"] = bool(
        result.get("verdict") == "EQ"
        and result["definedness_audit"]["rejected_witnesses"] > 0
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths-dir", type=Path, required=True)
    parser.add_argument("--ranking", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=SMT_TIMEOUT_MS)
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
    finalize_definedness_audit(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
