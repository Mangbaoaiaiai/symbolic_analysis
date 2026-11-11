#!/usr/bin/env python3
"""Shared Round017 external-function model and ABI qualification rules."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Iterable


SCHEMA = "symbolicana.round017.semantic_model_audit.v1"


RUNTIME_BOOTSTRAP_SYMBOLS = frozenset(
    {
        "__cxa_finalize",
        "__gmon_start__",
        "__libc_start_main",
        "_ITM_deregisterTMCloneTable",
        "_ITM_registerTMCloneTable",
    }
)


IO_MODEL_RULES: dict[str, dict[str, str]] = {
    name: {
        "category": "io",
        "model_status": "instrumented_io_hook",
        "model_kind": "symbolic input or observable-output hook",
        "abi_prototype": prototype,
        "eq_permission": "instrumented",
        "neq_permission": "instrumented",
        "reason": "I/O is represented by the input schema and ordered output events",
    }
    for name, prototype in {
        "scanf": "int scanf(const char *format, ...)",
        "__isoc99_scanf": "int __isoc99_scanf(const char *format, ...)",
        "__isoc23_scanf": "int __isoc23_scanf(const char *format, ...)",
        "__scanf_chk": "int __scanf_chk(const char *format, ...)",
        "printf": "int printf(const char *format, ...)",
        "__printf_chk": "int __printf_chk(int flag, const char *format, ...)",
        "fprintf": "int fprintf(void *stream, const char *format, ...)",
        "__fprintf_chk": "int __fprintf_chk(void *stream, int flag, const char *format, ...)",
        "puts": "int puts(const char *string)",
        "fputs": "int fputs(const char *string, void *stream)",
        "putchar": "int putchar(int character)",
        "putc": "int putc(int character, void *stream)",
        "fputc": "int fputc(int character, void *stream)",
        "fflush": "int fflush(void *stream)",
    }.items()
}


EXACT_MODEL_RULES: dict[str, dict[str, str]] = {
    "sqrt": {
        "category": "math",
        "model_status": "modeled_ieee754",
        "model_kind": "SqrtSymbolicHook/claripy.fpSqrt",
        "abi_prototype": "double sqrt(double)",
        "eq_permission": "conditional",
        "neq_permission": "replay_required",
        "reason": (
            "correctly rounded IEEE-754 sqrt model; EQ additionally requires "
            "every reached call argument to be provably nonnegative and no "
            "errno/fenv observation"
        ),
    },
    "sqrtf": {
        "category": "math",
        "model_status": "modeled_ieee754",
        "model_kind": "SqrtSymbolicHook/claripy.fpSqrt",
        "abi_prototype": "float sqrtf(float)",
        "eq_permission": "conditional",
        "neq_permission": "replay_required",
        "reason": (
            "correctly rounded IEEE-754 binary32 sqrt model; EQ additionally "
            "requires every reached call argument to be provably nonnegative "
            "and no errno/fenv observation"
        ),
    },
    "__sqrt_finite": {
        "category": "math",
        "model_status": "modeled_ieee754",
        "model_kind": "SqrtSymbolicHook/claripy.fpSqrt",
        "abi_prototype": "double __sqrt_finite(double)",
        "eq_permission": "conditional",
        "neq_permission": "replay_required",
        "reason": (
            "double finite-sqrt ABI; EQ additionally requires every reached "
            "call argument to be provably nonnegative and no errno/fenv "
            "observation"
        ),
    },
}


UNCONSTRAINED_RETURN_FUNCTIONS = frozenset(
    {
        "exp",
        "expf",
        "log",
        "logf",
        "pow",
        "powf",
        "sin",
        "sinf",
        "cos",
        "cosf",
        "tan",
        "tanf",
        "asin",
        "asinf",
        "acos",
        "acosf",
        "atan",
        "atanf",
        "atan2",
        "atan2f",
        "sinh",
        "cosh",
        "tanh",
        "expm1",
        "expm1f",
        "log1p",
        "log1pf",
        "log2",
        "log2f",
        "log10",
        "log10f",
        "cbrt",
        "cbrtf",
    }
)


BINARY_AUDIT_REQUIRED_FUNCTIONS = frozenset(
    {
        "fabs",
        "fabsf",
        "floor",
        "floorf",
        "ceil",
        "ceilf",
        "abs",
        "labs",
        "fmin",
        "fminf",
        "fmax",
        "fmaxf",
        "copysign",
        "copysignf",
        "nearbyint",
        "rint",
    }
)


UNCLASSIFIED_HELPERS = frozenset(
    {
        "longBitsToDoubleC",
        "doubleToRawLongBits",
        "erf",
        "erff",
        "erfc",
        "erfcf",
    }
)


FENV_OBSERVATION_FUNCTIONS = frozenset(
    {
        "__errno_location",
        "feclearexcept",
        "fegetexceptflag",
        "feraiseexcept",
        "fesetexceptflag",
        "fetestexcept",
        "fegetround",
        "fesetround",
        "fegetenv",
        "feholdexcept",
        "fesetenv",
        "feupdateenv",
    }
)


SOURCE_MODEL_RULES: dict[str, dict[str, str]] = {
    **EXACT_MODEL_RULES,
    **{
        name: {
            "category": "transcendental",
            "model_status": "unconstrained_external_return",
            "model_kind": "angr unresolved external default",
            "eq_permission": "prohibited",
            "neq_permission": "replay_required",
            "reason": (
                "return value is not tied to the call arguments; concrete "
                "difference must be replayed"
            ),
        }
        for name in sorted(UNCONSTRAINED_RETURN_FUNCTIONS)
    },
    **{
        name: {
            "category": "intrinsic_or_library",
            "model_status": "requires_binary_symbol_audit",
            "model_kind": "hardware instruction or unresolved libc",
            "eq_permission": "blocked_pending_binary_audit",
            "neq_permission": "replay_required",
            "reason": "source spelling does not determine compiled implementation",
        }
        for name in sorted(BINARY_AUDIT_REQUIRED_FUNCTIONS)
    },
    **{
        name: {
            "category": "external_helper",
            "model_status": "unclassified_external_helper",
            "model_kind": "no registered Round017 model",
            "eq_permission": "prohibited",
            "neq_permission": "replay_required",
            "reason": "helper definition/link identity must be audited",
        }
        for name in sorted(UNCLASSIFIED_HELPERS)
    },
    **IO_MODEL_RULES,
}


_VERSION_SUFFIX = re.compile(r"@+[A-Za-z0-9_.]+$")


def symbol_base_name(symbol: str) -> str:
    """Return a linker symbol's unversioned spelling."""
    return _VERSION_SUFFIX.sub("", str(symbol).strip())


