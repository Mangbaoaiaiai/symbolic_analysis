"""Single source of defaults for the paper experiment profile."""

from __future__ import annotations

from typing import Any


PROFILE_SCHEMA = "symbolicana.experiment_profile.v1"
PAPER_PROFILE_ID = "paper.v3-20261020"
OSF_PROFILE_ID = "osf.full-input.staged.v1-20261021"

HYBRID_TOP1_THRESHOLD = 0.70
HYBRID_MARGIN_THRESHOLD = 0.05
LOOP_BOUND = 30
SYMBOLIC_EXECUTION_TIMEOUT_SECONDS = 600
SMT_TIMEOUT_MS = 60_000
RANKING_TRUTH_TIMEOUT_MS = 2_000
VERIFIER_WALL_TIMEOUT_SECONDS = 300
MAX_PATHS = 128
DEFAULT_INT_MIN = -100
DEFAULT_INT_MAX = 100
DEFAULT_FLOAT_MIN = -100.0
DEFAULT_FLOAT_MAX = 100.0
FULL_INPUT_SPACE = "full_representable_input_space"

SEMANTIC_CONTRACT = {
    "id": "Ret+GS+Out.v1",
    "components": [
        "input_space_equivalence",
        "function_return_value_equivalence",
        "program_output_equivalence",
        "globally_observable_memory_state_equivalence",
    ],
    "output_ordering": "stdio_call_order",
    "supported_output_sinks": ["stdout", "stdio"],
    "supported_output_calls": [
        "printf",
        "fprintf",
        "puts",
        "fputs",
        "putchar",
        "putc",
        "fputc",
    ],
    "unsupported_external_io": [
        "files",
        "network",
        "arbitrary device I/O",
        "observable timing",
    ],
    "global_state_replay": "not_implemented_this_round",
}


def paper_profile() -> dict[str, Any]:
    return {
        "schema": PROFILE_SCHEMA,
        "id": PAPER_PROFILE_ID,
        "hybrid": {
            "theta_pc": HYBRID_TOP1_THRESHOLD,
            "delta_pc": HYBRID_MARGIN_THRESHOLD,
        },
        "symbolic_execution": {
            "loop_bound": LOOP_BOUND,
            "timeout_seconds": SYMBOLIC_EXECUTION_TIMEOUT_SECONDS,
            "max_paths": MAX_PATHS,
            "integer_domain": [DEFAULT_INT_MIN, DEFAULT_INT_MAX],
            "floating_point_domain": [DEFAULT_FLOAT_MIN, DEFAULT_FLOAT_MAX],
        },
        "smt": {
            "timeout_ms": SMT_TIMEOUT_MS,
            "ranking_truth_timeout_ms": RANKING_TRUTH_TIMEOUT_MS,
            "verifier_wall_timeout_seconds": VERIFIER_WALL_TIMEOUT_SECONDS,
        },
        "semantic_contract": dict(SEMANTIC_CONTRACT),
    }


def profile_with_overrides(**overrides: Any) -> dict[str, Any]:
    profile = paper_profile()
    for key, value in overrides.items():
        if value is not None:
            profile[key] = value
    return profile


def _record_domain(minimum: int | float | None, maximum: int | float | None):
    if minimum is None and maximum is None:
        return FULL_INPUT_SPACE
    if minimum is None or maximum is None:
        raise ValueError("input domain bounds must be supplied together")
    return [minimum, maximum]


def profile_for_input_domains(
    int_min: int | None,
    int_max: int | None,
    float_min: float | None,
    float_max: float | None,
    *,
    loop_bound: int | None = None,
    max_paths: int | None = None,
    timeout_seconds: int | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Record the exact input space used by one experiment run."""
    profile = paper_profile()
    if profile_id is not None:
        profile["id"] = profile_id
    profile["symbolic_execution"]["integer_domain"] = _record_domain(
        int_min, int_max
    )
    profile["symbolic_execution"]["floating_point_domain"] = _record_domain(
        float_min, float_max
    )
    if loop_bound is not None:
        profile["symbolic_execution"]["loop_bound"] = loop_bound
    if max_paths is not None:
        profile["symbolic_execution"]["max_paths"] = max_paths
    if timeout_seconds is not None:
        profile["symbolic_execution"]["timeout_seconds"] = timeout_seconds
    return profile
