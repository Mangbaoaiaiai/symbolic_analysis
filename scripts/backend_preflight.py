#!/usr/bin/env python3
"""Conservative preflight checks before choosing a solver backend."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable

from z3 import (
    BitVec,
    FPSortRef,
    Solver,
    Z3_OP_FPA_TO_IEEE_BV,
    ExprRef,
    fpIsNaN,
    fpToFP,
    is_app,
    substitute,
)


@dataclass(frozen=True)
class BackendPreflight:
    supported: bool
    unsupported_operators: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class FPToIEEEBVTranslation:
    status: str
    assertions: tuple[ExprRef, ...]
    conversion_count: int
    unique_conversion_count: int
    proof_queries: tuple[dict[str, object], ...]
    reason: str
    exact_non_nan_inverse: bool


def preflight_bitwuzla(assertions: Iterable[ExprRef]) -> BackendPreflight:
    """Detect Z3-specific operators that cannot be sent as standard SMT.

    The check is intentionally narrow: an unsupported result permits an exact
    skip of a backend invocation, while a supported result does not promise
    that the backend will accept or solve every other expression.
    """
    unsupported: set[str] = set()
    seen: set[int] = set()

    def visit(expression: ExprRef) -> None:
        identifier = expression.get_id()
        if identifier in seen:
            return
        seen.add(identifier)
        if is_app(expression) and (
            expression.decl().kind() == Z3_OP_FPA_TO_IEEE_BV
        ):
            unsupported.add(str(expression.decl().name()))
        for child in expression.children():
            visit(child)

    for assertion in assertions:
        visit(assertion)
    names = tuple(sorted(unsupported))
    return BackendPreflight(
        supported=not names,
        unsupported_operators=names,
        reason=(
            "z3_specific_floating_point_to_ieee_bits"
            if names
            else ""
        ),
    )


def _collect_fp_to_ieee_bv(assertions: Iterable[ExprRef]) -> list[ExprRef]:
    nodes: list[ExprRef] = []
    seen: set[int] = set()

    def visit(expression: ExprRef) -> None:
        identifier = expression.get_id()
        if identifier in seen:
            return
        seen.add(identifier)
        if is_app(expression) and (
            expression.decl().kind() == Z3_OP_FPA_TO_IEEE_BV
        ):
            nodes.append(expression)
        for child in expression.children():
            visit(child)

    for assertion in assertions:
        visit(assertion)
    return nodes


def _contains_fp_to_ieee_bv(expression: ExprRef) -> bool:
    return bool(_collect_fp_to_ieee_bv((expression,)))


def translate_fp_to_ieee_bv(
    assertions: Iterable[ExprRef],
    *,
    proof_timeout_ms: int = 5_000,
) -> FPToIEEEBVTranslation:
    """Bridge Z3's FP-to-bits extension when each value is provably non-NaN.

    For non-NaN IEEE-754 values, ``to_fp`` from the bit-vector sort is the
    exact inverse of ``fp.to_ieee_bv``.  The translation introduces one fresh
    bit-vector per conversion and constrains it through that inverse relation.
    A possible NaN leaves the query unchanged because bit-vector to FP
    reconstruction does not preserve NaN payload identity in this theory.
    """
    original = tuple(assertions)
    conversions = _collect_fp_to_ieee_bv(original)
    if not conversions:
        return FPToIEEEBVTranslation(
            status="not_applicable",
            assertions=original,
            conversion_count=0,
            unique_conversion_count=0,
            proof_queries=(),
            reason="no_fp_to_ieee_bv",
            exact_non_nan_inverse=False,
        )

    proofs: list[dict[str, object]] = []
    all_non_nan = True
    unknown_proof = False
    extension_free_assertions = tuple(
        assertion
        for assertion in original
        if not _contains_fp_to_ieee_bv(assertion)
    )
    for index, conversion in enumerate(conversions):
        argument = conversion.arg(0)
        for proof_kind, proof_assertions in (
            ("with_extension", original),
            ("extension_free_weaker_formula", extension_free_assertions),
        ):
            proof = Solver(ctx=argument.ctx)
            proof.set("timeout", max(1, int(proof_timeout_ms)))
            proof.add(*proof_assertions)
            proof.add(fpIsNaN(argument, ctx=argument.ctx))
            proof_started = time.perf_counter()
            status = str(proof.check())
            proofs.append(
                {
                    "index": index,
                    "status": status,
                    "elapsed_seconds": time.perf_counter() - proof_started,
                    "argument_sort": str(argument.sort()),
                    "claim": "not_fp_is_nan",
                    "proof_kind": proof_kind,
                }
            )
            if status == "sat":
                all_non_nan = False
                break
            if status != "unsat":
                unknown_proof = True
                all_non_nan = False
                break
        if not all_non_nan:
            break

    if not all_non_nan:
        return FPToIEEEBVTranslation(
            status=(
                "proof_unknown" if unknown_proof else "possible_nan"
            ),
            assertions=original,
            conversion_count=len(conversions),
            unique_conversion_count=len(conversions),
            proof_queries=tuple(proofs),
            reason=(
                "non_nan_premise_not_proved"
                if unknown_proof
                else "fp_to_ieee_bv_argument_may_be_nan"
            ),
            exact_non_nan_inverse=False,
        )

    translated = list(original)
    inverse_constraints: list[ExprRef] = []
    replacements: list[tuple[ExprRef, ExprRef]] = []
    for index, conversion in enumerate(conversions):
        argument = conversion.arg(0)
        sort = argument.sort()
        if not isinstance(sort, FPSortRef):
            return FPToIEEEBVTranslation(
                status="unsupported_sort",
                assertions=original,
                conversion_count=len(conversions),
                unique_conversion_count=len(conversions),
                proof_queries=tuple(proofs),
                reason="fp_to_ieee_bv_argument_is_not_floating_point",
                exact_non_nan_inverse=False,
            )
        bits = int(sort.ebits() + sort.sbits())
        encoded = BitVec(
            f"__round017_fp_ieee_bits_{index}_{bits}",
            bits,
            ctx=argument.ctx,
        )
        inverse_constraints.append(
            argument == fpToFP(encoded, sort, ctx=argument.ctx)
        )
        replacements.append((conversion, encoded))

    for conversion, encoded in replacements:
        translated = [
            substitute(assertion, (conversion, encoded))
            for assertion in translated
        ]
    combined = tuple([*translated, *inverse_constraints])
    if _collect_fp_to_ieee_bv(combined):
        return FPToIEEEBVTranslation(
            status="unsupported_nested_conversion",
            assertions=original,
            conversion_count=len(conversions),
            unique_conversion_count=len(conversions),
            proof_queries=tuple(proofs),
            reason="nested_fp_to_ieee_bv_remained_after_translation",
            exact_non_nan_inverse=False,
        )
    return FPToIEEEBVTranslation(
        status="translated",
        assertions=combined,
        conversion_count=len(conversions),
        unique_conversion_count=len(conversions),
        proof_queries=tuple(proofs),
        reason="exact_inverse_on_proved_non_nan_values",
        exact_non_nan_inverse=True,
    )

