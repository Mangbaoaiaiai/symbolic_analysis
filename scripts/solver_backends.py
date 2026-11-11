#!/usr/bin/env python3
"""Shared Z3/Bitwuzla backend strategies for verifier SMT calls."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import struct
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend_preflight import preflight_bitwuzla, translate_fp_to_ieee_bv
from z3 import (
    Context,
    Solver as Z3Solver,
    sat,
    unsat,
    unknown,
)


STRATEGIES = ("Z60", "B60", "B10Z50", "Z10B50")
DIVISION_ALIASES = {
    "bvsdiv_i": "bvsdiv",
    "bvudiv_i": "bvudiv",
    "bvsrem_i": "bvsrem",
    "bvurem_i": "bvurem",
    "bvsmod_i": "bvsmod",
}
INPUT_SYMBOL = re.compile(r"^(?:arg_|FP_arg_|scanf_)")

AuditCallback = Callable[
    ["BackendSolver", str, int, float, str, list[dict[str, Any]]],
    dict[str, Any] | None,
]

_active_strategy = "Z60"
_audit_callback: AuditCallback | None = None
_audit_all_queries = False
_stats: Counter[str] = Counter()


def configure_solver_strategy(
    strategy: str,
    *,
    audit_callback: AuditCallback | None = None,
    audit_all_queries: bool = False,
) -> None:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown solver strategy: {strategy}")
    global _active_strategy, _audit_callback, _audit_all_queries, _stats
    _active_strategy = strategy
    _audit_callback = audit_callback
    _audit_all_queries = audit_all_queries
    _stats = Counter()


def active_strategy() -> str:
    return _active_strategy


def solver_audit_summary() -> dict[str, Any]:
    return {
        "strategy": _active_strategy,
        "counts": dict(sorted(_stats.items())),
    }


def translate_z3_division_aliases(text: str) -> tuple[str, dict[str, Any]]:
    """Translate Z3's internal division aliases to standard SMT-LIB.

    Z3's ``*_i`` operators are the standard high-divisor-by-zero behavior.
    The alias/standard pairs are universally equivalent for bit-vectors.
    """
    translated = text
    aliases: dict[str, int] = {}
    for alias, standard in DIVISION_ALIASES.items():
        translated, count = re.subn(
            rf"(?<![A-Za-z0-9_.]){re.escape(alias)}(?![A-Za-z0-9_.])",
            standard,
            translated,
        )
        if count:
            aliases[alias] = count
    if not re.search(r"(?m)^\s*\(set-logic\b", translated):
        translated = "(set-logic ALL)\n" + translated
    return translated, {
        "applied": bool(aliases),
        "aliases": aliases,
        "set_logic_added": True,
    }


def _parse_bv_value(text: str, bits: int) -> int:
    text = text.strip()
    if text.startswith("#b"):
        return int(text[2:], 2)
    if text.startswith("#x"):
        return int(text[2:], 16)
    match = re.fullmatch(r"\(_\s+bv(\d+)\s+\d+\)", text)
    if match:
        return int(match.group(1))
    raise ValueError(f"unsupported BitVec model value: {text}")


def _fp_concrete(raw: int, exponent_bits: int, significand_bits: int) -> dict[str, Any]:
    bits = exponent_bits + significand_bits
    fraction_bits = significand_bits - 1
    exponent_mask = ((1 << exponent_bits) - 1) << fraction_bits
    exponent = (raw & exponent_mask) >> fraction_bits
    fraction = raw & ((1 << fraction_bits) - 1)
    if exponent == (1 << exponent_bits) - 1:
        number = math.nan if fraction else (
            -math.inf if raw >> (bits - 1) else math.inf
        )
    else:
        number = struct.unpack(
            ">f" if bits == 32 else ">d",
            raw.to_bytes(bits // 8, "big"),
        )[0]
    return {
        "kind": "float",
        "bits": bits,
        "value": number,
        "ieee_bits": raw,
    }


@dataclass
class BitwuzlaModel:
    values: dict[str, dict[str, Any] | None]

    def concrete_value(self, variable: Any) -> dict[str, Any] | None:
        name = variable.decl().name()
        return self.values.get(name)


@dataclass
class BitwuzlaRun:
    status: str
    elapsed_seconds: float
    model: BitwuzlaModel | None
    model_available: bool
    model_error: str
    parse_seconds: float
    solve_seconds: float
    extraction_seconds: float
    translation: dict[str, Any]
    error: str = ""


def _bitwuzla_model_values(
    parser: Any,
    solver: Any,
) -> tuple[dict[str, dict[str, Any] | None], str]:
    values: dict[str, dict[str, Any] | None] = {}
    errors: list[str] = []
    for declaration in parser.get_declared_funs():
        if not declaration.is_const():
            continue
        name = str(declaration.symbol())
        try:
            value = solver.get_value(declaration)
            sort_text = str(value.sort())
            bitvec = re.fullmatch(r"\(_\s+BitVec\s+(\d+)\)", sort_text)
            if bitvec:
                bits = int(bitvec.group(1))
                raw = _parse_bv_value(str(value), bits)
                signed = raw - (1 << bits) if raw >= (1 << (bits - 1)) else raw
                values[name] = {
                    "kind": "bitvec",
                    "bits": bits,
                    "value": signed,
                    "unsigned": raw,
                }
                continue
            floating = re.fullmatch(
                r"\(_\s+FloatingPoint\s+(\d+)\s+(\d+)\)",
                sort_text,
            )
            if floating:
                exponent_bits = int(floating.group(1))
                significand_bits = int(floating.group(2))
                parts = value.value()
                if not isinstance(parts, (list, tuple)) or len(parts) != 3:
                    raise ValueError(f"unsupported FP model value: {value}")
                raw = int("".join(str(part) for part in parts), 2)
                values[name] = _fp_concrete(
                    raw,
                    exponent_bits,
                    significand_bits,
                )
                continue
            values[name] = None
        except Exception as exc:  # noqa: BLE001
            values[name] = None
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
    input_errors = [
        error
        for error in errors
        if INPUT_SYMBOL.match(error.split(":", 1)[0])
    ]
    return values, ";".join(input_errors)


def run_bitwuzla(smt2: str, timeout_ms: int) -> BitwuzlaRun:
    start = time.perf_counter()
    translated, translation = translate_z3_division_aliases(smt2)
    parse_start = time.perf_counter()
    try:
        import bitwuzla

        options = bitwuzla.Options()
        options.set(bitwuzla.Option.PRODUCE_MODELS, True)
        options.set(bitwuzla.Option.TIME_LIMIT_PER, max(1, int(timeout_ms)))
        with tempfile.TemporaryDirectory(prefix="round014-bitwuzla-") as temp:
            query_path = Path(temp) / "query.smt2"
            query_path.write_text(translated, encoding="utf-8")
            parser = bitwuzla.Parser(
                bitwuzla.TermManager(),
                options,
                "smt2",
            )
            parser.parse(str(query_path), parse_only=True, parse_file=True)
        parse_seconds = time.perf_counter() - parse_start
        solve_start = time.perf_counter()
        solver = parser.bitwuzla()
        result = solver.check_sat()
        solve_seconds = time.perf_counter() - solve_start
        status = str(result).casefold()
        if status not in {"sat", "unsat", "unknown"}:
            status = "error"
    except Exception as exc:  # noqa: BLE001
        error_kind = (
            "unsupported"
            if type(exc).__name__ == "BitwuzlaException"
            else "adapter_missing"
            if isinstance(exc, ImportError)
            else "error"
        )
        return BitwuzlaRun(
            status=error_kind,
            elapsed_seconds=time.perf_counter() - start,
            model=None,
            model_available=False,
            model_error="",
            parse_seconds=time.perf_counter() - parse_start,
            solve_seconds=0.0,
            extraction_seconds=0.0,
            translation=translation,
            error=f"{type(exc).__name__}: {exc}",
        )

    model = None
    model_available = False
    model_error = ""
    extraction_seconds = 0.0
    if status == "sat":
        extraction_start = time.perf_counter()
        values, model_error = _bitwuzla_model_values(parser, solver)
        extraction_seconds = time.perf_counter() - extraction_start
        model = BitwuzlaModel(values)
        model_available = not model_error
    return BitwuzlaRun(
        status=status,
        elapsed_seconds=time.perf_counter() - start,
        model=model,
        model_available=model_available,
        model_error=model_error,
        parse_seconds=parse_seconds,
        solve_seconds=solve_seconds,
        extraction_seconds=extraction_seconds,
        translation=translation,
    )


def _stage_name() -> str:
    frame = inspect.currentframe()
    if frame is None or frame.f_back is None or frame.f_back.f_back is None:
        return "solver_check"
    caller = frame.f_back.f_back.f_code.co_name
    mapping = {
        "verify_path_pair": "return_value_overlap_equivalence",
        "verify_path_overlap": "path_overlap",
        "verify_semantic_path_relation": "semantic_input_overlap",
        "find_return_counterexample": "return_value_counterexample",
        "verify_return_smt_equivalence": "return_value_overlap_equivalence",
        "check_input_coverage": "input_coverage",
        "check_union_coverage": "union_coverage",
        "check_union_coverage_evidence": "global_input_space",
    }
    return mapping.get(caller, caller)


def _remaining_ms(deadline: float) -> int:
    return max(0, math.ceil((deadline - time.perf_counter()) * 1000))


class BackendSolver:
    """Small compatibility wrapper around Z3 with optional Bitwuzla routing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._z3 = Z3Solver(*args, **kwargs)
        # Explicit Z3 contexts are frequently local to one verification
        # function. Keep the context alive for at least as long as this
        # wrapper, and release the internal solver first in __del__.
        self._context_keepalive = self._z3.ctx
        self._strategy = _active_strategy
        self._timeout_ms = 30_000
        self._last_attempts: list[dict[str, Any]] = []
        self._last_backend_inputs: list[dict[str, Any]] = []
        self._last_selected_backend = ""
        self._last_reason_unknown = ""
        self._last_model: Any = None
        self._last_query_sha256 = ""
        self._last_backend_query_sha256 = ""
        self._cached_smt2: str | None = None
        self._source_query_text: str | None = None
        self._z3_source_query_text: str | None = None
        self.last_auto_audit_event: dict[str, Any] | None = None

    def __del__(self) -> None:
        """Destroy the Z3 solver while its explicit context is still alive."""
        try:
            self._z3 = None
        except BaseException:
            pass

    def set(self, key: str, value: Any) -> None:
        if key == "timeout":
            self._timeout_ms = max(1, int(value))
            return
        self._z3.set(key, value)

    def add(self, *args: Any) -> None:
        self._z3.add(*args)
        self._cached_smt2 = None
        self._source_query_text = None
        self._z3_source_query_text = None

    def from_string(self, text: str) -> None:
        translated, _ = translate_z3_division_aliases(text)
        self._z3.from_string(translated)
        self._cached_smt2 = None
        self._source_query_text = text
        self._z3_source_query_text = translated

    def assertions(self) -> list[Any]:
        return list(self._z3.assertions())

    def to_smt2(self) -> str:
        if self._cached_smt2 is None:
            self._cached_smt2 = self._z3.to_smt2()
        return self._cached_smt2

    def model(self) -> Any:
        return self._last_model

    def reason_unknown(self) -> str:
        return self._last_reason_unknown

    def statistics(self) -> str:
        return json.dumps(self._last_attempts, sort_keys=True)

    def last_attempts(self) -> list[dict[str, Any]]:
        return list(self._last_attempts)

    def last_backend_inputs(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._last_backend_inputs]

    def last_selected_backend(self) -> str:
        return self._last_selected_backend

    def _run_z3(
        self,
        budget_ms: int,
    ) -> tuple[str, float, Any, str, dict[str, Any]]:
        self._z3.set("timeout", max(1, int(budget_ms)))
        start = time.perf_counter()
        status = str(self._z3.check())
        elapsed = time.perf_counter() - start
        model = self._z3.model() if status == "sat" else None
        reason = "" if status in {"sat", "unsat"} else str(self._z3.reason_unknown())
        return status, elapsed, model, reason, {"reason": reason}

    def _run_bitwuzla(
        self,
        budget_ms: int,
        query_text: str,
    ) -> tuple[str, float, Any, str, dict[str, Any]]:
        query = query_text
        self._last_backend_query_sha256 = hashlib.sha256(
            query.encode("utf-8")
        ).hexdigest()
        run = run_bitwuzla(query, budget_ms)
        details = {
            "translation": run.translation,
            "parse_seconds": run.parse_seconds,
            "solve_seconds": run.solve_seconds,
            "extraction_seconds": run.extraction_seconds,
            "model_available": run.model_available,
            "model_error": run.model_error,
        }
        status = run.status
        if status == "sat" and not run.model_available:
            status = "unknown"
            details["reason"] = "model_extraction_failed"
        elif status == "unsupported":
            details["reason"] = "adapter_or_parser_unsupported"
        elif status == "error":
            details["reason"] = run.error
        elif status == "unknown":
            details["reason"] = "solver_unknown_or_timeout"
        return status, run.elapsed_seconds, run.model, run.error, details

    def check(self) -> Any:
        start = time.perf_counter()
        deadline = start + self._timeout_ms / 1000.0
        self.last_auto_audit_event = None
        self._last_attempts = []
        self._last_backend_inputs = []
        self._last_selected_backend = ""
        self._last_model = None
        self._last_reason_unknown = ""
        self._last_backend_query_sha256 = ""

        if self._strategy == "Z60":
            schedule = [("z3", self._timeout_ms)]
        elif self._strategy == "B60":
            schedule = [("bitwuzla", self._timeout_ms)]
        elif self._strategy == "B10Z50":
            schedule = [
                ("bitwuzla", min(10_000, self._timeout_ms)),
                ("z3", None),
            ]
        elif self._strategy == "Z10B50":
            schedule = [
                ("z3", min(10_000, self._timeout_ms)),
                ("bitwuzla", None),
            ]
        else:
            raise ValueError(f"unknown solver strategy: {self._strategy}")

        logical_query = self._source_query_text or self.to_smt2()
        bitwuzla_query = logical_query
        preflight_attempts: list[dict[str, Any]] = []
        scheduled_bitwuzla = [
            (backend, fixed_budget)
            for backend, fixed_budget in schedule
            if backend == "bitwuzla"
        ]
        fp_translation: dict[str, Any] | None = None
        if scheduled_bitwuzla:
            translation = translate_fp_to_ieee_bv(
                self._z3.assertions(),
                proof_timeout_ms=min(5_000, self._timeout_ms),
            )
            fp_translation = {
                "status": translation.status,
                "reason": translation.reason,
                "conversion_count": translation.conversion_count,
                "unique_conversion_count": translation.unique_conversion_count,
                "exact_non_nan_inverse": translation.exact_non_nan_inverse,
                "proof_queries": list(translation.proof_queries),
            }
            _stats[f"fp_bridge.{translation.status}"] += 1
            bitwuzla_assertions = translation.assertions
            if translation.status == "translated":
                translated_solver = Z3Solver(ctx=self._z3.ctx)
                translated_solver.add(*translation.assertions)
                bitwuzla_query = translated_solver.to_smt2()
            preflight = preflight_bitwuzla(bitwuzla_assertions)
            if not preflight.supported:
                schedule = [
                    item for item in schedule if item[0] != "bitwuzla"
                ]
                _, fixed_budget = scheduled_bitwuzla[0]
                bitwuzla_budget = (
                    self._timeout_ms
                    if fixed_budget is None
                    else min(self._timeout_ms, fixed_budget)
                )
                preflight_attempts.append(
                    {
                        "backend": "bitwuzla",
                        "status": "unsupported",
                        "budget_ms": bitwuzla_budget,
                        "elapsed_seconds": 0.0,
                        "reason": preflight.reason,
                        "unsupported_operators": list(
                            preflight.unsupported_operators
                        ),
                        "preflight": True,
                        "fp_translation": fp_translation,
                    }
                )

        self._last_query_sha256 = hashlib.sha256(
            logical_query.encode("utf-8")
        ).hexdigest()

        final_status = "unknown"
        for attempt in preflight_attempts:
            self._last_attempts.append(attempt)
            _stats["attempts.bitwuzla.unsupported"] += 1
            _stats["unresolved.bitwuzla.unsupported"] += 1
        if preflight_attempts:
            self._last_reason_unknown = str(
                preflight_attempts[0]["reason"]
            )
        for backend, fixed_budget in schedule:
            remaining = _remaining_ms(deadline)
            if remaining <= 0:
                break
            budget = remaining if fixed_budget is None else min(remaining, fixed_budget)
            if backend == "z3":
                z3_query = self._z3_source_query_text or logical_query
                self._last_backend_inputs.append(
                    {
                        "backend": "z3",
                        "invoked": True,
                        "transport": "python_api_assertions",
                        "logical_query": logical_query,
                        "backend_query": z3_query,
                        "logical_query_sha256": self._last_query_sha256,
                        "backend_query_sha256": hashlib.sha256(
                            z3_query.encode("utf-8")
                        ).hexdigest(),
                        "translation": {},
                    }
                )
                status, elapsed, model, reason, details = self._run_z3(budget)
            else:
                translated, translation = translate_z3_division_aliases(
                    bitwuzla_query
                )
                self._last_backend_inputs.append(
                    {
                        "backend": "bitwuzla",
                        "invoked": True,
                        "transport": "smt2_file",
                        "logical_query": logical_query,
                        "backend_query": translated,
                        "logical_query_sha256": self._last_query_sha256,
                        "backend_query_sha256": hashlib.sha256(
                            translated.encode("utf-8")
                        ).hexdigest(),
                        "translation": {
                            **translation,
                            "fp_to_ieee_bv": fp_translation,
                            "backend_logical_query": bitwuzla_query,
                        },
                    }
                )
                status, elapsed, model, reason, details = self._run_bitwuzla(
                    budget,
                    bitwuzla_query,
                )
            attempt = {
                "backend": backend,
                "status": status,
                "budget_ms": budget,
                "elapsed_seconds": elapsed,
                **details,
            }
            self._last_attempts.append(attempt)
            _stats[f"attempts.{backend}.{status}"] += 1
            if status in {"sat", "unsat"}:
                final_status = status
                self._last_model = model
                self._last_selected_backend = backend
                _stats[f"selected.{backend}.{status}"] += 1
                break
            self._last_reason_unknown = reason or status
            _stats[f"unresolved.{backend}.{status}"] += 1
            self._last_selected_backend = backend

        _stats[f"queries.{self._strategy}"] += 1
        if final_status == "unknown":
            _stats["final.unknown"] += 1

        elapsed = time.perf_counter() - start
        if _audit_all_queries and _audit_callback is not None:
            self.last_auto_audit_event = _audit_callback(
                self,
                _stage_name(),
                self._timeout_ms,
                elapsed,
                final_status,
                self.last_attempts(),
            )
        if final_status == "sat":
            return sat
        if final_status == "unsat":
            return unsat
        return unknown