def _canonical(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def model_rule(symbol: str) -> dict[str, str]:
    """Classify an imported or source-level external symbol."""
    raw = str(symbol)
    name = symbol_base_name(raw)
    if name in RUNTIME_BOOTSTRAP_SYMBOLS:
        return {
            "function": name,
            "category": "runtime_bootstrap",
            "model_status": "outside_entry_observation",
            "model_kind": "loader/compiler startup support",
            "abi_prototype": "",
            "eq_permission": "outside_observed_entry",
            "neq_permission": "outside_observed_entry",
            "reason": (
                "symbol belongs to process startup/finalization and is outside "
                "the frozen entry-to-observation analysis scope"
            ),
        }
    if name in SOURCE_MODEL_RULES:
        return {"function": name, **SOURCE_MODEL_RULES[name]}
    return {
        "function": name,
        "category": "unclassified_external",
        "model_status": "unclassified_external_function",
        "model_kind": "no registered Round017 binary model",
        "abi_prototype": "",
        "eq_permission": "prohibited",
        "neq_permission": "replay_and_model_audit_required",
        "reason": "binary import has no qualified Round017 semantic model",
    }


def source_rule(symbol: str) -> dict[str, str] | None:
    """Return the source-level rule used by the inventory generator."""
    name = symbol_base_name(symbol)
    if name not in SOURCE_MODEL_RULES:
        return None
    return {"function": name, **SOURCE_MODEL_RULES[name]}


def normalize_imports(imports: Iterable[str]) -> list[str]:
    return sorted({str(item) for item in imports if str(item)})


def audit_binary_imports(
    imports: Iterable[str],
    *,
    source: str = "binary_dynamic_imports",
) -> dict[str, Any]:
    """Audit imported symbols before any runtime model-use evidence exists."""
    normalized = normalize_imports(imports)
    records = [model_rule(symbol) for symbol in normalized]
    fenv_symbols = sorted(
        {
            record["function"]
            for record in records
            if record["function"] in FENV_OBSERVATION_FUNCTIONS
        }
    )
    blockers: list[str] = []
    runtime_obligations: list[str] = []
    for record in records:
        symbol = record["function"]
        permission = record["eq_permission"]
        if permission in {
            "prohibited",
            "blocked_pending_binary_audit",
        }:
            blockers.append(f"unqualified_external_model:{symbol}")
        elif permission == "conditional":
            runtime_obligations.append(symbol)
    if fenv_symbols:
        blockers.append(
            "floating_point_environment_observable:"
            + ",".join(fenv_symbols)
        )
    payload = {
        "schema": SCHEMA,
        "source": source,
        "imports": records,
        "fenv_observation_symbols": fenv_symbols,
        "runtime_obligations": sorted(set(runtime_obligations)),
        "runtime_evidence_complete": False,
        "runtime_uses": [],
        "eq_blockers": blockers,
        "eq_eligible": False,
        "neq_gate": "current_static_candidate_and_binary_replay_required",
    }
    payload["audit_hash"] = hashlib.sha256(
        _canonical(payload).encode("utf-8")
    ).hexdigest()
    return payload


def finalize_runtime_audit(
    base_audit: dict[str, Any],
    runtime_uses: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Apply per-call sqrt obligations and produce the verifier-facing audit."""
    payload = json.loads(_canonical(base_audit))
    uses = [dict(item) for item in runtime_uses]
    blockers = list(payload.get("eq_blockers") or [])
    for use in uses:
        function = str(use.get("function") or "")
        if function not in EXACT_MODEL_RULES:
            blockers.append(f"unqualified_runtime_model_use:{function}")
            continue
        if use.get("argument_nonnegative") is not True:
            blockers.append(
                f"sqrt_argument_not_proved_nonnegative:{function}"
            )
    deduplicated_uses: dict[str, dict[str, Any]] = {}
    for use in uses:
        key = _canonical(use)
        deduplicated_uses[key] = use
    payload["runtime_uses"] = [
        deduplicated_uses[key] for key in sorted(deduplicated_uses)
    ]
    payload["runtime_evidence_complete"] = True
    payload["eq_blockers"] = sorted(set(blockers))
    payload["eq_eligible"] = not payload["eq_blockers"]
    status_counts = Counter(
        str(record.get("model_status") or "")
        for record in payload.get("imports") or []
    )
    payload["model_status_counts"] = dict(sorted(status_counts.items()))
    payload["audit_hash"] = hashlib.sha256(
        _canonical(payload).encode("utf-8")
    ).hexdigest()
    return payload


def validate_binary_model_audit(audit: Any) -> list[str]:
    """Validate the structural evidence needed to authorize an EQ verdict."""
    errors: list[str] = []
    if not isinstance(audit, dict):
        return ["semantic_model_audit_missing"]
    if audit.get("schema") != SCHEMA:
        errors.append("semantic_model_audit_schema_mismatch")
    if audit.get("runtime_evidence_complete") is not True:
        errors.append("semantic_model_runtime_evidence_incomplete")
    if not isinstance(audit.get("imports"), list):
        errors.append("semantic_model_imports_missing")
    if not isinstance(audit.get("runtime_uses"), list):
        errors.append("semantic_model_runtime_uses_missing")
    blockers = audit.get("eq_blockers")
    if "fixed_runtime" in audit:
        from fixed_math_runtime import validate_certificate, validate_use
        errors.extend(validate_certificate(audit["fixed_runtime"]))
        for use in audit.get("runtime_uses") or []:
            errors.extend(validate_use(use, audit["fixed_runtime"]))
    if not isinstance(blockers, list):
        errors.append("semantic_model_blockers_missing")
    if audit.get("eq_eligible") is True and errors:
        errors.append("semantic_model_claims_eligibility_with_invalid_evidence")
    return errors


def combined_eq_audit(audits: Iterable[dict[str, Any] | None]) -> dict[str, Any]:
    """Combine both sides without allowing one side to upgrade the other."""
    valid_audits: list[dict[str, Any]] = []
    errors: list[str] = []
    blockers: list[str] = []
    replay_required_symbols: list[str] = []
    for side_index, audit in enumerate(audits):
        side = "old" if side_index == 0 else "new"
        side_errors = validate_binary_model_audit(audit)
        errors.extend(f"{side}:{error}" for error in side_errors)
        if isinstance(audit, dict):
            valid_audits.append(audit)
            for record in audit.get("imports") or []:
                if (
                    isinstance(record, dict)
                    and record.get("neq_permission")
                    in {
                        "replay_required",
                        "replay_and_model_audit_required",
                    }
                    and record.get("eq_permission")
                    in {
                        "prohibited",
                        "blocked_pending_binary_audit",
                        "conditional",
                    }
                ):
                    replay_required_symbols.append(
                        f"{side}:{record.get('function')}"
                    )
            blockers.extend(
                f"{side}:{item}" for item in (audit.get("eq_blockers") or [])
            )
            if audit.get("eq_eligible") is not True:
                blockers.append(f"{side}:semantic_model_not_eq_eligible")
        else:
            blockers.append(f"{side}:semantic_model_audit_missing")
    fixed = [a.get("fixed_runtime") for a in valid_audits]
    if any(fixed):
        if not all(fixed) or len(fixed) != 2:
            errors.append("fixed_runtime_mixed_or_missing_contract")
        elif fixed[0].get("environment_id") != fixed[1].get("environment_id"):
            errors.append("fixed_runtime_environment_mismatch")
    return {
        "schema": "symbolicana.round017.combined_semantic_model_audit.v1",
        "side_count": len(valid_audits),
        "validation_errors": sorted(set(errors)),
        "eq_blockers": sorted(set(blockers)),
        "eq_eligible": not errors and not blockers,
        "neq_replay_required_symbols": sorted(
            set(replay_required_symbols)
        ),
        "neq_requires_current_static_candidate_and_replay": bool(
            replay_required_symbols
        ),
    }
