#!/usr/bin/env python3
"""Classify truncated loop states without treating lazy states as reachable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from z3 import Solver, get_version_string, sat, unsat, unknown


DEFAULT_FRONTIER_TIMEOUT_MS = 60_000
DEFAULT_FRONTIER_RANDOM_SEED = 0


@dataclass(frozen=True)
class FrontierRecord:
    index: int
    status: str
    reason: str
    timeout_ms: int

    def as_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "status": self.status,
            "reason": self.reason,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True)
class FrontierAudit:
    records: tuple[FrontierRecord, ...]
    timeout_ms: int

    @property
    def infeasible_count(self) -> int:
        return sum(record.status == "unsat" for record in self.records)

    @property
    def feasible_count(self) -> int:
        return sum(record.status == "sat" for record in self.records)

    @property
    def unknown_count(self) -> int:
        return sum(record.status == "unknown" for record in self.records)

    @property
    def not_checked_count(self) -> int:
        return sum(record.status == "not_checked" for record in self.records)

    @property
    def blocks_completeness(self) -> bool:
        return bool(
            self.feasible_count
            or self.unknown_count
            or self.not_checked_count
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "schema": "symbolicana.loop_frontier_audit.v1",
            "solver_backend": "z3",
            "solver_version": get_version_string(),
            "timeout_ms": self.timeout_ms,
            "random_seed": DEFAULT_FRONTIER_RANDOM_SEED,
            "state_count": len(self.records),
            "infeasible_count": self.infeasible_count,
            "feasible_count": self.feasible_count,
            "unknown_count": self.unknown_count,
            "not_checked_count": self.not_checked_count,
            "blocks_completeness": self.blocks_completeness,
            "records": [record.as_json() for record in self.records],
        }


def classify_smt_frontiers(
    queries: list[str],
    *,
    timeout_ms: int = DEFAULT_FRONTIER_TIMEOUT_MS,
    stop_on_blocking: bool = False,
) -> FrontierAudit:
    """Prove individual frontier formulas infeasible where possible.

    Only UNSAT removes a frontier from completeness accounting. SAT and every
    parse/solver/unknown result remain blocking.
    """
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    records = []
    blocking_seen = False
    for index, query in enumerate(queries, 1):
        if blocking_seen and stop_on_blocking:
            records.append(
                FrontierRecord(
                    index=index,
                    status="not_checked",
                    reason="blocked_by_prior_frontier",
                    timeout_ms=timeout_ms,
                )
            )
            continue
        if not query.strip():
            records.append(
                FrontierRecord(
                    index=index,
                    status="unknown",
                    reason="empty_query",
                    timeout_ms=timeout_ms,
                )
            )
            blocking_seen = True
            continue
        solver = Solver()
        solver.set(
            timeout=timeout_ms,
            random_seed=DEFAULT_FRONTIER_RANDOM_SEED,
        )
        try:
            solver.from_string(query)
            status = solver.check()
        except Exception as exc:
            records.append(
                FrontierRecord(
                    index=index,
                    status="unknown",
                    reason=f"query_error:{type(exc).__name__}",
                    timeout_ms=timeout_ms,
                )
            )
            blocking_seen = True
            continue
        if status == unsat:
            status_text = "unsat"
            reason = "frontier_infeasible"
        elif status == sat:
            status_text = "sat"
            reason = "frontier_feasible"
        elif status == unknown:
            status_text = "unknown"
            reason = str(solver.reason_unknown() or "solver_unknown")
        else:
            status_text = "unknown"
            reason = "unexpected_solver_status"
        records.append(
            FrontierRecord(
                index=index,
                status=status_text,
                reason=reason,
                timeout_ms=timeout_ms,
            )
        )
        if status_text in {"sat", "unknown"}:
            blocking_seen = True
    return FrontierAudit(records=tuple(records), timeout_ms=timeout_ms)
