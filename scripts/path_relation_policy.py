#!/usr/bin/env python3
"""Pure policy decisions for one source/target path relation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PathRelationDecision:
    status: str
    equivalent_on_overlap: bool | None
    coverage_obligation_vacuous: bool
    may_confirm_program_neq: bool
    may_support_program_eq: bool
    reason: str


@dataclass(frozen=True)
class SourceFeasibilityDecision:
    status: str
    skip_remaining_candidates: bool
    coverage_obligation_vacuous: bool
    count_unknown: bool
    reason: str


def classify_source_feasibility(
    feasibility_status: str | None,
) -> SourceFeasibilityDecision:
    """Classify one configured-domain source feasibility query."""
    normalized = str(feasibility_status or "").casefold()
    if normalized == "unsat":
        return SourceFeasibilityDecision(
            status="vacuous_source",
            skip_remaining_candidates=True,
            coverage_obligation_vacuous=True,
            count_unknown=False,
            reason="source_unsat_under_input_domain",
        )
    if normalized == "sat":
        return SourceFeasibilityDecision(
            status="source_feasible",
            skip_remaining_candidates=False,
            coverage_obligation_vacuous=False,
            count_unknown=False,
            reason="source_sat_under_input_domain",
        )
    if normalized in {"unknown", "timeout"}:
        return SourceFeasibilityDecision(
            status="source_feasibility_unknown",
            skip_remaining_candidates=False,
            coverage_obligation_vacuous=False,
            count_unknown=True,
            reason=f"source_feasibility_{normalized}",
        )
    return SourceFeasibilityDecision(
        status="source_feasibility_invalid",
        skip_remaining_candidates=False,
        coverage_obligation_vacuous=False,
        count_unknown=True,
        reason=(
            "missing_source_feasibility_result"
            if not normalized
            else f"unexpected_source_feasibility_status:{feasibility_status}"
        ),
    )


def classify_path_relation(
    *,
    overlap_status: str,
    source_feasible: bool | None = None,
    semantic_status: bool | None = None,
    replay_confirmed: bool = False,
) -> PathRelationDecision:
    """Classify one relation without promoting it to a program verdict."""
    normalized = overlap_status.casefold()
    if normalized == "unsat":
        return PathRelationDecision(
            status="vacuous_intersection",
            equivalent_on_overlap=True,
            coverage_obligation_vacuous=True,
            may_confirm_program_neq=False,
            may_support_program_eq=False,
            reason="no_input_in_source_target_intersection",
        )
    if source_feasible is False and normalized in {"sat", "unknown"}:
        return PathRelationDecision(
            status="vacuous_source",
            equivalent_on_overlap=True,
            coverage_obligation_vacuous=True,
            may_confirm_program_neq=False,
            may_support_program_eq=False,
            reason="source_path_unsat",
        )
    if normalized == "unknown" or source_feasible is None:
        return PathRelationDecision(
            status="unknown",
            equivalent_on_overlap=None,
            coverage_obligation_vacuous=False,
            may_confirm_program_neq=False,
            may_support_program_eq=False,
            reason="overlap_or_source_feasibility_unknown",
        )
    if normalized != "sat":
        return PathRelationDecision(
            status="invalid_status",
            equivalent_on_overlap=None,
            coverage_obligation_vacuous=False,
            may_confirm_program_neq=False,
            may_support_program_eq=False,
            reason=f"unexpected_overlap_status:{overlap_status}",
        )
    if semantic_status is True:
        return PathRelationDecision(
            status="equivalent_on_overlap",
            equivalent_on_overlap=True,
            coverage_obligation_vacuous=False,
            may_confirm_program_neq=False,
            may_support_program_eq=True,
            reason="semantic_equivalence_proved",
        )
    if semantic_status is False and replay_confirmed:
        return PathRelationDecision(
            status="confirmed_neq",
            equivalent_on_overlap=False,
            coverage_obligation_vacuous=False,
            may_confirm_program_neq=True,
            may_support_program_eq=False,
            reason="model_replayed_with_observable_difference",
        )
    return PathRelationDecision(
        status="unresolved_semantics",
        equivalent_on_overlap=None,
        coverage_obligation_vacuous=False,
        may_confirm_program_neq=False,
        may_support_program_eq=False,
        reason=(
            "semantic_unknown"
            if semantic_status is None
            else "semantic_difference_not_replayed"
        ),
    )

