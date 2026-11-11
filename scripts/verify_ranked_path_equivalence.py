#!/usr/bin/env python3
"""Verify program equivalence by following a ranked path-pair queue."""

from __future__ import annotations

import ast
import argparse
import contextvars
import hashlib
import json
import math
import os
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
    FP,
    FPSort,
    FPNumRef,
    Not,
    Or,
    is_app,
    is_bv_value,
    is_fp_value,
    is_int_value,
    is_quantifier,
    fpToIEEEBV,
    parse_smt2_string,
    sat,
    Solver as Z3Solver,
    unsat,
)
from z3.z3util import get_vars

from solver_backends import (
    STRATEGIES,
    BackendSolver as Solver,
    active_strategy,
    configure_solver_strategy,
    solver_audit_summary,
)
from binary_identity import (
    ArtifactIdentityError,
    sha256_file as identity_sha256_file,
    validate_live_artifact_identity,
)
from static_counterexample_candidate import (
    CandidateSchemaError,
    SCHEMA as CANDIDATE_SCHEMA,
    canonical_json_hash as candidate_json_hash,
    canonicalize_path_identity,
    candidate_with_state,
    persist_candidate_checkpoint,
    public_candidate_value,
)
from program_counterexample import (
    classify_replay as classify_program_replay,
    replay_cached_witnesses,
    sha256_file,
)
from input_domain_contract import (
    build_contract,
    is_float_return_type,
    load_profile,
    semantic_schema_key,
    sha256_json,
    signature_return_type,
    symbol_matches_spec,
    validate_values,
    z3_domain_constraints,
)
from path_relation_policy import classify_source_feasibility
from benchmark_smt_path_union import extract_domain_expressions
from round017_semantic_models import combined_eq_audit
from smt_path_union import build_path_union_query

# Paper Section 4.1 uses 60 seconds for every path-pair SMT comparison.
RETURN_EQ_TIMEOUT_MS = 60_000
# A bounded, SMT-guided pre-scan only looks for a replayable NEQ witness.
# Failure to find one is non-authoritative and falls back to full coverage
# verification.
NEQ_PRESCAN_BUDGET_MS = 15_000
NEQ_PRESCAN_PAIR_TIMEOUT_MS = 2_000
SOURCE_FEASIBILITY_UNSAT_THRESHOLD = 2
SOURCE_FEASIBILITY_BULK_PRODUCT_THRESHOLD = 10_000
SOURCE_FEASIBILITY_BULK_FAILURE_THRESHOLD = 2
FLOAT_FORMAT_SPECIFIERS = frozenset("aAeEfFgG")
FLOAT_TYPE_NAMES = frozenset(
    {"float", "double", "float32", "float64", "f32", "f64", "binary32", "binary64"}
)
FLOAT_REPR_MARKERS = (
    "fpToIEEEBV",
    "fp.to_ieee_bv",
    "FPS(",
    "FPV(",
    "(_ to_fp ",
    "(_ +zero",
    "FloatingPoint",
)
FORBIDDEN_NEQ_DISCOVERY_SOURCES = frozenset(
    {
        "validated_counterexample_cache",
        "counterexample_only_standard_seed_replay",
        "standard_domain_seed_replay",
    }
)
UNRELIABLE_ADDRESS_REASONS = frozenset(
    {
        "lossy_address_concretization",
        "unverified_address_concretization",
        "outside_object_address_abstraction_present",
    }
)
UB_ONLY_REPLAY_CLASSIFICATIONS = frozenset(
    {
        "both_ub_candidate",
        "one_sided_ub_candidate",
    }
)

_SMT_AUDIT_DIR: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "symbolic_analysis_smt_audit_dir",
    default=None,
)
_SMT_AUDIT_EVENTS: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar(
        "symbolic_analysis_smt_audit_events",
        default=None,
    )
)
_SMT_AUDIT_SEQUENCE: contextvars.ContextVar[int] = contextvars.ContextVar(
    "symbolic_analysis_smt_audit_sequence",
    default=0,
)
_SMT_AUDIT_ALL_QUERIES: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "symbolic_analysis_smt_audit_all_queries",
    default=False,
)
_ACTIVE_INPUT_CONTRACT: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar(
        "symbolic_analysis_active_input_contract",
        default=None,
    )
)
_ACTIVE_RETURN_TYPE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "symbolic_analysis_active_return_type",
    default=None,
)
_ACTIVE_ARTIFACT_IDENTITY: contextvars.ContextVar[
    dict[str, Any] | None
] = contextvars.ContextVar(
    "symbolic_analysis_active_artifact_identity",
    default=None,
)
_ACTIVE_TASK_UID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "symbolic_analysis_active_task_uid",
    default="",
)
_ACTIVE_RELATION_CONTEXT: contextvars.ContextVar[
    dict[str, Any] | None
] = contextvars.ContextVar(
    "symbolic_analysis_active_relation_context",
    default=None,
)


_PROOF_QUERY_CONTEXT = contextvars.ContextVar("proof_query_context", default=None)


def proof_query_call(kind, scope_direction, source, targets, function, *args, **kwargs):
    """Attach ownership to actual query events, never to legacy counters."""
    token = _PROOF_QUERY_CONTEXT.set({
        "kind": kind, "direction": scope_direction, "source": source,
        "targets": list(targets),
    })
    try:
        return function(*args, **kwargs)
    finally:
        _PROOF_QUERY_CONTEXT.reset(token)


def configure_smt_audit(
    directory: Path | None,
    *,
    persist_all_queries: bool = False,
) -> None:
    """Start a per-verifier SMT evidence session."""
    _SMT_AUDIT_ALL_QUERIES.set(bool(persist_all_queries))
    if directory is None:
        _SMT_AUDIT_DIR.set(None)
        _SMT_AUDIT_EVENTS.set(None)
        _SMT_AUDIT_SEQUENCE.set(0)
        return
    directory.mkdir(parents=True, exist_ok=True)
    _SMT_AUDIT_DIR.set(directory)
    _SMT_AUDIT_EVENTS.set([])
    _SMT_AUDIT_SEQUENCE.set(0)


def evidence_session_directory(
    output_path: Path,
    attempt_uid: str | None,
) -> Path:
    base = output_path.parent / f"{output_path.stem}_smt_audit"
    if not attempt_uid:
        return base
    safe_attempt = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        attempt_uid,
    ).strip("_")
    return base / f"attempt_{safe_attempt or 'unknown'}"


def smt_audit_summary() -> dict[str, Any]:
    events = list(_SMT_AUDIT_EVENTS.get() or [])
    directory = _SMT_AUDIT_DIR.get()
    summary = {
        "directory": str(directory) if directory else None,
        "query_count": len(events),
        "unknown_count": sum(
            str(event.get("status")) not in {"sat", "unsat"} for event in events
        ),
    }
    if _SMT_AUDIT_ALL_QUERIES.get():
        summary["events_omitted_from_report"] = True
        summary["events"] = []
    else:
        summary["events"] = events
    return summary


def candidate_audit_summary() -> dict[str, Any]:
    audit_dir = _SMT_AUDIT_DIR.get()
    if audit_dir is None:
        return {
            "schema": "symbolicana.round018.candidate_audit_summary.v1",
            "directory": None,
            "candidate_count": 0,
            "status_counts": {},
            "query_kind_counts": {},
            "pending_count": 0,
            "candidates": [],
        }
    directory = (
        audit_dir.parent
        / f"{audit_dir.name.removesuffix('_smt_audit')}_candidates"
    )
    candidates = []
    if directory.is_dir():
        for path in sorted(directory.glob("cex-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            candidates.append(payload)
    status_counts = Counter(
        str(candidate.get("status") or "missing")
        for candidate in candidates
    )
    query_kind_counts = Counter(
        str(candidate.get("query_kind") or "missing")
        for candidate in candidates
    )
    return {
        "schema": "symbolicana.round018.candidate_audit_summary.v1",
        "directory": str(directory),
        "candidate_count": len(candidates),
        "status_counts": dict(sorted(status_counts.items())),
        "query_kind_counts": dict(sorted(query_kind_counts.items())),
        "pending_count": status_counts.get("pending", 0),
        "candidates": [
            {
                "candidate_id": candidate.get("candidate_id"),
                "status": candidate.get("status"),
                "reason": candidate.get("reason"),
                "query_kind": candidate.get("query_kind"),
                "direction": candidate.get("direction"),
                "old_path_id": candidate.get("old_path_id"),
                "new_path_id": candidate.get("new_path_id"),
                "logical_query_sha256": candidate.get(
                    "logical_query_sha256"
                ),
            }
            for candidate in candidates
        ],
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = 20
    for attempt in range(attempts):
        temporary = path.with_name(
            f".{path.name}.{time.time_ns()}.{attempt}.tmp"
        )
        temporary.write_text(text, encoding="utf-8")
        try:
            temporary.replace(path)
            return
        except PermissionError:
            try:
                temporary.unlink()
            except OSError:
                pass
            if attempt == attempts - 1:
                raise
            time.sleep(min(1.0, 0.02 * (2**attempt)))


def _update_existing_text(path: Path, text: str) -> None:
    """Update already-persisted metadata without replacing its inode."""
    attempts = 20
    for attempt in range(attempts):
        try:
            with path.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(min(1.0, 0.02 * (2**attempt)))


def _solver_query_text(solver: Solver) -> str:
    try:
        query = solver.to_smt2()
    except Exception:
        query = (
            "(set-logic ALL)\n"
            + "\n".join(str(assertion) for assertion in solver.assertions())
        )
    if not re.search(r"(?m)^\s*\(check-sat\)\s*$", query):
        query = query.rstrip() + "\n(check-sat)\n"
    return query if query.endswith("\n") else query + "\n"


def persist_smt_query(
    solver: Solver,
    *,
    stage: str,
    timeout_ms: int,
    elapsed: float,
    status: Any,
    path_ids: list[str] | None = None,
    details: dict[str, Any] | None = None,
    force: bool = False,
    query_text: str | None = None,
) -> dict[str, Any] | None:
    """Persist complete query evidence for SAT witnesses and unresolved results."""
    status_text = str(status)
    backend_inputs = getattr(solver, "last_backend_inputs", None)
    backend_records = (
        backend_inputs()
        if callable(backend_inputs)
        else []
    )
    selected_backend = (
        str(solver.last_selected_backend())
        if hasattr(solver, "last_selected_backend")
        else ""
    )
    selected_input = next(
        (
            record
            for record in reversed(backend_records)
            if record.get("backend") == selected_backend
        ),
        backend_records[-1] if backend_records else None,
    )
    if query_text is not None:
        query = query_text
    elif selected_input is not None:
        query = str(selected_input.get("logical_query") or "")
    else:
        query = _solver_query_text(solver)
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if _SMT_AUDIT_ALL_QUERIES.get():
        auto_event = getattr(solver, "last_auto_audit_event", None)
        if (
            isinstance(auto_event, dict)
            and getattr(solver, "_last_query_sha256", "") == query_hash
        ):
            auto_event["stage"] = stage or auto_event.get("stage")
            auto_event["path_ids"] = list(
                dict.fromkeys(
                    [
                        *(auto_event.get("path_ids") or []),
                        *(path_ids or []),
                    ]
                )
            )
            merged_details = dict(auto_event.get("details") or {})
            merged_details.update(details or {})
            auto_event["details"] = merged_details
            if _PROOF_QUERY_CONTEXT.get() is not None:
                auto_event["proof_context"] = dict(_PROOF_QUERY_CONTEXT.get())
            metadata_path = Path(str(auto_event["query_path"])).with_suffix(".json")
            _update_existing_text(
                metadata_path,
                json.dumps(auto_event, indent=2, sort_keys=True) + "\n",
            )
            return auto_event
    if not force and status_text in {"sat", "unsat"}:
        return None
    directory = _SMT_AUDIT_DIR.get()
    if directory is None:
        return None

    sequence = int(_SMT_AUDIT_SEQUENCE.get()) + 1
    _SMT_AUDIT_SEQUENCE.set(sequence)
    safe_stage = re.sub(r"[^A-Za-z0-9_.-]+", "_", stage).strip("_") or "query"
    stem = f"{sequence:05d}_{safe_stage}_{query_hash[:12]}"
    query_path = directory / f"{stem}.smt2"
    metadata_path = directory / f"{stem}.json"
    _atomic_write_text(query_path, query)
    backend_query_text = (
        str(selected_input.get("backend_query") or "")
        if selected_input is not None
        else query
    )
    backend_query_hash = hashlib.sha256(
        backend_query_text.encode("utf-8")
    ).hexdigest()
    backend_query_path = None
    if (
        selected_input is not None
        and backend_query_text != query
    ):
        backend_query_path = directory / f"{stem}.backend.smt2"
        _atomic_write_text(
            backend_query_path,
            backend_query_text,
        )

    reason_unknown = ""
    if status_text not in {"sat", "unsat"}:
        try:
            reason_unknown = str(solver.reason_unknown())
        except Exception as exc:
            reason_unknown = f"reason_unknown_unavailable:{type(exc).__name__}"

    attempts = (
        list(solver.last_attempts())
        if hasattr(solver, "last_attempts")
        else []
    )
    unused_attempts = list(enumerate(attempts))
    backend_rows: list[dict[str, Any]] = []
    for record in backend_records:
        match = next(
            (
                (attempt_index, attempt)
                for attempt_index, attempt in unused_attempts
                if attempt.get("backend") == record.get("backend")
            ),
            None,
        )
        attempt_index = None
        attempt: dict[str, Any] = {}
        if match is not None:
            attempt_index, attempt = match
            unused_attempts = [
                item for item in unused_attempts if item[0] != attempt_index
            ]
        fp_translation = (
            (record.get("translation") or {}).get("fp_to_ieee_bv") or {}
        )
        backend_rows.append(
            {
                "backend": record.get("backend"),
                "invoked": bool(record.get("invoked")),
                "attempt_index": attempt_index,
                "status": attempt.get("status"),
                "budget_ms": attempt.get("budget_ms"),
                "elapsed_seconds": attempt.get("elapsed_seconds"),
                "logical_query_sha256": hashlib.sha256(
                    str(record.get("logical_query") or "").encode("utf-8")
                ).hexdigest(),
                "backend_query_sha256": hashlib.sha256(
                    str(record.get("backend_query") or "").encode("utf-8")
                ).hexdigest(),
                "fp_translation_status": (
                    fp_translation.get("status") or "not_applicable"
                ),
                "fp_translation_reason": fp_translation.get("reason") or "",
                "reason_unknown": attempt.get("reason") or "",
            }
        )
    for attempt_index, attempt in unused_attempts:
        fp_translation = attempt.get("fp_translation") or {}
        backend_rows.append(
            {
                "backend": attempt.get("backend"),
                "invoked": False,
                "attempt_index": attempt_index,
                "status": attempt.get("status"),
                "budget_ms": attempt.get("budget_ms"),
                "elapsed_seconds": attempt.get("elapsed_seconds"),
                "logical_query_sha256": query_hash,
                "backend_query_sha256": None,
                "fp_translation_status": (
                    fp_translation.get("status") or "not_attempted"
                ),
                "fp_translation_reason": (
                    fp_translation.get("reason") or ""
                ),
                "reason_unknown": attempt.get("reason") or "",
                "preflight": bool(attempt.get("preflight")),
            }
        )
    backend_rows.sort(
        key=lambda row: (
            row.get("attempt_index") is None,
            int(row.get("attempt_index") or 0),
            str(row.get("backend") or ""),
        )
    )

    event: dict[str, Any] = {
        "proof_context": _PROOF_QUERY_CONTEXT.get(),
        "sequence": sequence,
        "stage": stage,
        "status": status_text,
        "reason_unknown": reason_unknown,
        "timeout_ms": int(timeout_ms),
        "elapsed_seconds": float(elapsed),
        "path_ids": list(path_ids or []),
        "query_path": str(query_path),
        "query_sha256": query_hash,
        "backend": selected_backend or None,
        "backend_query_sha256": backend_query_hash,
        "backend_query_bytes": len(backend_query_text.encode("utf-8")),
        "backend_query_path": (
            str(backend_query_path)
            if backend_query_path is not None
            else None
        ),
        "pre_invocation_backend_inputs": [
            {
                "backend": record.get("backend"),
                "invoked": bool(record.get("invoked")),
                "transport": record.get("transport"),
                "logical_query_sha256": hashlib.sha256(
                    str(record.get("logical_query") or "").encode(
                        "utf-8"
                    )
                ).hexdigest(),
                "backend_query_sha256": hashlib.sha256(
                    str(record.get("backend_query") or "").encode(
                        "utf-8"
                    )
                ).hexdigest(),
                "logical_query_bytes": len(
                    str(record.get("logical_query") or "").encode(
                        "utf-8"
                    )
                ),
                "backend_query_bytes": len(
                    str(record.get("backend_query") or "").encode(
                        "utf-8"
                    )
                ),
                "translation": record.get("translation") or {},
            }
            for record in backend_records
        ],
        "backend_rows": backend_rows,
        "statistics": (
            str(solver.statistics())
            if status_text not in {"sat", "unsat"}
            else ""
        ),
        "details": details or {},
    }
    _atomic_write_text(
        metadata_path,
        json.dumps(event, indent=2, sort_keys=True) + "\n",
    )
    events = _SMT_AUDIT_EVENTS.get()
    if events is not None:
        events.append(event)
    return event


def persist_backend_check(
    solver: Solver,
    stage: str,
    timeout_ms: int,
    elapsed: float,
    status: str,
    attempts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    return persist_smt_query(
        solver,
        stage=stage,
        timeout_ms=timeout_ms,
        elapsed=elapsed,
        status=status,
        details={
            "solver_strategy": active_strategy(),
            "solver_attempts": attempts,
        },
        force=True,
    )


def persist_confirmed_evidence(
    record: dict[str, Any],
    *,
    evidence_type: str,
) -> str | None:
    """Append a confirmed counterexample/domain witness before final reporting."""
    audit_dir = _SMT_AUDIT_DIR.get()
    if audit_dir is None:
        return None
    stem = audit_dir.name.removesuffix("_smt_audit")
    evidence_dir = audit_dir.parent / f"{stem}_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / "confirmed.jsonl"
    payload = {
        "recorded_at": time.time(),
        "evidence_type": evidence_type,
        "record": record,
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                public_candidate_value(payload),
                sort_keys=True,
            )
            + "\n"
        )
    return str(path)


def active_artifact_identity_hash() -> str:
    identity = _ACTIVE_ARTIFACT_IDENTITY.get() or {}
    return str(identity.get("artifact_identity_sha256") or "")


def active_input_contract_hash() -> str:
    contract = _ACTIVE_INPUT_CONTRACT.get()
    return candidate_json_hash(contract) if contract else ""


def attach_candidate_identity(
    record: dict[str, Any],
    *,
    query_kind: str,
    direction: str,
    logical_query_sha256: str | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    nested_checkpoint = {}
    counterexample_value = record.get("counterexample")
    if isinstance(counterexample_value, dict):
        value = counterexample_value.get("_candidate_checkpoint")
        if isinstance(value, dict):
            nested_checkpoint = value
    direct_checkpoint = record.get("_candidate_checkpoint")
    if isinstance(direct_checkpoint, dict):
        nested_checkpoint = direct_checkpoint
    candidate = canonicalize_path_identity(
        record,
        direction=direction,
        task_uid=_ACTIVE_TASK_UID.get(),
        query_kind=query_kind,
        evidence_source=str(record.get("counterexample_source") or query_kind),
        logical_query_sha256=logical_query_sha256
        or str(record.get("query_sha256") or ""),
        input_contract_hash=active_input_contract_hash(),
        artifact_identity_hash=active_artifact_identity_hash(),
        candidate_id=str(nested_checkpoint.get("candidate_id") or "") or None,
        dedupe_key=dedupe_key,
    )
    annotated = dict(record)
    annotated.update(
        {
            "candidate_schema": CANDIDATE_SCHEMA,
            "candidate_id": candidate["candidate_id"],
            "query_kind": candidate["query_kind"],
            "direction": candidate["direction"],
            "old_path_id": candidate["old_path_id"],
            "new_path_id": candidate["new_path_id"],
            "logical_query_sha256": candidate[
                "logical_query_sha256"
            ],
            "input_contract_hash": candidate["input_contract_hash"],
            "artifact_identity_hash": candidate[
                "artifact_identity_hash"
            ],
        }
    )
    return annotated


def persist_candidate_record(
    record: dict[str, Any],
    *,
    query_kind: str,
    direction: str,
    status: str,
    reason: str = "",
    logical_query_sha256: str | None = None,
    replay: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    annotated = attach_candidate_identity(
        record,
        query_kind=query_kind,
        direction=direction,
        logical_query_sha256=logical_query_sha256,
        dedupe_key=dedupe_key,
    )
    candidate = canonicalize_path_identity(
        annotated,
        direction=direction,
        task_uid=_ACTIVE_TASK_UID.get(),
        query_kind=query_kind,
        evidence_source=str(
            annotated.get("evidence_source")
            or annotated.get("counterexample_source")
            or query_kind
        ),
        logical_query_sha256=logical_query_sha256
        or str(annotated.get("logical_query_sha256") or ""),
        input_contract_hash=active_input_contract_hash(),
        artifact_identity_hash=active_artifact_identity_hash(),
        candidate_id=str(annotated["candidate_id"]),
        dedupe_key=dedupe_key,
    )
    candidate["counterexample"] = annotated.get("counterexample")
    candidate["input_schema"] = annotated.get("input_schema")
    candidate["mismatch_component"] = annotated.get("mismatch_component")
    candidate["query_path"] = annotated.get("query_path")
    terminal = candidate_with_state(
        candidate,
        status=status,
        reason=reason,
        replay=replay,
    )
    audit_dir = _SMT_AUDIT_DIR.get()
    if audit_dir is not None:
        persist_candidate_checkpoint(
            terminal,
            audit_dir.parent
            / f"{audit_dir.name.removesuffix('_smt_audit')}_candidates",
        )
    annotated["candidate_disposition"] = terminal["status"]
    annotated["candidate_disposition_reason"] = terminal["reason"]
    annotated["_candidate_checkpoint"] = terminal
    return annotated


def finalize_candidate_checkpoint(
    record: dict[str, Any],
    *,
    status: str,
    reason: str,
    replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checkpoint = record.get("_candidate_checkpoint")
    counterexample_value = record.get("counterexample")
    if (
        not isinstance(checkpoint, dict)
        and isinstance(counterexample_value, dict)
    ):
        checkpoint = counterexample_value.get("_candidate_checkpoint")
    if not isinstance(checkpoint, dict):
        return record
    terminal = candidate_with_state(
        checkpoint,
        status=status,
        reason=reason,
        replay=replay,
    )
    audit_dir = _SMT_AUDIT_DIR.get()
    if audit_dir is not None:
        persist_candidate_checkpoint(
            terminal,
            audit_dir.parent
            / f"{audit_dir.name.removesuffix('_smt_audit')}_candidates",
        )
    record["_candidate_checkpoint"] = terminal
    if (
        isinstance(counterexample_value, dict)
        and isinstance(
            counterexample_value.get("_candidate_checkpoint"),
            dict,
        )
    ):
        counterexample_value["_candidate_checkpoint"] = terminal
    record["candidate_disposition"] = status
    record["candidate_disposition_reason"] = reason
    return record


def persist_sat_counterexample_candidate(
    solver: Solver,
    *,
    stage: str,
    timeout_ms: int,
    elapsed_seconds: float,
    component: str,
    counterexample: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist a SAT model before any binary replay is attempted."""
    relation = _ACTIVE_RELATION_CONTEXT.get()
    if not isinstance(relation, dict):
        return None
    query_event = persist_smt_query(
        solver,
        stage=stage,
        timeout_ms=timeout_ms,
        elapsed=elapsed_seconds,
        status=sat,
        path_ids=[
            str(relation["source_path_id"]),
            str(relation["target_path_id"]),
        ],
        details={
            "candidate_component": component,
            "solver_strategy": active_strategy(),
        },
        force=True,
    )
    query_sha256 = (
        str(query_event.get("query_sha256") or "")
        if isinstance(query_event, dict)
        else ""
    )
    if counterexample is None:
        model = solver.model()
        variables = collect_variables(*solver.assertions())
        source_id = str(relation["source_path_id"])
        target_id = str(relation["target_path_id"])
        direction = str(relation.get("direction") or "old_to_new")
        active_identity = _ACTIVE_ARTIFACT_IDENTITY.get() or {}
        paths_dir_text = (
            (active_identity.get("old") or {}).get("paths_dir")
            if direction == "new_to_old"
            else (active_identity.get("new") or {}).get("paths_dir")
        )
        if paths_dir_text:
            specs = complete_input_specs_for_paths(
                Path(str(paths_dir_text)),
                Path(str(paths_dir_text)) / f"{source_id}.txt",
                Path(str(paths_dir_text)) / f"{target_id}.txt",
            )
        else:
            specs = ()
        inputs = complete_inputs_from_model(model, variables, specs)
        counterexample = {
            "inputs": inputs,
            "input_schema": [
                {
                    "name": name,
                    "kind": kind,
                    "bits": bits,
                    "precision": precision,
                }
                for name, kind, bits, precision in specs
            ],
            "input_schema_source": (
                "exploration_and_path_artifacts" if specs else "not_available"
            ),
            "source": "static_smt_model",
        }
    record = {
        "source": str(relation["source_path_id"]),
        "target": str(relation["target_path_id"]),
        "direction": str(relation.get("direction") or "old_to_new"),
        "counterexample": counterexample,
        "input_schema": counterexample.get("input_schema"),
        "counterexample_source": "static_smt_model",
        "query_path": query_event.get("query_path") if query_event else None,
        "query_sha256": query_sha256,
    }
    annotated = persist_candidate_record(
        record,
        query_kind=stage,
        direction=str(record["direction"]),
        status="indeterminate",
        reason="awaiting_binary_replay",
        logical_query_sha256=query_sha256,
        dedupe_key=component,
    )
    checkpoint = annotated.get("_candidate_checkpoint")
    if counterexample is not None and isinstance(checkpoint, dict):
        counterexample["_candidate_checkpoint"] = checkpoint
        counterexample["candidate_id"] = checkpoint["candidate_id"]
    return checkpoint if isinstance(checkpoint, dict) else None


def finalize_replay_candidate(
    counterexample: dict[str, Any] | None,
    replay: dict[str, Any] | None,
    *,
    accept_static_global_mismatch: bool = False,
) -> dict[str, Any] | None:
    """Attach a terminal candidate state after replay returns."""
    if not isinstance(counterexample, dict):
        return None
    checkpoint = counterexample.get("_candidate_checkpoint")
    if not isinstance(checkpoint, dict):
        return None
    replay_payload = replay or {}
    if replay_payload.get("confirmed") is True:
        status = "accepted"
        reason = str(replay_payload.get("reason") or "stable_replay")
    elif accept_static_global_mismatch:
        status = "accepted"
        reason = "static_global_mismatch_with_stable_defined_execution"
    elif str(replay_payload.get("reason") or "") in {
        "replay_input_outside_configured_domain",
        "replay_input_invalid",
        "completed_input_fails_static_query",
        "no_observable_output_diff",
    }:
        status = "rejected"
        reason = str(replay_payload.get("reason"))
    else:
        status = "indeterminate"
        reason = str(
            replay_payload.get("reason")
            or "replay_did_not_confirm_counterexample"
        )
    terminal = candidate_with_state(
        checkpoint,
        status=status,
        reason=reason,
        replay=replay_payload,
    )
    audit_dir = _SMT_AUDIT_DIR.get()
    if audit_dir is not None:
        persist_candidate_checkpoint(
            terminal,
            audit_dir.parent
            / f"{audit_dir.name.removesuffix('_smt_audit')}_candidates",
        )
    counterexample["_candidate_checkpoint"] = terminal
    counterexample["candidate_disposition"] = status
    counterexample["candidate_disposition_reason"] = reason
    return terminal


def is_float_observable(value: dict[str, Any]) -> bool:
    """Return whether metadata identifies a value as IEEE floating-point."""
    for key in ("value_type", "data_type", "kind", "type"):
        if str(value.get(key) or "").casefold() in FLOAT_TYPE_NAMES:
            return True
    specifier = str(value.get("specifier") or "")
    if len(specifier) >= 2 and specifier[0] == "%" and specifier[-1] in FLOAT_FORMAT_SPECIFIERS:
        return True
    text = f"{value.get('repr') or ''}\n{value.get('smt') or ''}"
    return any(marker in text for marker in FLOAT_REPR_MARKERS)


def return_values_are_float(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    """Resolve return-kind semantics using the explicit function ABI when present."""
    explicit_return_type = _ACTIVE_RETURN_TYPE.get()
    if explicit_return_type is not None:
        return is_float_return_type(explicit_return_type)
    return is_float_observable(left) and is_float_observable(right)


def ieee_float_bits_zero(value: Any, bits: int, ctx: Context):
    magnitude_mask = BitVecVal((1 << (bits - 1)) - 1, bits, ctx=ctx)
    return (value & magnitude_mask) == BitVecVal(0, bits, ctx=ctx)


def zero_sign_insensitive_float_neq(
    left: Any,
    right: Any,
    bits: int,
    ctx: Context,
):
    """Compare IEEE bit patterns while identifying +0 with -0."""
    equal = Or(
        left == right,
        And(
            ieee_float_bits_zero(left, bits, ctx),
            ieee_float_bits_zero(right, bits, ctx),
        ),
    )
    return Not(equal)


def float_text_token_is_zero(token: str) -> bool:
    try:
        value = float.fromhex(token) if "0x" in token.casefold() else float(token)
    except (OverflowError, ValueError):
        return False
    return value == 0.0


def normalize_numeric_signed_zero_text(text: str) -> str:
    """Normalize textual +0/-0 without relaxing any nonzero comparison."""
    pattern = re.compile(
        r"(?<![A-Za-z0-9_.])"
        r"[-+]?0"
        r"(?:x0(?:\.0*)?p[+-]?0|(?:\.0*)?(?:[eE][+-]?0+)?)"
        r"(?![A-Za-z0-9_.])",
        flags=re.IGNORECASE,
    )
    return pattern.sub("0", text)


def float_text_token_looks_float(token: str) -> bool:
    """Recognize textual floating-point shapes without widening BV semantics."""
    compact = token.strip().casefold()
    if compact in {"nan", "+nan", "-nan", "inf", "+inf", "-inf"}:
        return True
    return bool(
        re.fullmatch(
            r"[+-]?(?:"
            r"0x(?:[0-9a-f]+(?:\.[0-9a-f]*)?|\.[0-9a-f]+)p[+-]?\d+"
            r"|(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+"
            r"|\d+\.\d*[eE][+-]?\d+|\.\d+[eE][+-]?\d+)"
            r")",
            compact,
        )
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


def active_domain_constraints(formula: Any, ctx: Context) -> list[Any]:
    contract = _ACTIVE_INPUT_CONTRACT.get()
    if not contract:
        return []
    variables = get_vars(formula)
    by_name = {variable.decl().name(): variable for variable in variables}
    constraints = []
    for spec in contract.get("inputs") or []:
        if spec.get("bounds", {}).get("domain") == (
            "not_applicable_pointer_address"
        ):
            continue
        matches = [
            variable
            for name, variable in by_name.items()
            if symbol_matches_spec(name, spec)
        ]
        expected_kind = spec.get("kind")
        expected_bits = int(spec.get("bits", 0) or 0)
        for variable in matches:
            sort_text = str(variable.sort())
            expression = variable
            if expected_kind == "float":
                if "BitVec" in sort_text:
                    if not sort_text.endswith(f" {expected_bits})"):
                        continue
                    expression = variable.raw_to_fp()
                elif not (
                    "FloatingPoint" in sort_text
                    or "FPSort" in sort_text
                ):
                    continue
            else:
                if "FloatingPoint" in sort_text or "FPSort" in sort_text:
                    expression = variable.raw_to_bv()
                elif "BitVec" not in sort_text:
                    continue
                if int(expression.size()) != expected_bits:
                    continue
            constraints.extend(
                z3_domain_constraints(
                    expression,
                    spec,
                    profile=contract.get("profile"),
                )
            )
    return constraints


def add_active_domain_constraints(
    solver: Any,
    ctx: Context,
    *formulas: Any,
) -> list[Any]:
    """Conjoin the configured input domain to semantic SMT formulas."""
    available = [formula for formula in formulas if formula is not None]
    if not available:
        return []
    combined = And(*available) if len(available) > 1 else available[0]
    constraints = active_domain_constraints(combined, ctx)
    seen = set()
    unique = []
    for constraint in constraints:
        key = str(constraint)
        if key in seen:
            continue
        seen.add(key)
        unique.append(constraint)
        solver.add(constraint)
    return unique


def configured_input_ranges() -> dict[str, Any] | None:
    contract = _ACTIVE_INPUT_CONTRACT.get()
    if not contract:
        return None
    profile = contract.get("profile") or {}
    integer = profile.get("integer") or {}
    floating_point = profile.get("floating_point") or {}
    if not integer or not floating_point:
        return None
    return {
        "integer": [
            int(integer["minimum"]),
            int(integer["maximum"]),
        ],
        "floating_point": [
            float(floating_point["minimum"]),
            float(floating_point["maximum"]),
        ],
    }


@lru_cache(maxsize=8192)
def _read_path_text_cached(
    path_text: str,
    mtime_ns: int,
    size: int,
) -> str:
    del mtime_ns, size
    return Path(path_text).read_text(
        encoding="utf-8",
        errors="replace",
    )


def cached_path_text(path: Path) -> str:
    stat = path.stat()
    return _read_path_text_cached(
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
    )


def parse_formula(path: Path, ctx: Context):
    formula = formula_from_smt_text(
        cached_path_text(path),
        ctx,
    )
    constraints = active_domain_constraints(formula, ctx)
    return And(formula, *constraints) if constraints else formula


def semantic_contract_hash(contract: dict[str, Any]) -> str:
    """Hash only fields that define the permitted external input domain."""
    return sha256_json(
        {
            "profile_id": contract.get("profile_id"),
            "profile": contract.get("profile") or {},
            "schema_hash": contract.get("schema_hash"),
            "inputs": contract.get("inputs") or [],
            "source_preconditions": (
                contract.get("source_preconditions") or []
            ),
        }
    )


def artifact_domain_audit(
    exploration: dict[str, Any],
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    if not contract:
        return {
            "status": "not_configured",
            "compatible": True,
            "sides": {},
        }
    expected_profile_hash = sha256_json(contract.get("profile") or {})
    expected_stored_contract_hash = contract.get("domain_hash")
    expected_semantic_contract_hash = semantic_contract_hash(contract)
    expected_schema_key = semantic_schema_key(contract.get("inputs") or [])
    sides = {}
    compatible = True
    for side, key in (
        ("old", "symbolic_oldV"),
        ("new", "symbolic_newV"),
    ):
        artifact = exploration.get(key) or {}
        artifact_profile_hash = artifact.get("input_domain_profile_hash")
        artifact_contract = artifact.get("input_contract") or {}
        artifact_contract_hash = artifact_contract.get("domain_hash")
        artifact_contract_inputs = artifact_contract.get("inputs")
        artifact_schema = artifact.get("input_schema")
        reasons = []
        if artifact_profile_hash and artifact_profile_hash != expected_profile_hash:
            reasons.append("profile_hash_mismatch")
        contract_hash_basis = ""
        if artifact_contract_hash:
            if artifact_contract_hash == expected_stored_contract_hash:
                contract_hash_basis = "stored_exact"
            elif (
                artifact_contract_inputs
                and semantic_contract_hash(artifact_contract)
                == expected_semantic_contract_hash
            ):
                contract_hash_basis = "semantic_canonical"
            else:
                reasons.append("domain_contract_hash_mismatch")
        schema_source = (
            artifact_contract_inputs
            if isinstance(artifact_contract_inputs, list)
            else artifact_schema
        )
        if isinstance(schema_source, list):
            if semantic_schema_key(schema_source) != expected_schema_key:
                reasons.append("domain_input_schema_mismatch")
        else:
            reasons.append("artifact_input_schema_missing")
        side_compatible = not reasons
        compatible = compatible and side_compatible
        sides[side] = {
            "compatible": side_compatible,
            "artifact_profile_hash": artifact_profile_hash,
            "artifact_contract_hash": artifact_contract_hash,
            "artifact_semantic_contract_hash": (
                semantic_contract_hash(artifact_contract)
                if artifact_contract_inputs
                else None
            ),
            "contract_hash_basis": contract_hash_basis,
            "artifact_input_schema": schema_source,
            "expected_profile_hash": expected_profile_hash,
            "expected_stored_contract_hash": expected_stored_contract_hash,
            "expected_semantic_contract_hash": (
                expected_semantic_contract_hash
            ),
            "external_domain_conjunction_required": (
                not artifact_profile_hash
            ),
            "reasons": reasons,
        }
    return {
        "status": "compatible" if compatible else "mismatch",
        "compatible": compatible,
        "comparison_basis": (
            "exact_stored_hash_or_canonical_semantic_hash"
        ),
        "expected_stored_contract_hash": expected_stored_contract_hash,
        "expected_semantic_contract_hash": expected_semantic_contract_hash,
        "sides": sides,
    }


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
    persist_smt_query(
        solver,
        stage="return_value_overlap_equivalence",
        timeout_ms=min(timeout_ms, RETURN_EQ_TIMEOUT_MS),
        elapsed=elapsed,
        status=status,
        path_ids=[
            path.stem
            for path in (left_path, right_path)
            if path is not None
        ],
    )
    if status == unsat:
        return True, elapsed
    if str(status) == "sat":
        return False, elapsed
    return None, elapsed


def verify_path_overlap(
    left: Path,
    right: Path,
    timeout_ms: int,
) -> tuple[Any | None, float]:
    start = time.perf_counter()
    ctx = Context()
    solver = Solver(ctx=ctx)
    solver.set("timeout", timeout_ms)
    solver.add(parse_formula(left, ctx), parse_formula(right, ctx))
    status = solver.check()
    elapsed = time.perf_counter() - start
    persist_smt_query(
        solver,
        stage="path_overlap",
        timeout_ms=timeout_ms,
        elapsed=elapsed,
        status=status,
        path_ids=[left.stem, right.stem],
    )
    return status, elapsed


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


@lru_cache(maxsize=8192)
def _extract_semantic_summary_cached(
    path_text: str,
    mtime_ns: int,
    size: int,
) -> dict[str, Any] | None:
    del mtime_ns, size
    path = Path(path_text)
    prefix = "; Semantic summary JSON:"
    for line in cached_path_text(path).splitlines():
        if line.startswith(prefix):
            try:
                return json.loads(line[len(prefix):].strip())
            except json.JSONDecodeError:
                return None
    return None


def extract_semantic_summary(path: Path) -> dict[str, Any] | None:
    stat = path.stat()
    return _extract_semantic_summary_cached(
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
    )


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

    output_eq, output_time, _output_calls = verify_output_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    total_time += output_time
    details["program_output_equivalent"] = output_eq

    details["memory_state_equivalent"] = "auxiliary_not_checked"
    global_eq, global_time, _global_calls, global_mapping = verify_global_state_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    total_time += global_time
    details["global_state_equivalent"] = global_eq
    details["global_state_mapping"] = global_mapping
    component_results = {
        "return_value": return_eq,
        "program_output": output_eq,
        "global_state": global_eq,
    }
    details["semantic_component_results"] = component_results
    if all(value is True for value in component_results.values()):
        return True, total_time, details
    if any(value is False for value in component_results.values()):
        return False, total_time, details
    return None, total_time, details


def verify_semantic_path_relation(
    left: Path,
    right: Path,
    timeout_ms: int,
    *,
    replay_mismatches: bool = True,
    counterexample_only: bool = False,
    direction: str = "old_to_new",
) -> tuple[bool | None, float, int, dict[str, Any]]:
    """Check whether two paths agree on their overlapping input region."""
    start = time.perf_counter()
    _ACTIVE_RELATION_CONTEXT.set(
        {
            "task_uid": _ACTIVE_TASK_UID.get(),
            "direction": direction,
            "source_path_id": left.stem,
            "target_path_id": right.stem,
        }
    )
    ctx = Context()
    left_constraint = parse_formula(left, ctx)
    right_constraint = parse_formula(right, ctx)
    overlap_solver = Solver(ctx=ctx)
    overlap_solver.set("timeout", timeout_ms)
    overlap_solver.add(left_constraint, right_constraint)
    overlap_status = overlap_solver.check()
    elapsed = time.perf_counter() - start
    smt_calls = 1
    overlap_audit = persist_smt_query(
        overlap_solver,
        stage="semantic_input_overlap",
        timeout_ms=timeout_ms,
        elapsed=elapsed,
        status=overlap_status,
        path_ids=[left.stem, right.stem],
    )
    overlap_model = overlap_solver.model() if overlap_status == sat else None

    details: dict[str, Any] = {
        "input_overlap": str(overlap_status),
        "return_value_equivalent": None,
        "program_output_equivalent": None,
        "memory_state_equivalent": None,
        "global_state_equivalent": None,
        "semantic_mode": "input_return_output_global_state_overlap",
    }
    if overlap_audit is not None:
        details["unknown_query"] = overlap_audit
        details["overlap_query_sha256"] = overlap_audit.get("query_sha256")
    if overlap_status == unsat:
        return False, elapsed, smt_calls, details
    if overlap_status != sat:
        return None, elapsed, smt_calls, details

    model_variables = collect_variables(
        left_constraint,
        right_constraint,
    )
    model_seed_inputs = concrete_inputs_from_variables(
        overlap_model,
        model_variables,
    )
    if model_seed_inputs:
        specs = complete_input_specs_for_paths(
            left.parent,
            left,
            right,
        )
        complete_inputs = complete_inputs_from_model(
            overlap_model,
            model_variables,
            specs,
        )
        if specs and len(complete_inputs) == len(specs):
            static_model_counterexample = {
                "inputs": complete_inputs,
                "input_schema": [
                    {
                        "name": name,
                        "kind": kind,
                        "bits": bits,
                        "precision": precision,
                    }
                    for name, kind, bits, precision in specs
                ],
                "input_schema_source": "exploration_and_path_artifacts",
                "source": "static_path_overlap_model",
            }
            persist_sat_counterexample_candidate(
                overlap_solver,
                stage="semantic_input_overlap",
                timeout_ms=timeout_ms,
                elapsed_seconds=elapsed,
                component="program_output",
                counterexample=static_model_counterexample,
            )
            static_model_replay = replay_counterexample(
                left,
                right,
                static_model_counterexample,
            )
            finalize_replay_candidate(
                static_model_counterexample,
                static_model_replay,
            )
            details["static_model_counterexample"] = (
                static_model_counterexample
            )
            details["static_model_replay"] = static_model_replay
            if static_model_replay.get("confirmed"):
                persist_smt_query(
                    overlap_solver,
                    stage="semantic_input_overlap_confirmed",
                    timeout_ms=timeout_ms,
                    elapsed=elapsed,
                    status=overlap_status,
                    path_ids=[left.stem, right.stem],
                    details={
                        "counterexample_source": (
                            "static_path_overlap_model"
                        ),
                        "replayed": True,
                    },
                    force=True,
                )
                details["counterexample"] = static_model_counterexample
                details["replay"] = static_model_replay
                details["mismatch_component"] = "program_output"
                details["mismatch_confirmed"] = True
                return False, elapsed, smt_calls, details

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
                timeout_ms,
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
    if return_eq is False and counterexample_only:
        return False, elapsed + return_time, smt_calls + return_calls, details
    if return_eq is None:
        return_eq, return_time, return_calls = verify_return_equivalence_on_overlap(
            left_summary, right_summary, timeout_ms, left, right
        )
    elapsed += return_time
    smt_calls += return_calls
    details["return_value_equivalent"] = return_eq
    if return_eq is False and replay_mismatches:
        counterexample = details.get("counterexample")
        if not counterexample:
            counterexample = find_return_counterexample(
                left_summary, right_summary, timeout_ms, left, right
            )
        details["counterexample"] = counterexample
        details["return_replay"] = replay_counterexample(
            left,
            right,
            counterexample,
        )
        finalize_replay_candidate(
            counterexample,
            details["return_replay"],
        )
        if details["return_replay"].get("confirmed"):
            details["replay"] = details["return_replay"]
            details["mismatch_component"] = "return_value"
            details["mismatch_confirmed"] = True
            return False, elapsed, smt_calls, details

    output_eq, output_time, output_calls = verify_output_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    elapsed += output_time
    smt_calls += output_calls
    details["program_output_equivalent"] = output_eq
    if output_eq is False and replay_mismatches:
        counterexample = find_output_counterexample(
            left_summary,
            right_summary,
            timeout_ms,
            left,
            right,
        )
        details["output_counterexample"] = counterexample
        details["output_replay"] = replay_counterexample(
            left,
            right,
            counterexample,
        )
        finalize_replay_candidate(
            counterexample,
            details["output_replay"],
        )
        if details["output_replay"].get("confirmed"):
            details["replay"] = details["output_replay"]
            details["mismatch_component"] = "program_output"
            details["mismatch_confirmed"] = True
            return False, elapsed, smt_calls, details

    details["memory_state_equivalent"] = "auxiliary_not_checked"
    global_eq, global_time, global_calls, global_mapping = verify_global_state_equivalence(
        left_summary, right_summary, timeout_ms, left, right
    )
    elapsed += global_time
    smt_calls += global_calls
    details["global_state_equivalent"] = global_eq
    details["global_state_mapping"] = global_mapping
    if global_eq is False:
        global_counterexample = find_global_state_counterexample(
            left_summary,
            right_summary,
            timeout_ms,
            left,
            right,
        )
        details["global_counterexample"] = global_counterexample
        global_replay = replay_counterexample(
            left,
            right,
            global_counterexample,
        )
        finalize_replay_candidate(
            global_counterexample,
            global_replay,
            accept_static_global_mismatch=replay_confirms_defined_execution(
                global_replay
            ),
        )
        details["global_replay"] = global_replay
        if replay_confirms_defined_execution(global_replay):
            details["replay"] = global_replay
            details["mismatch_component"] = "global_state"
            details["mismatch_confirmed"] = True
            return False, elapsed, smt_calls, details

    component_results = {
        "return_value": return_eq,
        "program_output": output_eq,
        "global_state": global_eq,
    }
    details["semantic_component_results"] = component_results
    if all(value is True for value in component_results.values()):
        details["mismatch_confirmed"] = False
        return True, elapsed, smt_calls, details
    if any(value is False for value in component_results.values()):
        details["mismatch_confirmed"] = False
        details["replay"] = (
            details.get("global_replay")
            or details.get("return_replay")
            or details.get("output_replay")
            or {"confirmed": False, "reason": "no_replayable_counterexample"}
        )
        return False, elapsed, smt_calls, details

    details["mismatch_confirmed"] = False
    details["unresolved_components"] = [
        name for name, value in component_results.items() if value is None
    ]
    return None, elapsed, smt_calls, details


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
    saw_unknown = False
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
            saw_unknown = True
            continue
        if (
            str(left.get("specifier") or "") != str(right.get("specifier") or "")
            or int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0)
            or int(left.get("bits", 0) or 0) <= 0
        ):
            return False, total_time, calls
        left_smt = left.get("smt")
        right_smt = right.get("smt")
        left_var = summary_variable_name(left_smt, left.get("variable"))
        right_var = summary_variable_name(right_smt, right.get("variable"))
        if all(
            isinstance(value, str) and value
            for value in (left_smt, right_smt, left_var, right_var)
        ):
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
            query_kind="output_counterexample_equivalence",
        )
        calls += int(bool(left.get("smt") and right.get("smt")))
        total_time += elapsed
        if equivalent is False:
            return False, total_time, calls
        if equivalent is None:
            saw_unknown = True
    if saw_unknown:
        return None, total_time, calls
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
        left_var = summary_variable_name(left_smt, left.get("variable"))
        right_var = summary_variable_name(right_smt, right.get("variable"))
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

    start = time.perf_counter()
    ctx = Context()
    formulas = []
    solver = Solver(ctx=ctx)
    solver.set("timeout", timeout_ms)
    try:
        if left_path is not None and right_path is not None:
            path_formulas = [parse_formula(left_path, ctx), parse_formula(right_path, ctx)]
            formulas.extend(path_formulas)
            solver.add(*path_formulas)
        mismatch = (
            BoolVal(True, ctx=ctx)
            if len(left_segments) != len(right_segments)
            else None
        )
        for left, right in (
            [] if mismatch is not None else zip(left_segments, right_segments)
        ):
            if str(left.get("sink")) != str(right.get("sink")):
                mismatch = BoolVal(True, ctx=ctx)
                break
            if str(left.get("kind") or "") != str(right.get("kind") or ""):
                mismatch = BoolVal(True, ctx=ctx)
                break
            if left.get("kind") == "text":
                if left.get("value") != right.get("value"):
                    mismatch = BoolVal(True, ctx=ctx)
                    break
                continue
            if (
                left.get("kind") != "formatted_value"
                or left.get("specifier") != right.get("specifier")
                or int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0)
            ):
                mismatch = BoolVal(True, ctx=ctx)
                break
            left_smt = left.get("smt")
            right_smt = right.get("smt")
            left_var = summary_variable_name(left_smt, left.get("variable"))
            right_var = summary_variable_name(right_smt, right.get("variable"))
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
            solver.add(left_formula, right_formula)
            add_active_domain_constraints(
                solver,
                ctx,
                left_formula,
                right_formula,
            )
            bits = int(left["bits"])
            left_value = BitVec(left_var, bits, ctx=ctx)
            right_value = BitVec(right_var_renamed, bits, ctx=ctx)
            if is_float_observable(left) and is_float_observable(right):
                mismatch = zero_sign_insensitive_float_neq(
                    left_value,
                    right_value,
                    bits,
                    ctx,
                )
            else:
                mismatch = left_value != right_value
            break
        if mismatch is not None:
            solver.add(mismatch)
        query_status = solver.check()
        persist_smt_query(
            solver,
            stage="output_counterexample",
            timeout_ms=timeout_ms,
            elapsed=time.perf_counter() - start,
            status=query_status,
            force=query_status == sat,
            path_ids=[
                path.stem
                for path in (left_path, right_path)
                if path is not None
            ],
        )
        if query_status != sat:
            return None
        model = solver.model()
        variables = collect_variables(*formulas)
        schema_dir = (
            left_path.parent
            if left_path is not None
            else right_path.parent
            if right_path is not None
            else Path(".")
        )
        specs = complete_input_specs_for_paths(
            schema_dir,
            *(
                path
                for path in (left_path, right_path)
                if path is not None
            ),
        )
        inputs = complete_inputs_from_model(model, variables, specs)
        counterexample_result = {
            "inputs": inputs,
            "input_schema": [
                {
                    "name": name,
                    "kind": kind,
                    "bits": bits,
                    "precision": precision,
                }
                for name, kind, bits, precision in specs
            ],
            "input_schema_source": (
                "exploration_and_path_artifacts"
                if specs
                else "not_available"
            ),
        }
        persist_sat_counterexample_candidate(
            solver,
            stage="output_counterexample",
            timeout_ms=timeout_ms,
            elapsed_seconds=time.perf_counter() - start,
            component="program_output",
            counterexample=counterexample_result,
        )
        return counterexample_result
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
    start = time.perf_counter()
    ctx = Context()
    left_formula = formula_from_smt_text(left_smt, ctx)
    right_formula = formula_from_smt_text(right_smt, ctx)
    solver = Solver(ctx=ctx)
    solver.set("timeout", min(timeout_ms, RETURN_EQ_TIMEOUT_MS))
    if left_path is not None and right_path is not None:
        solver.add(parse_formula(left_path, ctx), parse_formula(right_path, ctx))
    add_active_domain_constraints(
        solver,
        ctx,
        left_formula,
        right_formula,
    )
    left_ret = BitVec(left_var, bits, ctx=ctx)
    right_ret = BitVec(right_var_renamed, bits, ctx=ctx)
    if return_values_are_float(left_return, right_return):
        neq = zero_sign_insensitive_float_neq(left_ret, right_ret, bits, ctx)
    else:
        neq = left_ret != right_ret
    solver.add(left_formula, right_formula, neq)
    status = solver.check()
    elapsed = time.perf_counter() - start
    if status == unsat:
        return True, elapsed, 1
    if status == sat:
        persist_sat_counterexample_candidate(
            solver,
            stage="return_value_counterexample_equivalence",
            timeout_ms=min(timeout_ms, RETURN_EQ_TIMEOUT_MS),
            elapsed_seconds=elapsed,
            component="return_value",
        )
        return False, elapsed, 1
    return None, elapsed, 1


def global_cells(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return canonical global cells across legacy and v6 summaries."""
    for key in ("regions", "objects"):
        value = state.get(key)
        if isinstance(value, dict):
            return value
    return None


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
        return None, 0.0, 0, {"method": "unavailable"}
    if left_state.get("unresolved") or right_state.get("unresolved"):
        return None, 0.0, 0, {"method": "unresolved"}
    left_regions = global_cells(left_state)
    right_regions = global_cells(right_state)
    if left_regions is None or right_regions is None:
        return None, 0.0, 0, {"method": "missing_cells"}
    if not left_regions and not right_regions:
        return True, 0.0, 0, {"method": "both_empty", "mapped_cells": 0}

    pairs, mapping_method = map_global_regions_with_mode(
        left_regions,
        right_regions,
    )
    mapping = {
        "method": mapping_method,
        "mapped_cells": len(pairs or []),
        "fallback_used": mapping_method == "sorted_position_fallback",
    }
    if pairs is None:
        return None, 0.0, 0, mapping
    total_time = 0.0
    calls = 0
    saw_unknown = False
    for left_cell, right_cell in pairs:
        equivalent, elapsed = verify_observable_expr_equivalence(
            left_cell,
            right_cell,
            timeout_ms,
            left_path,
            right_path,
            query_kind="global_state_counterexample_equivalence",
        )
        total_time += elapsed
        calls += int(bool(left_cell.get("smt") and right_cell.get("smt")))
        if equivalent is False:
            return False, total_time, calls, mapping
        if equivalent is None:
            saw_unknown = True
    if saw_unknown:
        return None, total_time, calls, mapping
    return True, total_time, calls, mapping


def map_global_regions_with_mode(
    left_regions: dict[str, Any], right_regions: dict[str, Any]
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]] | None, str]:
    """Map by canonical identity, then by the historical sorted-position rule."""
    if set(left_regions) == set(right_regions):
        left_items = sorted(left_regions.items())
        right_items = sorted(right_regions.items())
        mapping_method = "canonical_key"
    elif len(left_regions) == len(right_regions):
        left_items = sorted(left_regions.items())
        right_items = sorted(right_regions.items())
        mapping_method = "sorted_position_fallback"
    else:
        return None, "unmapped"
    pairs = []
    for (_left_key, left), (_right_key, right) in zip(left_items, right_items):
        if not isinstance(left, dict) or not isinstance(right, dict):
            return None, "invalid_cell"
        if int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0):
            return None, "width_mismatch"
        pairs.append((left, right))
    return pairs, mapping_method


def map_global_regions(
    left_regions: dict[str, Any],
    right_regions: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any]]] | None:
    """Compatibility wrapper for the historical global-cell mapping."""
    pairs, _method = map_global_regions_with_mode(
        left_regions,
        right_regions,
    )
    return pairs


def global_regions_identical(
    left_state: dict[str, Any],
    right_state: dict[str, Any],
) -> bool:
    left_regions = global_cells(left_state)
    right_regions = global_cells(right_state)
    if left_regions is None or right_regions is None:
        return False
    pairs = map_global_regions(left_regions, right_regions)
    if pairs is None:
        return False
    for left, right in pairs:
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False
        if int(left.get("bits", 0) or 0) != int(right.get("bits", 0) or 0):
            return False
        left_smt = left.get("smt")
        right_smt = right.get("smt")
        left_var = summary_variable_name(left_smt, left.get("variable"))
        right_var = summary_variable_name(right_smt, right.get("variable"))
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


def verify_observable_expr_equivalence(
    left: dict[str, Any],
    right: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
    query_kind: str = "observable_expression_equivalence",
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
        add_active_domain_constraints(
            solver,
            ctx,
            left_formula,
            right_formula,
        )
        left_value = BitVec(left_var, bits, ctx=ctx)
        right_value = BitVec(right_var_renamed, bits, ctx=ctx)
        if is_float_observable(left) and is_float_observable(right):
            neq = zero_sign_insensitive_float_neq(
                left_value,
                right_value,
                bits,
                ctx,
            )
        else:
            neq = left_value != right_value
        solver.add(left_formula, right_formula, neq)
        status = solver.check()
    except Exception:
        return None, time.perf_counter() - start
    elapsed = time.perf_counter() - start
    persist_smt_query(
        solver,
        stage="observable_expression_equivalence",
        timeout_ms=timeout_ms,
        elapsed=elapsed,
        status=status,
        path_ids=[
            path.stem
            for path in (left_path, right_path)
            if path is not None
        ],
        details={
            "left_variable": left_var,
            "right_variable": right_var,
            "bits": bits,
            "left_specifier": left.get("specifier"),
            "right_specifier": right.get("specifier"),
        },
    )
    if status == unsat:
        return True, elapsed
    if status == sat:
        persist_sat_counterexample_candidate(
            solver,
            stage=query_kind,
            timeout_ms=timeout_ms,
            elapsed_seconds=elapsed,
            component=(
                "global_state"
                if "global_state" in query_kind
                else "program_output"
            ),
        )
        return False, elapsed
    return None, elapsed


def find_global_state_counterexample(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
) -> dict[str, Any] | None:
    """Find one concrete input for a mapped global-cell difference."""
    left_state = left_summary.get("global_state") or {}
    right_state = right_summary.get("global_state") or {}
    if not left_state.get("available") or not right_state.get("available"):
        return None
    if left_state.get("unresolved") or right_state.get("unresolved"):
        return None
    left_regions = global_cells(left_state)
    right_regions = global_cells(right_state)
    if left_regions is None or right_regions is None:
        return None
    pairs, mapping_method = map_global_regions_with_mode(
        left_regions,
        right_regions,
    )
    if pairs is None:
        return None
    for left_cell, right_cell in pairs:
        bits = int(left_cell.get("bits", 0) or 0)
        if bits <= 0 or bits != int(right_cell.get("bits", 0) or 0):
            continue
        left_smt = left_cell.get("smt")
        right_smt = right_cell.get("smt")
        left_var = summary_variable_name(
            left_smt,
            left_cell.get("variable"),
        )
        right_var = summary_variable_name(
            right_smt,
            right_cell.get("variable"),
        )
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
        ctx = Context()
        try:
            left_formula = formula_from_smt_text(left_smt, ctx)
            right_formula = formula_from_smt_text(right_smt, ctx)
            solver = Solver(ctx=ctx)
            solver.set("timeout", timeout_ms)
            path_formulas = []
            if left_path is not None and right_path is not None:
                path_formulas = [
                    parse_formula(left_path, ctx),
                    parse_formula(right_path, ctx),
                ]
                solver.add(*path_formulas)
            add_active_domain_constraints(
                solver,
                ctx,
                left_formula,
                right_formula,
            )
            left_value = BitVec(left_var, bits, ctx=ctx)
            right_value = BitVec(right_var_renamed, bits, ctx=ctx)
            if is_float_observable(left_cell) and is_float_observable(
                right_cell
            ):
                difference = zero_sign_insensitive_float_neq(
                    left_value,
                    right_value,
                    bits,
                    ctx,
                )
            else:
                difference = left_value != right_value
            solver.add(left_formula, right_formula, difference)
            start = time.perf_counter()
            status = solver.check()
            elapsed = time.perf_counter() - start
            persist_smt_query(
                solver,
                stage="global_state_counterexample",
                timeout_ms=timeout_ms,
                elapsed=elapsed,
                status=status,
                force=status == sat,
                path_ids=[
                    path.stem
                    for path in (left_path, right_path)
                    if path is not None
                ],
                details={
                    "left_variable": left_var,
                    "right_variable": right_var,
                    "bits": bits,
                    "mapping_method": mapping_method,
                },
            )
            if status != sat:
                continue
            model = solver.model()
            variables = collect_variables(
                left_formula,
                right_formula,
                *path_formulas,
            )
            schema_dir = (
                left_path.parent
                if left_path is not None
                else right_path.parent
                if right_path is not None
                else Path(".")
            )
            specs = complete_input_specs_for_paths(
                schema_dir,
                *(
                    path
                    for path in (left_path, right_path)
                    if path is not None
                ),
            )
            inputs = complete_inputs_from_model(model, variables, specs)
            counterexample_result = {
                "inputs": inputs,
                "input_schema": [
                    {
                        "name": name,
                        "kind": kind,
                        "bits": bits_for_input,
                        "precision": precision,
                    }
                    for name, kind, bits_for_input, precision in specs
                ],
                "input_schema_source": (
                    "exploration_and_path_artifacts"
                    if specs
                    else "not_available"
                ),
                "mapping_method": mapping_method,
                "left_variable": left_var,
                "right_variable": right_var,
            }
            persist_sat_counterexample_candidate(
                solver,
                stage="global_state_counterexample",
                timeout_ms=timeout_ms,
                elapsed_seconds=elapsed,
                component="global_state",
                counterexample=counterexample_result,
            )
            return counterexample_result
        except Exception:
            continue
    return None


def find_return_counterexample(
    left_summary: dict[str, Any],
    right_summary: dict[str, Any],
    timeout_ms: int,
    left_path: Path | None = None,
    right_path: Path | None = None,
    seed_inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    start = time.perf_counter()
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
        add_active_domain_constraints(
            solver,
            ctx,
            left_formula,
            right_formula,
        )
        left_ret = BitVec(left_var, bits, ctx=ctx)
        right_ret = BitVec(right_var_renamed, bits, ctx=ctx)
        if return_values_are_float(left, right):
            neq = zero_sign_insensitive_float_neq(
                left_ret,
                right_ret,
                bits,
                ctx,
            )
        else:
            neq = left_ret != right_ret
        solver.add(left_formula, right_formula, neq)
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
        return_query_status = solver.check()
        persist_smt_query(
            solver,
            stage="return_value_counterexample",
            timeout_ms=timeout_ms,
            elapsed=time.perf_counter() - start,
            status=return_query_status,
            force=return_query_status == sat,
            path_ids=[
                path.stem
                for path in (left_path, right_path)
                if path is not None
            ],
        )
        if return_query_status != sat:
            return None
        model = solver.model()
        variables = collect_variables(
            left_formula,
            right_formula,
            *path_formulas,
        )
        schema_dir = (
            left_path.parent
            if left_path is not None
            else right_path.parent
            if right_path is not None
            else Path(".")
        )
        specs = complete_input_specs_for_paths(
            schema_dir,
            *(
                path
                for path in (left_path, right_path)
                if path is not None
            ),
        )
        inputs = complete_inputs_from_model(model, variables, specs)
        counterexample_result = {
            "inputs": inputs,
            "input_schema": [
                {
                    "name": name,
                    "kind": kind,
                    "bits": bits,
                    "precision": precision,
                }
                for name, kind, bits, precision in specs
            ],
            "input_schema_source": (
                "exploration_and_path_artifacts"
                if specs
                else "not_available"
            ),
        }
        persist_sat_counterexample_candidate(
            solver,
            stage="return_value_counterexample",
            timeout_ms=timeout_ms,
            elapsed_seconds=time.perf_counter() - start,
            component="return_value",
            counterexample=counterexample_result,
        )
        return counterexample_result
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
    specs: dict[str, tuple[str, int, int]] = {}
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


def input_specs_from_path_artifacts(
    *paths: Path,
) -> tuple[tuple[str, str, int, int], ...]:
    """Recover complete input arity when an unconstrained path has no symbols."""
    specs: dict[str, tuple[str, int]] = {}
    for path in paths:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        names: list[str] = []
        signature = re.search(
            r";\s*Symbolic variable values:\s*(\{.*\})",
            content,
        )
        if signature:
            try:
                values = ast.literal_eval(signature.group(1))
            except (SyntaxError, ValueError):
                values = {}
            if isinstance(values, dict):
                names.extend(
                    name
                    for name in values
                    if isinstance(name, str) and is_input_symbol(name)
                )
        names.extend(
            re.findall(
                r"\(declare-fun\s+"
                r"((?:FP_arg_|arg_|scanf_)[A-Za-z0-9_]+)\s+\(\)",
                content,
            )
        )
        for name in names:
            floating = re.search(
                rf"\(declare-fun\s+{re.escape(name)}\s+\(\)\s+"
                r"\(_\s+FloatingPoint\s+(\d+)\s+(\d+)\)\)",
                content,
            )
            bitvec = re.search(
                rf"\(declare-fun\s+{re.escape(name)}\s+\(\)\s+"
                r"\(_\s+BitVec\s+(\d+)\)\)",
                content,
            )
            if floating:
                bits = int(floating.group(1)) + int(floating.group(2))
                specs[name] = ("float", bits)
            elif bitvec:
                specs[name] = ("bitvec", int(bitvec.group(1)))
            elif name.startswith("FP_arg_"):
                specs.setdefault(name, ("float", 32))
            else:
                specs.setdefault(name, ("bitvec", 32))
    by_position: dict[int, tuple[int, str, tuple[str, int]]] = {}
    priority = {"FP_arg_": 0, "scanf_": 1, "arg_": 2}
    for name, value in specs.items():
        order = input_symbol_order(name)
        family = next(
            (prefix for prefix in priority if name.startswith(prefix)),
            "arg_",
        )
        candidate = (priority[family], name, value)
        current = by_position.get(order[0])
        if (
            current is None
            or candidate[0] < current[0]
            or (
                candidate[0] == current[0]
                and len(candidate[1]) > len(current[1])
            )
        ):
            by_position[order[0]] = candidate
    canonical = sorted(
        (
            (name, kind, bits, 0)
            for _rank, name, (kind, bits) in by_position.values()
        ),
        key=lambda item: input_symbol_order(item[0]),
    )
    return tuple(canonical)


def merge_input_specs(
    *spec_groups: tuple[tuple[str, str, int, int], ...] | None,
) -> tuple[tuple[str, str, int, int], ...]:
    """Merge positional schemas, preferring float declarations over fallbacks."""
    by_position: dict[int, tuple[str, str, int, int]] = {}
    priority = {"FP_arg_": 0, "scanf_": 1, "arg_": 2}
    for specs in spec_groups:
        for name, kind, bits, precision in specs or ():
            position = input_symbol_order(name)[0]
            family = next(
                (prefix for prefix in priority if name.startswith(prefix)),
                "other",
            )
            candidate = (
                name,
                kind,
                int(bits),
                int(precision),
            )
            current = by_position.get(position)
            if current is None:
                by_position[position] = candidate
                continue
            current_family = next(
                (prefix for prefix in priority if current[0].startswith(prefix)),
                "other",
            )
            if priority.get(family, 9) < priority.get(current_family, 9):
                by_position[position] = candidate
            elif family == current_family and candidate[2] > current[2]:
                by_position[position] = candidate
    return tuple(
        sorted(
            by_position.values(),
            key=lambda item: input_symbol_order(item[0]),
        )
    )


def input_schema_from_exploration(
    paths_dir: Path,
) -> tuple[tuple[str, str, int, int], ...]:
    """Read the complete input schema emitted by the current exploration tool."""
    schemas: list[list[dict[str, Any]]] = []
    for prefix in ("symbolic_oldV", "symbolic_newV"):
        path = paths_dir / f"{prefix}_exploration.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        schema = payload.get("input_schema")
        if isinstance(schema, list):
            schemas.append(
                [item for item in schema if isinstance(item, dict)]
            )
    if not schemas:
        return ()

    by_position: dict[int, tuple[str, str, int, int]] = {}
    for schema in schemas:
        for index, item in enumerate(schema):
            name = str(item.get("name") or f"arg_{index}")
            kind = str(item.get("kind") or "bitvec")
            bits = int(item.get("bits", 32) or 32)
            precision = int(item.get("precision", 0) or 0)
            by_position[input_symbol_order(name)[0]] = (
                name,
                kind,
                bits,
                precision,
            )
    return tuple(
        sorted(
            by_position.values(),
            key=lambda item: input_symbol_order(item[0]),
        )
    )


def explicit_zero_input_contract(paths_dir: Path) -> bool:
    """Return true only when both sides explicitly declare zero inputs."""
    for prefix in ("symbolic_oldV", "symbolic_newV"):
        path = paths_dir / f"{prefix}_exploration.json"
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        contract = payload.get("input_contract")
        if isinstance(contract, dict) and isinstance(
            contract.get("inputs"),
            list,
        ):
            inputs = contract["inputs"]
        elif isinstance(payload.get("input_schema"), list):
            inputs = payload["input_schema"]
        else:
            return False
        if inputs:
            return False
    return True


def complete_input_specs_for_paths(
    paths_dir: Path,
    *paths: Path,
) -> tuple[tuple[str, str, int, int], ...]:
    """Return one positional schema for every harness argument."""
    return merge_input_specs(
        input_schema_from_exploration(paths_dir),
        input_specs_from_path_artifacts(*paths),
    )


def deterministic_input_for_spec(
    spec: tuple[str, str, int, int],
) -> dict[str, Any]:
    name, kind, bits, _precision = spec
    if kind == "float":
        return {
            "name": name,
            "kind": "float",
            "bits": bits,
            "value": 0.0,
            "ieee_bits": 0,
            "source": "deterministic_unconstrained_completion",
        }
    return {
        "name": name,
        "kind": "bitvec",
        "bits": bits,
        "value": 0,
        "unsigned": 0,
        "source": "deterministic_unconstrained_completion",
    }


def complete_inputs_from_model(
    model,
    variables: list[Any],
    specs: tuple[tuple[str, str, int, int], ...],
) -> list[dict[str, Any]]:
    """Evaluate one complete positional harness input from a single SAT model."""
    concrete_by_position: dict[int, list[dict[str, Any]]] = {}
    for item in concrete_inputs_from_variables(model, variables):
        concrete_by_position.setdefault(
            input_symbol_order(item["name"])[0],
            [],
        ).append(item)
    if not specs:
        return [
            concrete_by_position[position][0]
            for position in sorted(concrete_by_position)
        ]

    completed: list[dict[str, Any]] = []
    for spec in specs:
        position = input_symbol_order(spec[0])[0]
        candidates = concrete_by_position.get(position, [])
        item = next(
            (
                candidate
                for candidate in candidates
                if str(candidate.get("kind")) == spec[1]
                and int(candidate.get("bits", 0) or 0) == spec[2]
            ),
            None,
        )
        if item is None and candidates:
            fallback = candidates[0]
            fallback_bits = int(fallback.get("bits", 0) or 0)
            if spec[1] == "float" and fallback_bits == spec[2]:
                raw = int(fallback.get("unsigned", 0) or 0)
                item = {
                    "name": spec[0],
                    "kind": "float",
                    "bits": spec[2],
                    "value": struct.unpack(
                        ">f" if spec[2] == 32 else ">d",
                        raw.to_bytes(spec[2] // 8, "big"),
                    )[0],
                    "ieee_bits": raw,
                    "source": "model_bit_pattern_coercion",
                }
            elif spec[1] == "bitvec" and fallback_bits == spec[2]:
                raw = int(fallback.get("ieee_bits", 0) or 0)
                item = {
                    "name": spec[0],
                    "kind": "bitvec",
                    "bits": spec[2],
                    "value": raw
                    - (1 << spec[2])
                    if raw >= (1 << (spec[2] - 1))
                    else raw,
                    "unsigned": raw,
                    "source": "model_bit_pattern_coercion",
                }
        if item is None:
            completed.append(deterministic_input_for_spec(spec))
            continue
        completed.append(item)
    return completed


def validate_replay_inputs(
    counterexample: dict[str, Any] | None,
    specs: tuple[tuple[str, str, int, int], ...],
) -> tuple[list[dict[str, Any]], list[int], list[str]]:
    """Return ordered inputs and reject missing or mistyped harness positions."""
    raw_inputs = (counterexample or {}).get("inputs")
    if not isinstance(raw_inputs, list):
        return [], [input_symbol_order(spec[0])[0] for spec in specs], []
    by_position = {
        input_symbol_order(str(item.get("name") or ""))[0]: item
        for item in raw_inputs
        if isinstance(item, dict) and item.get("name")
    }
    if not specs:
        return list(raw_inputs), [], []
    ordered: list[dict[str, Any]] = []
    missing: list[int] = []
    errors: list[str] = []
    expected_positions = {input_symbol_order(spec[0])[0] for spec in specs}
    for spec in specs:
        position = input_symbol_order(spec[0])[0]
        item = by_position.get(position)
        if item is None:
            missing.append(position)
        else:
            if str(item.get("kind")) != spec[1]:
                errors.append(
                    f"position {position}: expected {spec[1]}, "
                    f"got {item.get('kind')}"
                )
            if int(item.get("bits", 0) or 0) != spec[2]:
                errors.append(
                    f"position {position}: expected {spec[2]} bits, "
                    f"got {item.get('bits')}"
                )
            ordered.append(item)
    unexpected = sorted(set(by_position) - expected_positions)
    if unexpected:
        errors.append(
            "unexpected input positions: "
            + ", ".join(str(item) for item in unexpected)
        )
    return ordered, missing, errors


def revalidate_completed_counterexample_query(
    counterexample: dict[str, Any] | None,
    ordered_inputs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check that deterministic model completion still satisfies the query."""
    checkpoint = (counterexample or {}).get("_candidate_checkpoint")
    if not isinstance(checkpoint, dict):
        return {
            "applicable": False,
            "status": "not_available",
            "reason": "candidate_checkpoint_missing",
        }
    query_raw = str(checkpoint.get("query_path") or "")
    query_path = Path(query_raw) if query_raw else None
    if query_path is None or not query_path.is_file():
        return {
            "applicable": False,
            "status": "not_available",
            "reason": "candidate_query_path_missing",
        }
    if query_path.stat().st_size > 32 * 1024 * 1024:
        return {
            "applicable": True,
            "status": "unknown",
            "reason": "candidate_query_too_large_for_completion_recheck",
            "query_path": str(query_path),
        }
    ctx = Context()
    solver = Z3Solver(ctx=ctx)
    try:
        solver.from_string(query_path.read_text(encoding="utf-8"))
        for item in ordered_inputs:
            name = str(item.get("name") or "")
            kind = str(item.get("kind") or "")
            bits = int(item.get("bits", 0) or 0)
            if not name or bits <= 0:
                return {
                    "applicable": True,
                    "status": "unknown",
                    "reason": "invalid_completed_input_spec",
                    "query_path": str(query_path),
                }
            if kind == "bitvec":
                variable = BitVec(name, bits, ctx=ctx)
                solver.add(
                    variable
                    == BitVecVal(
                        int(item.get("unsigned", 0) or 0),
                        bits,
                        ctx=ctx,
                    )
                )
            elif kind == "float":
                exponent_bits = 8 if bits == 32 else 11
                significand_bits = 24 if bits == 32 else 53
                variable = FP(
                    name,
                    FPSort(exponent_bits, significand_bits, ctx=ctx),
                    ctx=ctx,
                )
                solver.add(
                    fpToIEEEBV(variable, ctx=ctx)
                    == BitVecVal(
                        int(item.get("ieee_bits", 0) or 0),
                        bits,
                        ctx=ctx,
                    )
                )
            else:
                return {
                    "applicable": True,
                    "status": "unknown",
                    "reason": "unsupported_completed_input_kind",
                    "query_path": str(query_path),
                }
        solver.set("timeout", 5_000)
        status = str(solver.check())
    except Exception as exc:  # noqa: BLE001
        return {
            "applicable": True,
            "status": "error",
            "reason": f"{type(exc).__name__}:{exc}",
            "query_path": str(query_path),
        }
    return {
        "applicable": True,
        "status": status,
        "reason": (
            "completed_inputs_satisfy_original_candidate_query"
            if status == "sat"
            else "completed_inputs_do_not_satisfy_original_candidate_query"
        ),
        "query_path": str(query_path),
        "query_sha256": hashlib.sha256(
            query_path.read_bytes()
        ).hexdigest(),
    }


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
        exponent_bits = int(value.ebits())
        fraction_bits = int(value.sbits()) - 1
        exponent_mask = ((1 << exponent_bits) - 1) << fraction_bits
        compact = value.sexpr().replace(" ", "").casefold()
        if compact.startswith("(_nan"):
            # Z3's FPNumRef.sign() raises for NaN, so construct the canonical
            # positive quiet-NaN bit pattern directly.
            raw = exponent_mask | (1 << (fraction_bits - 1))
            number = math.nan
        elif compact.startswith("(_+oo"):
            raw = exponent_mask
            number = math.inf
        elif compact.startswith("(_-oo"):
            raw = (1 << (bits - 1)) | exponent_mask
            number = -math.inf
        else:
            raw = (
                (int(bool(value.sign())) << (bits - 1))
                | (int(value.exponent_as_long()) << fraction_bits)
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
        concrete_reader = getattr(model, "concrete_value", None)
        if callable(concrete_reader):
            concrete = concrete_reader(variable)
        else:
            value = model.eval(variable, model_completion=True)
            concrete = z3_value_to_concrete(model, value)
        if concrete is not None:
            inputs.append({"name": name, **concrete})
    inputs.sort(key=lambda item: input_symbol_order(item["name"]))
    return inputs


def replay_counterexample(
    left_path: Path, right_path: Path, counterexample: dict[str, Any] | None
) -> dict[str, Any]:
    if not isinstance(counterexample, dict):
        return {"confirmed": False, "reason": "counterexample_inputs_unavailable"}
    raw_inputs = counterexample.get("inputs")
    if not isinstance(raw_inputs, list):
        return {"confirmed": False, "reason": "counterexample_inputs_unavailable"}
    try:
        left_binary = binary_for_path(left_path)
        right_binary = binary_for_path(right_path)
    except ArtifactIdentityError as exc:
        return {
            "confirmed": False,
            "reason": "binary_identity_error",
            "identity_error": str(exc),
        }
    if left_binary is None or right_binary is None:
        return {"confirmed": False, "reason": "binary_unavailable"}
    specs = complete_input_specs_for_paths(
        left_path.parent,
        left_path,
        right_path,
    )
    zero_input = not specs and explicit_zero_input_contract(left_path.parent)
    if not raw_inputs and not zero_input:
        return {"confirmed": False, "reason": "counterexample_inputs_unavailable"}
    if zero_input and raw_inputs:
        return {
            "confirmed": False,
            "reason": "replay_input_invalid",
            "missing_positions": [],
            "validation_errors": ["zero-input program received inputs"],
            "input_schema": [],
        }
    active_contract = _ACTIVE_INPUT_CONTRACT.get()
    if active_contract:
        raw_schema = counterexample.get("input_schema")
        if not raw_schema:
            raw_schema = [
                {
                    key: value
                    for key, value in item.items()
                    if key
                    in {
                        "index",
                        "name",
                        "kind",
                        "bits",
                        "precision",
                        "c_type",
                    }
                }
                for item in active_contract.get("inputs") or []
            ]
        _ordered_domain_inputs, domain_errors = validate_values(
            raw_schema,
            counterexample.get("inputs"),
            active_contract.get("profile"),
        )
        if domain_errors:
            return {
                "confirmed": False,
                "reason": "replay_input_outside_configured_domain",
                "domain_errors": domain_errors,
                "inputs": counterexample.get("inputs"),
            }
    ordered_inputs, missing, validation_errors = validate_replay_inputs(
        counterexample,
        specs,
    )
    if missing or validation_errors:
        return {
            "confirmed": False,
            "reason": "replay_input_invalid",
            "missing_positions": missing,
            "validation_errors": validation_errors,
            "input_schema": [
                {
                    "name": name,
                    "kind": kind,
                    "bits": bits,
                    "precision": precision,
                }
                for name, kind, bits, precision in specs
            ],
        }
    query_revalidation = revalidate_completed_counterexample_query(
        counterexample,
        ordered_inputs,
    )
    if query_revalidation["applicable"] and query_revalidation["status"] != "sat":
        return {
            "confirmed": False,
            "reason": "completed_input_fails_static_query",
            "query_revalidation": query_revalidation,
            "inputs": ordered_inputs,
            "input_schema": specs,
        }
    tokens = [format_replay_value(item) for item in ordered_inputs]
    stdin = " ".join(tokens) + "\n"
    nan_payload_preserved = all(
        not (
            item.get("kind") == "float"
            and isinstance(item.get("value"), float)
            and math.isnan(item["value"])
        )
        or int(item.get("ieee_bits", 0) or 0)
        == (
            (0x7FC00000 if int(item.get("bits", 0) or 0) == 32 else 0x7FF8000000000000)
        )
        for item in ordered_inputs
    )
    left_runs = [run_binary(left_binary, stdin), run_binary(left_binary, stdin)]
    right_runs = [run_binary(right_binary, stdin), run_binary(right_binary, stdin)]
    if any(not run.get("completed") for run in left_runs + right_runs):
        return {
            "confirmed": False,
            "reason": "replay_failed",
            "stdin": stdin,
            "left_runs": left_runs,
            "right_runs": right_runs,
            "input_schema": specs,
            "nan_payload_preserved": nan_payload_preserved,
        }
    if left_runs[0] != left_runs[1] or right_runs[0] != right_runs[1]:
        return {
            "confirmed": False,
            "reason": "repeated_execution_unstable",
            "stdin": stdin,
            "left_runs": left_runs,
            "right_runs": right_runs,
            "input_schema": specs,
            "nan_payload_preserved": nan_payload_preserved,
        }
    left_run = left_runs[0]
    right_run = right_runs[0]
    left_summary = extract_semantic_summary(left_path)
    right_summary = extract_semantic_summary(right_path)
    stdout_equal, stdout_comparison = replay_streams_equivalent(
        left_summary,
        right_summary,
        str(left_run.get("stdout") or ""),
        str(right_run.get("stdout") or ""),
        sink="stdout",
    )
    stderr_equal, stderr_comparison = replay_streams_equivalent(
        left_summary,
        right_summary,
        str(left_run.get("stderr") or ""),
        str(right_run.get("stderr") or ""),
        sink="stderr",
    )
    left_exit = left_run.get("returncode")
    right_exit = right_run.get("returncode")
    if left_exit != 0 or right_exit != 0:
        confirmed = False
        reason = "program_exit_nonzero"
    elif not stdout_equal or not stderr_equal:
        confirmed = True
        reason = "observable_output_diff"
    else:
        confirmed = False
        reason = "no_observable_output_diff"
    return {
        "confirmed": confirmed,
        "reason": reason,
        "stdin": stdin,
        "inputs": ordered_inputs,
        "input_schema": specs,
        "nan_payload_preserved": nan_payload_preserved,
        "left": left_run,
        "right": right_run,
        "left_runs": left_runs,
        "right_runs": right_runs,
        "comparison": {
            "stdout": stdout_comparison,
            "stderr": stderr_comparison,
            "float_zero_sign_insensitive": bool(
                stdout_comparison.get("zero_sign_normalization")
                or stderr_comparison.get("zero_sign_normalization")
            ),
        },
        "query_revalidation": query_revalidation,
    }


def replay_confirms_defined_execution(replay: dict[str, Any]) -> bool:
    """Check stable, successful execution even when observable output agrees."""
    left_runs = replay.get("left_runs") or []
    right_runs = replay.get("right_runs") or []
    runs = list(left_runs) + list(right_runs)
    return bool(
        replay.get("stdin") is not None
        and len(left_runs) == 2
        and len(right_runs) == 2
        and replay.get("comparison") is not None
        and all(
            run.get("completed")
            and run.get("returncode") == 0
            for run in runs
        )
    )


def audit_domain_witness(
    source_paths: list[Path],
    target_paths: list[Path],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Replay a path-union difference and classify its definedness evidence."""
    witness_inputs = evidence.get("witness_inputs") or []
    audit: dict[str, Any] = {
        "direction": evidence.get("direction"),
        "query_path": evidence.get("query_path"),
        "query_sha256": evidence.get("query_sha256"),
        "witness_schema_complete": bool(evidence.get("witness_schema_complete")),
        "witness_inputs": witness_inputs,
        "replay": None,
        "classification": "unconfirmed",
        "reason": "",
        "definedness_confirmed": False,
        "supports_neq": False,
    }
    if not source_paths or not target_paths:
        audit["reason"] = "missing_path_side"
        return audit
    if not witness_inputs:
        audit["reason"] = "witness_inputs_unavailable"
        return audit

    replay = replay_counterexample(
        source_paths[0],
        target_paths[0],
        {"inputs": witness_inputs},
    )
    audit["replay"] = replay
    reason = str(replay.get("reason") or "")
    if reason in {
        "counterexample_inputs_unavailable",
        "binary_unavailable",
        "binary_identity_error",
        "replay_input_invalid",
        "replay_failed",
    }:
        audit["reason"] = reason
        return audit
    if reason == "repeated_execution_unstable":
        audit["classification"] = "unstable"
        audit["reason"] = reason
        return audit

    left = replay.get("left") or {}
    right = replay.get("right") or {}
    if not left.get("completed") or not right.get("completed"):
        audit["reason"] = "process_execution_incomplete"
        return audit

    left_rc = int(left.get("returncode", 0) or 0)
    right_rc = int(right.get("returncode", 0) or 0)
    left_signal = left_rc < 0
    right_signal = right_rc < 0
    stdout_equal = left.get("stdout") == right.get("stdout")
    stderr_equal = left.get("stderr") == right.get("stderr")
    observables_equal = stdout_equal and stderr_equal

    if left_signal or right_signal:
        audit["classification"] = (
            "both_ub_candidate"
            if left_signal and right_signal
            else "one_sided_ub_candidate"
        )
        audit["reason"] = "fatal_signal_requires_object_or_diagnostic_confirmation"
        return audit

    if left_rc == 0 and right_rc == 0:
        if observables_equal:
            audit["classification"] = "artifact_coverage_defect"
            audit["reason"] = "both_defined_with_identical_observables"
        else:
            audit["classification"] = "observable_mismatch"
            audit["reason"] = "both_defined_with_observable_difference"
            audit["definedness_confirmed"] = True
            audit["supports_neq"] = True
        return audit

    if left_rc == 0 or right_rc == 0:
        audit["classification"] = "definedness_mismatch"
        audit["reason"] = "one_side_defined_success_other_defined_rejection"
        audit["definedness_confirmed"] = True
        audit["supports_neq"] = True
        return audit

    if left_rc != right_rc or not observables_equal:
        audit["classification"] = "defined_rejection_mismatch"
        audit["reason"] = "both_sides_defined_with_different_rejection_or_output"
        audit["definedness_confirmed"] = True
        audit["supports_neq"] = True
    else:
        audit["classification"] = "defined_same_outcome"
        audit["reason"] = "both_sides_defined_with_identical_observables"
    return audit


def program_domain_counterexample(
    source_paths: list[Path],
    target_paths: list[Path],
) -> dict[str, Any]:
    """Try stable concrete boundary/standard seeds before path traversal."""
    if not source_paths or not target_paths:
        return {
            "counterexample": None,
            "reason": "no_paths",
            "seeds_tested": 0,
            "seeds_available": 0,
            "observations": [],
        }
    left = source_paths[0]
    right = target_paths[0]
    ctx = Context()
    try:
        left_constraint = parse_formula(left, ctx)
        right_constraint = parse_formula(right, ctx)
    except Exception:
        return {
            "counterexample": None,
            "reason": "input_spec_unavailable",
            "seeds_tested": 0,
            "seeds_available": 0,
            "observations": [],
        }
    specs = merge_input_specs(
        complete_input_specs_for_paths(left.parent, left, right),
        concrete_input_specs(
            collect_variables(left_constraint, right_constraint)
        ),
    )
    if not specs:
        return {
            "counterexample": None,
            "reason": "input_spec_unavailable",
            "seeds_tested": 0,
            "seeds_available": 0,
            "observations": [],
        }

    seeds = standard_input_seeds(specs)
    observations = []
    for seed in seeds:
        replay = replay_counterexample(
            left,
            right,
            {"inputs": seed},
        )
        if replay.get("confirmed"):
            record = {
                "source": left.stem,
                "target": right.stem,
                "rank": 1,
                "counterexample": {"inputs": seed},
                "replay": replay,
                "counterexample_source": "standard_domain_seed_replay",
                "seeds_tested": len(observations) + 1,
                "seeds_available": len(seeds),
                "observations": observations,
            }
            record["evidence_path"] = persist_confirmed_evidence(
                record,
                evidence_type="standard_domain_replay",
            )
            return record
        observations.append(
            {
                "inputs": seed,
                "confirmed": False,
                "reason": replay.get("reason"),
            }
        )
    return {
        "counterexample": None,
        "reason": "no_confirmed_counterexample",
        "seeds_tested": len(seeds),
        "seeds_available": len(seeds),
        "observations": observations,
    }


def binary_for_path(path: Path) -> Path | None:
    stem = "symbolic_oldV" if path.stem.startswith("symbolic_oldV") else "symbolic_newV"
    side = "old" if stem == "symbolic_oldV" else "new"
    identity = _ACTIVE_ARTIFACT_IDENTITY.get()
    if identity is not None:
        side_identity = identity.get(side) or {}
        paths_dir = Path(str(side_identity.get("paths_dir") or "")).resolve()
        if path.resolve().parent != paths_dir:
            raise ArtifactIdentityError(
                f"{side}_path_is_outside_manifest_paths_dir"
            )
        expected = Path(
            str(side_identity.get("binary_path") or "")
        ).resolve()
        if not expected.is_file():
            raise ArtifactIdentityError(
                f"{side}_manifest_binary_missing:{expected}"
            )
        actual_hash = identity_sha256_file(expected)
        if actual_hash != side_identity.get("binary_sha256"):
            raise ArtifactIdentityError(
                f"{side}_manifest_binary_sha256_changed_before_replay"
            )
        return expected
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


def output_segments_for_sink(
    summary: dict[str, Any] | None,
    sink: str,
) -> list[dict[str, Any]] | None:
    if summary is None:
        return None
    segments = flatten_output_segments(summary)
    if segments is None:
        return None
    return [
        segment
        for segment in segments
        if (
            str(segment.get("sink") or "stdio") == "stderr"
            if sink == "stderr"
            else str(segment.get("sink") or "stdio") != "stderr"
        )
    ]


def structured_output_tokens(
    summary: dict[str, Any] | None,
    text: str,
    *,
    sink: str,
) -> list[tuple[dict[str, Any], str | None]] | None:
    """Parse one replay stream using path-output type metadata."""
    selected = output_segments_for_sink(summary, sink)
    if selected is None:
        return None
    if not selected:
        return [] if text == "" else None
    parts: list[str] = []
    descriptors: list[dict[str, Any]] = []
    group_index = 0
    for segment in selected:
        kind = str(segment.get("kind") or "")
        if kind == "text":
            parts.append(re.escape(str(segment.get("value") or "")))
            continue
        if kind != "formatted_value":
            return None
        parts.append(r"(\S+)")
        descriptors.append(segment)
        group_index += 1
    match = re.fullmatch("".join(parts), text, flags=re.DOTALL)
    if match is None or group_index != len(match.groups()):
        return None
    return [
        (segment, group)
        for segment, group in zip(descriptors, match.groups())
    ]


def replay_streams_equivalent(
    left_summary: dict[str, Any] | None,
    right_summary: dict[str, Any] | None,
    left_text: str,
    right_text: str,
    *,
    sink: str,
) -> tuple[bool, dict[str, Any]]:
    if left_text == right_text:
        return True, {"method": "exact_text", "zero_sign_normalization": False}
    normalized_text_equal = (
        normalize_numeric_signed_zero_text(left_text)
        == normalize_numeric_signed_zero_text(right_text)
    )
    if normalized_text_equal:
        return True, {
            "method": "text_numeric_zero_normalization",
            "zero_sign_normalization": True,
        }
    left_layout = output_segments_for_sink(left_summary, sink)
    right_layout = output_segments_for_sink(right_summary, sink)
    if left_layout is None or right_layout is None:
        return False, {
            "method": "exact_text_fallback",
            "zero_sign_normalization": False,
        }
    if len(left_layout) != len(right_layout):
        return False, {"method": "structured_output", "zero_sign_normalization": False}
    for left_meta, right_meta in zip(left_layout, right_layout):
        if str(left_meta.get("kind") or "") != str(right_meta.get("kind") or ""):
            return False, {"method": "structured_output", "zero_sign_normalization": False}
        if left_meta.get("kind") == "text":
            if left_meta.get("value") != right_meta.get("value"):
                return False, {"method": "structured_output", "zero_sign_normalization": False}
        elif (
            left_meta.get("specifier") != right_meta.get("specifier")
            or int(left_meta.get("bits", 0) or 0)
            != int(right_meta.get("bits", 0) or 0)
        ):
            return False, {"method": "structured_output", "zero_sign_normalization": False}
    left_tokens = structured_output_tokens(left_summary, left_text, sink=sink)
    right_tokens = structured_output_tokens(right_summary, right_text, sink=sink)
    if left_tokens is None or right_tokens is None:
        return False, {"method": "exact_text_fallback", "zero_sign_normalization": False}
    if len(left_tokens) != len(right_tokens):
        return False, {"method": "structured_output", "zero_sign_normalization": False}
    normalized = False
    for (left_meta, left_token), (right_meta, right_token) in zip(
        left_tokens,
        right_tokens,
    ):
        if left_token is None or right_token is None:
            return False, {"method": "structured_output", "zero_sign_normalization": normalized}
        left_float = is_float_observable(left_meta)
        right_float = is_float_observable(right_meta)
        if left_float != right_float:
            return False, {"method": "structured_output", "zero_sign_normalization": normalized}
        if (
            left_float
            or float_text_token_looks_float(left_token)
            or float_text_token_looks_float(right_token)
        ) and (
            float_text_token_is_zero(left_token)
            and float_text_token_is_zero(right_token)
        ):
            normalized = True
            continue
        if left_token != right_token:
            return False, {"method": "structured_output", "zero_sign_normalization": normalized}
    return True, {"method": "structured_output", "zero_sign_normalization": normalized}


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
        name for name in declared if name.startswith(expected_name + "_")
    ]
    return matching[0] if len(matching) == 1 else None


@lru_cache(maxsize=4096)
def _smt_defined_expr_signature(
    smt_text: str,
    definition_variable: str,
) -> tuple[Any, ...] | None:
    """Return a canonical signature for a summary-defined SMT expression."""
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
    expression: ExprRef,
    *,
    definition_variable: str,
) -> tuple[Any, ...]:
    if is_app(expression) and expression.num_args() == 0:
        if is_bv_value(expression):
            return (
                "const",
                "bitvec",
                int(expression.size()),
                int(expression.as_long()),
            )
        if is_int_value(expression):
            return ("const", "int", str(expression))
        if is_fp_value(expression):
            return (
                "const",
                "fp",
                str(expression.sort()),
                expression.sexpr(),
            )
        name = (
            "__SUMMARY_VALUE__"
            if str(expression) == definition_variable
            else str(expression)
        )
        return ("symbol", name, str(expression.sort()))
    if is_app(expression):
        return (
            "app",
            str(expression.decl().name()),
            str(expression.sort()),
            tuple(
                _canonical_expr_signature(
                    expression.arg(index),
                    definition_variable=definition_variable,
                )
                for index in range(expression.num_args())
            ),
        )
    if is_quantifier(expression):
        return ("quantifier", expression.sexpr())
    return ("other", expression.sexpr())


def check_input_coverage(old_path: Path, covering_new_paths: list[Path], timeout_ms: int) -> tuple[bool | None, float]:
    if not covering_new_paths:
        return False, 0.0
    old_text = exact_path_condition_text(old_path)
    if any(
        old_text == exact_path_condition_text(path)
        for path in covering_new_paths
    ):
        return True, 0.0
    old_signature = exact_path_condition_signature(old_path)
    if old_signature is not None and any(
        old_signature == exact_path_condition_signature(path)
        for path in covering_new_paths
    ):
        return True, 0.0
    start = time.perf_counter()
    ctx = Context()
    old_formula = parse_formula(old_path, ctx)
    cover_formulas = [parse_formula(path, ctx) for path in covering_new_paths]
    cover_formula = Or(*cover_formulas)
    solver = Solver(ctx=ctx)
    solver.set("timeout", timeout_ms)
    solver.add(old_formula, Not(cover_formula))
    domain_constraints = add_active_domain_constraints(
        solver,
        ctx,
        old_formula,
        cover_formula,
    )
    status = solver.check()
    elapsed = time.perf_counter() - start
    persist_smt_query(
        solver,
        stage="source_input_coverage",
        timeout_ms=timeout_ms,
        elapsed=elapsed,
        status=status,
        path_ids=[old_path.stem, *(path.stem for path in covering_new_paths)],
        details={
            "input_ranges": configured_input_ranges(),
            "domain_constraint_count": len(domain_constraints),
        },
    )
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


def compact_union_query(
    source_paths: list[Path],
    target_paths: list[Path],
) -> tuple[Any, list[dict[str, Any]]] | None:
    """Build a compact exact union query when the active contract is known."""
    contract = _ACTIVE_INPUT_CONTRACT.get()
    if not contract or contract.get("status") != "supported":
        return None
    source_texts = [
        path.read_text(encoding="utf-8", errors="replace")
        for path in source_paths
    ]
    target_texts = [
        path.read_text(encoding="utf-8", errors="replace")
        for path in target_paths
    ]
    (
        domain_expressions,
        selected_inputs,
        domain_declarations,
    ) = extract_domain_expressions(
        [*source_texts, *target_texts],
        contract,
    )
    query = build_path_union_query(
        source_texts,
        target_texts,
        extra_domain_expressions=domain_expressions,
        extra_declarations=domain_declarations,
    )
    if query.unsupported_commands or not query.text:
        return None
    return query, selected_inputs


def compact_query_variables(
    selected_inputs: list[dict[str, Any]],
    ctx: Context,
) -> list[Any]:
    variables = []
    for item in selected_inputs:
        name = str(item["name"])
        bits = int(item["bits"])
        if item["kind"] == "float":
            if "FloatingPoint" in str(item["sort"]):
                sort = (
                    FPSort(11, 53, ctx=ctx)
                    if bits == 64
                    else FPSort(8, 24, ctx=ctx)
                )
                variable = FP(name, sort, ctx=ctx)
            else:
                variable = BitVec(name, bits, ctx=ctx).raw_to_fp()
        else:
            variable = BitVec(name, bits, ctx=ctx)
        variables.append(variable)
    return variables


def check_union_coverage_evidence(
    source_paths: list[Path],
    target_paths: list[Path],
    timeout_ms: int,
    *,
    direction: str,
    input_ranges: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check one inclusion direction and preserve a complete SAT/unknown query."""
    source_ids = [path.stem for path in source_paths]
    target_ids = [path.stem for path in target_paths]
    effective_input_ranges = configured_input_ranges() or input_ranges
    evidence: dict[str, Any] = {
        "direction": direction,
        "query": "source_union_minus_target_union",
        "source_paths": source_ids,
        "target_paths": target_ids,
        "input_ranges": effective_input_ranges,
    }
    if not source_paths:
        return {
            **evidence,
            "status": "unsat",
            "subset": True,
            "method": "empty_source_union",
            "elapsed_seconds": 0.0,
            "query_path": None,
            "query_sha256": None,
        }
    if sorted(exact_path_condition_text(path) for path in source_paths) == sorted(
        exact_path_condition_text(path) for path in target_paths
    ):
        return {
            **evidence,
            "status": "unsat",
            "subset": True,
            "method": "exact_path_condition_text_identity",
            "elapsed_seconds": 0.0,
            "query_path": None,
            "query_sha256": None,
        }
    source_signatures = [
        exact_path_condition_signature(path) for path in source_paths
    ]
    target_signatures = [
        exact_path_condition_signature(path) for path in target_paths
    ]
    if (
        all(signature is not None for signature in source_signatures)
        and all(signature is not None for signature in target_signatures)
        and sorted(source_signatures, key=repr)
        == sorted(target_signatures, key=repr)
    ):
        return {
            **evidence,
            "status": "unsat",
            "subset": True,
            "method": "canonical_path_ast_identity",
            "elapsed_seconds": 0.0,
            "query_path": None,
            "query_sha256": None,
        }

    start = time.perf_counter()
    ctx = Context()
    compact_details: dict[str, Any] = {
        "used": False,
        "error": None,
    }
    query_text: str | None = None
    model_variables: list[Any] = []
    compact_specs: tuple[tuple[str, str, int, int], ...] | None = None
    compact = None
    compact_error: Exception | None = None
    try:
        compact = compact_union_query(source_paths, target_paths)
    except Exception as exc:  # noqa: BLE001
        compact_error = exc
    if compact is not None:
        compact_query, selected_inputs = compact
        solver = Solver(ctx=ctx)
        solver.from_string(compact_query.text)
        solver.set("timeout", timeout_ms)
        query_text = compact_query.text
        domain_constraints = []
        model_variables = compact_query_variables(selected_inputs, ctx)
        contract = _ACTIVE_INPUT_CONTRACT.get() or {}
        compact_specs = tuple(
            (
                str(item["name"]),
                str(item["kind"]),
                int(item["bits"]),
                int(item.get("precision", 0) or 0),
            )
            for item in contract.get("inputs") or []
        )
        compact_details = {
            "used": True,
            "error": None,
            "query_bytes": len(compact_query.text.encode("utf-8")),
            "declarations": len(compact_query.declarations),
            "selected_inputs": selected_inputs,
        }
    else:
        source_formulas = [
            parse_formula(path, ctx) for path in source_paths
        ]
        target_formulas = [
            parse_formula(path, ctx) for path in target_paths
        ]
        source_formula = Or(*source_formulas)
        target_formula = (
            Or(*target_formulas)
            if target_formulas
            else BoolVal(False, ctx=ctx)
        )
        solver = Solver(ctx=ctx)
        solver.set("timeout", timeout_ms)
        solver.add(source_formula, Not(target_formula))
        domain_constraints = add_active_domain_constraints(
            solver,
            ctx,
            source_formula,
            target_formula,
        )
        model_variables = collect_variables(
            source_formula,
            target_formula,
        )
        compact_details["error"] = (
            f"{type(compact_error).__name__}: {compact_error}"
            if compact_error is not None
            else "compact_query_unavailable"
        )
    status = solver.check()
    elapsed = time.perf_counter() - start
    solver_elapsed = sum(
        float(attempt.get("elapsed_seconds", 0.0) or 0.0)
        for attempt in solver.last_attempts()
    )
    if status == unsat:
        subset: bool | None = True
    elif status == sat:
        subset = False
    else:
        subset = None
    persisted = persist_smt_query(
        solver,
        stage=f"global_input_space:{direction}",
        timeout_ms=timeout_ms,
        elapsed=elapsed,
        status=status,
        path_ids=[*source_ids, *target_ids],
        details={
            "direction": direction,
            "input_ranges": effective_input_ranges,
            "domain_constraint_count": len(domain_constraints),
            "compact_query": compact_details,
            "solver_elapsed_seconds": solver_elapsed,
            "preparation_seconds": max(0.0, elapsed - solver_elapsed),
        },
        force=True,
        query_text=query_text,
    )
    model = solver.model() if status == sat else None
    witness_inputs: list[dict[str, Any]] = []
    witness_schema_complete = False
    if model is not None:
        specs = compact_specs
        if specs is None:
            schema_dir = source_paths[0].parent
            specs = complete_input_specs_for_paths(
                schema_dir,
                *source_paths,
                *target_paths,
            )
        witness_inputs = complete_inputs_from_model(
            model,
            model_variables,
            specs,
        )
        witness_schema_complete = bool(specs and witness_inputs)
    return {
        **evidence,
        "status": str(status),
        "subset": subset,
        "method": "smt_union_exclusion",
        "representation": (
            "compact_smt_lib_union"
            if compact_details["used"]
            else "z3_ast_union"
        ),
        "elapsed_seconds": elapsed,
        "query_path": persisted.get("query_path") if persisted else None,
        "query_sha256": persisted.get("query_sha256") if persisted else None,
        "reason_unknown": persisted.get("reason_unknown") if persisted else "",
        "model": str(model) if model is not None else None,
        "witness_inputs": witness_inputs,
        "witness_schema_complete": witness_schema_complete,
    }


def check_union_coverage(source_paths: list[Path], target_paths: list[Path], timeout_ms: int) -> tuple[bool | None, float]:
    evidence = check_union_coverage_evidence(
        source_paths,
        target_paths,
        timeout_ms,
        direction="source_subset_targets",
    )
    return evidence["subset"], float(evidence["elapsed_seconds"])


def filter_definitely_unsat_paths(
    paths: list[Path], timeout_ms: int
) -> tuple[list[Path], list[str], list[str], float]:
    """Deprecated diagnostic helper; never called by formal verification.

    Round 13 removed the independent per-path feasibility traversal from both
    normal and explicit complete-matching modes.  The verifier keeps raw path
    artifacts and lets overlap/coverage/semantic queries handle feasibility.
    This function remains only for historical test compatibility.
    """
    feasible: list[Path] = []
    unsat_paths: list[str] = []
    unknown_paths: list[str] = []
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
            unsat_paths.append(path.stem)
        else:
            feasible.append(path)
            if status != sat:
                unknown_paths.append(path.stem)
    return feasible, unsat_paths, unknown_paths, elapsed_total


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


def check_source_feasibility(
    path: Path,
    timeout_ms: int,
) -> tuple[str, float, dict[str, Any]]:
    """Prove one source path non-vacuous or vacuous under the active domain."""
    started = time.perf_counter()
    context = Context()
    formula = parse_formula(path, context)
    solver = Solver(ctx=context)
    solver.set("timeout", timeout_ms)
    solver.add(formula)
    domain_constraints = add_active_domain_constraints(
        solver,
        context,
        formula,
    )
    status = str(solver.check())
    elapsed = time.perf_counter() - started
    persisted = persist_smt_query(
        solver,
        stage="source_feasibility",
        timeout_ms=timeout_ms,
        elapsed=elapsed,
        status=status,
        path_ids=[path.stem],
        details={
            "input_ranges": configured_input_ranges(),
            "domain_constraint_count": len(domain_constraints),
        },
        force=True,
    )
    return status, elapsed, persisted or {}


def summarize_required_obligations(source_ids, records, direction):
    """Derive final obligations from per-source coverage and semantic evidence.

    A result flag or an empty processed prefix is never a proof. An individual
    target union need not be contained in its source: the other direction has
    its own independent obligations.
    """
    required, errors = [], []
    by_source = {}
    for record in records:
        source = record.get("query")
        if source not in source_ids or source in by_source:
            errors.append({"direction": direction, "source": source,
                           "reason": "unexpected_or_duplicate_source_record"})
        by_source[source] = record
    for source in source_ids:
        record = by_source.get(source)
        selected = record.get("match", []) if record else []
        selected = [selected] if isinstance(selected, str) else selected
        selected = selected if isinstance(selected, list) else []
        vacuous = bool(record and record.get("coverage_obligation_vacuous") is True
                       and record.get("source_feasibility") == "unsat")
        coverage = bool(record and selected and
                        record.get("source_subset_targets") is True)
        checks = (record or {}).get("semantic_checks", [])
        checks = checks if isinstance(checks, list) else []
        checks_by_target = {item.get("target"): item for item in checks}
        semantic = bool(coverage and all(
            checks_by_target.get(target, {}).get("equivalent") is True
            for target in selected))
        if record and record.get("coverage_obligation_vacuous") and not vacuous:
            errors.append({"direction": direction, "source": source,
                           "reason": "vacuity_without_unsat_evidence"})
        if record and record.get("matched") is True and not coverage:
            errors.append({"direction": direction, "source": source,
                           "reason": "matched_without_coverage_evidence"})
        for kind, proven in (("coverage", coverage), ("semantics", semantic)):
            reason = None
            if not (vacuous or proven):
                if record is None:
                    reason = "source_not_processed"
                elif kind == "coverage":
                    reason = ("coverage_query_unknown" if
                              record.get("source_subset_targets") is None or
                              record.get("coverage_status") == "coverage_unknown"
                              else "source_not_covered")
                elif not coverage:
                    reason = "no_complete_semantic_cover"
                elif any(checks_by_target.get(t, {}).get("equivalent") is False
                         for t in selected):
                    reason = "semantic_difference_unresolved"
                else:
                    reason = "semantic_query_unknown_or_missing_evidence"
            required.append({
                "obligation_id": f"{direction}:{source}:{kind}",
                "direction": direction, "source": source, "kind": kind,
                "targets": selected, "status": "discharged" if vacuous or proven else "unresolved",
                "basis": "source_unsat" if vacuous else
                         "source_subset_selected_union" if proven and kind == "coverage" else
                         "all_selected_overlaps_equivalent" if proven else None,
                "reason": reason,
                "semantic_evidence": checks if kind == "semantics" and not proven else [],
            })
    unresolved = [item for item in required if item["status"] == "unresolved"]
    return {
        "required_obligations": required,
        "unresolved_required_obligations": unresolved,
        "unresolved_required_obligation_count": len(unresolved),
        "proof_accounting_errors": errors,
        "success": not unresolved and not errors,
        "matching_complete": not errors and not any(
            item["kind"] == "coverage" for item in unresolved),
    }


def historical_unknown_summary(obligations, direction=None):
    """Count actual UNKNOWN query events, preserving their original identity."""
    events = []
    discharged = []
    for event in _SMT_AUDIT_EVENTS.get() or []:
        if str(event.get("status")) in {"sat", "unsat"}:
            continue
        context = event.get("proof_context") or {}
        if direction is not None and context.get("direction") != direction:
            continue
        row = {key: event.get(key) for key in (
            "sequence", "stage", "status", "reason_unknown", "path_ids",
            "query_path", "query_sha256", "proof_context")}
        row["event_id"] = f"{_SMT_AUDIT_DIR.get()}:{event.get('sequence')}"
        events.append(row)
        related = [item for item in obligations
                   if item["direction"] == context.get("direction")
                   and item.get("source") == context.get("source")]
        if related and all(item["status"] == "discharged" for item in related):
            discharged.append({"event_id": row["event_id"],
                               "query_status": row["status"],
                               "resolution": "final_obligations_proven_by_alternative_evidence",
                               "obligation_ids": [item["obligation_id"] for item in related]})
    return {"unknowns_role": "legacy_diagnostic_only",
            "historical_unknown_query_count": len(events),
            "historical_unknown_events": events,
            "historical_unknown_scope": "recorded_logical_query_results_not_backend_attempts",
            "discharged_historical_unknown_events": discharged}


def abstract_difference_candidates(records):
    """A replay seed from a SAT overlap is not a semantic difference witness."""
    found = []
    for record in records:
        for item in record.get("semantic_checks", []) or record.get("intersections", []):
            details = item.get("details") or {}
            for component, key, result_key in (
                ("return_value", "counterexample", "return_value_equivalent"),
                ("program_output", "output_counterexample", "program_output_equivalent"),
                ("global_state", "global_counterexample", "global_state_equivalent"),
            ):
                candidate = details.get(key)
                if details.get(result_key) is False and candidate:
                    found.append({"source": record.get("query"), "target": item.get("target"),
                                  "component": component, "counterexample": candidate})
    return found


def classify_directional_failure(proof, candidates):
    if proof["proof_accounting_errors"]:
        return "proof_accounting_inconsistent"
    if candidates:
        return "abstract_mismatch_without_confirmed_replay"
    unresolved = proof["unresolved_required_obligations"]
    if any(item["kind"] == "coverage" for item in unresolved):
        return "matching_incomplete"
    if unresolved:
        return "semantic_checks_incomplete"
    return "proof_accounting_inconsistent"


def verify_directional_cover(
    source_paths: list[Path],
    target_paths: list[Path],
    ranking: dict[str, list[str]],
    timeout_ms: int,
    truth_pairs: dict[str, set[str]] | None = None,
    allow_one_to_many: bool = True,
    direction: str = "old_to_new",
) -> dict[str, Any]:
    """Match source paths using the historical one-target or union ablation.

    ``allow_one_to_many=False`` is the historical ``--one-to-one-only``
    baseline: a source path may select at most one target, and a one-target
    source-subset-target relation is valid. It does not impose global
    injectivity, so different source paths may reuse a target. The reverse
    direction is checked independently by the caller.
    """
    source_by_id = path_index(source_paths)
    source_items = list(source_by_id.items())
    target_by_id = path_index(target_paths)
    default_targets = [path.stem for path in target_paths]
    matched_targets: set[str] = set()
    records: list[dict[str, Any]] = []
    smt_calls = 0
    t_smt = 0.0
    unknowns = 0
    semantic_modes: dict[str, int] = {}
    confirmed_mismatches: list[dict[str, Any]] = []
    feasibility_cache: dict[
        str,
        tuple[str, float, dict[str, Any]],
    ] = {}
    failed_source_count = 0
    bulk_prefilter = {
        "triggered": False,
        "checked_sources": 0,
        "unsat_sources": 0,
        "unknown_sources": 0,
        "elapsed_seconds": 0.0,
    }

    for source_index, (source_id, source_path) in enumerate(source_items):
        candidates = ranking.get(source_id, default_targets)
        compatible: list[str] = []
        compatible_ranks: list[int] = []
        intersections: list[dict[str, Any]] = []
        semantic_checks: list[dict[str, Any]] = []
        exact_equal = False
        intersection_verified = False
        equality_details: dict[str, bool | None] = {
            "source_subset_targets": False,
            "targets_subset_source": None,
        }
        candidate_unknowns = 0
        feasibility_status: str | None = None
        feasibility_elapsed = 0.0
        feasibility_persisted: dict[str, Any] = {}
        vacuous_source = False
        unsat_intersection_count = 0
        cached_feasibility = feasibility_cache.get(source_id)
        if cached_feasibility is not None:
            (
                feasibility_status,
                feasibility_elapsed,
                feasibility_persisted,
            ) = cached_feasibility
            if feasibility_status == "unsat":
                vacuous_source = True
                records.append(
                    {
                        "query": source_id,
                        "match": [],
                        "rank": [],
                        "matched": False,
                        "coverage_obligation_vacuous": True,
                        "source_feasibility": feasibility_status,
                        "source_feasibility_elapsed_seconds": (
                            feasibility_elapsed
                        ),
                        "source_feasibility_query_path": (
                            feasibility_persisted.get("query_path")
                        ),
                        "source_feasibility_query_sha256": (
                            feasibility_persisted.get("query_sha256")
                        ),
                        "match_type": "vacuous_source",
                        "input_space_equal_with_match": False,
                        "intersection_verified": False,
                        "source_subset_targets": False,
                        "targets_subset_source": None,
                        "intersections": [],
                    }
                )
                continue

        for rank, target_id in enumerate(candidates, 1):
            target_path = target_by_id.get(target_id)
            if target_path is None:
                continue
            equivalent, elapsed, calls, semantic_details = proof_query_call(
                "semantics", direction, source_id, [target_id], verify_semantic_path_relation,
                source_path,
                target_path,
                timeout_ms,
                direction=direction,
            )
            smt_calls += calls
            t_smt += elapsed
            mode = str(semantic_details.get("semantic_mode", "unknown"))
            semantic_modes[mode] = semantic_modes.get(mode, 0) + 1

            if truth_pairs is not None:
                equivalent = target_id in truth_pairs.get(source_id, set())
            semantic_checks.append({"target": target_id, "equivalent": equivalent,
                                    "details": semantic_details})

            overlap = semantic_details.get("input_overlap")
            if overlap == "unsat":
                unsat_intersection_count += 1
                should_probe = (
                    feasibility_status is None
                    and (
                        unsat_intersection_count
                        >= SOURCE_FEASIBILITY_UNSAT_THRESHOLD
                        or rank >= len(candidates)
                    )
                )
                if should_probe:
                    (
                        feasibility_status,
                        feasibility_elapsed,
                        feasibility_persisted,
                    ) = proof_query_call(
                        "feasibility", direction, source_id, [], check_source_feasibility,
                        source_path,
                        timeout_ms,
                    )
                    smt_calls += 1
                    t_smt += feasibility_elapsed
                    feasibility_decision = (
                        classify_source_feasibility(
                            feasibility_status
                        )
                    )
                    if feasibility_decision.coverage_obligation_vacuous:
                        vacuous_source = True
                        break
                continue
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
            if replay.get("confirmed") or semantic_details.get(
                "mismatch_confirmed"
            ):
                mismatch_record = {
                    "source": source_id,
                    "target": target_id,
                    "rank": rank,
                    "direction": direction,
                    "counterexample_source": "static_path_overlap_model",
                    "counterexample": (
                        semantic_details.get("counterexample")
                        or semantic_details.get("output_counterexample")
                        or semantic_details.get("global_counterexample")
                    ),
                    "replay": replay,
                    "mismatch_component": semantic_details.get(
                        "mismatch_component"
                    ),
                }
                mismatch_record = attach_candidate_identity(
                    mismatch_record,
                    query_kind="ranked_semantic_replay",
                    direction=direction,
                    logical_query_sha256=(
                        semantic_details.get("overlap_query_sha256")
                    ),
                )
                mismatch_record["evidence_path"] = persist_confirmed_evidence(
                    mismatch_record,
                    evidence_type="ranked_semantic_replay",
                )
                confirmed_mismatches.append(mismatch_record)
                # A single concretely replayed observable difference is
                # sufficient to authorize NEQ. Further coverage candidates
                # cannot overturn that witness and need not be explored.
                break

            if equivalent is None:
                candidate_unknowns += 1
                continue
            if equivalent is not True:
                continue

            if truth_pairs is None:
                candidate_ids = (
                    [*compatible, target_id]
                    if allow_one_to_many
                    else [target_id]
                )
                candidate_ranks = (
                    [*compatible_ranks, rank]
                    if allow_one_to_many
                    else [rank]
                )
                equal, equality_time, equality_details = proof_query_call(
                    "coverage", direction, source_id, candidate_ids, check_path_union_equal,
                    source_path,
                    [target_by_id[item] for item in candidate_ids],
                    timeout_ms,
                )
                smt_calls += 1
                t_smt += equality_time
                if equal is None:
                    unknowns += 1
                    # Only source inclusion is necessary in this direction.
                    if equality_details.get("source_subset_targets") is True:
                        compatible = candidate_ids
                        compatible_ranks = candidate_ranks
                        intersection_verified = True
                        break
                    if allow_one_to_many:
                        compatible = candidate_ids
                        compatible_ranks = candidate_ranks
                    continue
                if equal:
                    compatible = candidate_ids
                    compatible_ranks = candidate_ranks
                    exact_equal = True
                    break
                if equality_details.get("source_subset_targets") is True:
                    compatible = candidate_ids
                    compatible_ranks = candidate_ranks
                    intersection_verified = True
                    break
                if allow_one_to_many:
                    compatible = candidate_ids
                    compatible_ranks = candidate_ranks
            else:
                compatible = [target_id]
                compatible_ranks = [rank]
                exact_equal = True
                equality_details["source_subset_targets"] = True
                break

        if (
            not vacuous_source
            and not (
                bool(compatible)
                and (exact_equal or intersection_verified)
            )
            and feasibility_status is None
        ):
            (
                feasibility_status,
                feasibility_elapsed,
                feasibility_persisted,
            ) = proof_query_call("feasibility", direction, source_id, [],
                                 check_source_feasibility, source_path, timeout_ms)
            smt_calls += 1
            t_smt += feasibility_elapsed
            feasibility_decision = classify_source_feasibility(
                feasibility_status
            )
            if feasibility_decision.coverage_obligation_vacuous:
                vacuous_source = True

        matched = bool(compatible) and (exact_equal or intersection_verified)
        if matched:
            matched_targets.update(compatible)
        if not matched and not vacuous_source:
            if feasibility_status in {"unknown", "timeout", None}:
                if feasibility_status is not None:
                    unknowns += 1
            unknowns += candidate_unknowns
        if vacuous_source:
            match_type = "vacuous_source"
        elif not matched:
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
                "coverage_obligation_vacuous": vacuous_source,
                "source_feasibility": feasibility_status,
                "source_feasibility_elapsed_seconds": feasibility_elapsed,
                "source_feasibility_query_path": (
                    feasibility_persisted.get("query_path")
                ),
                "source_feasibility_query_sha256": (
                    feasibility_persisted.get("query_sha256")
                ),
                "match_type": match_type,
                "input_space_equal_with_match": exact_equal,
                "intersection_verified": intersection_verified,
                "source_subset_targets": equality_details.get("source_subset_targets"),
                "targets_subset_source": equality_details.get("targets_subset_source"),
                "intersections": intersections,
                "semantic_checks": semantic_checks,
            }
        )
        if not matched and not vacuous_source:
            failed_source_count += 1
            if (
                not bulk_prefilter["triggered"]
                and len(source_paths) * len(target_paths)
                >= SOURCE_FEASIBILITY_BULK_PRODUCT_THRESHOLD
                and failed_source_count
                >= SOURCE_FEASIBILITY_BULK_FAILURE_THRESHOLD
            ):
                bulk_prefilter["triggered"] = True
                for remaining_id, remaining_path in (
                    source_items[source_index + 1 :]
                ):
                    if remaining_id in feasibility_cache:
                        continue
                    (
                        remaining_status,
                        remaining_elapsed,
                        remaining_persisted,
                    ) = proof_query_call(
                        "feasibility", direction, remaining_id, [], check_source_feasibility,
                        remaining_path,
                        timeout_ms,
                    )
                    feasibility_cache[remaining_id] = (
                        remaining_status,
                        remaining_elapsed,
                        remaining_persisted,
                    )
                    smt_calls += 1
                    t_smt += remaining_elapsed
                    bulk_prefilter["checked_sources"] += 1
                    bulk_prefilter["elapsed_seconds"] += (
                        remaining_elapsed
                    )
                    if remaining_status == "unsat":
                        bulk_prefilter["unsat_sources"] += 1
                    elif remaining_status in {"unknown", "timeout"}:
                        bulk_prefilter["unknown_sources"] += 1
        if confirmed_mismatches:
            break

    coverage_counts: dict[str, int] = {}
    for record in records:
        key = str(record["match_type"])
        coverage_counts[key] = coverage_counts.get(key, 0) + 1
    proof = summarize_required_obligations(list(source_by_id), records, direction)
    return {
        **proof,
        **historical_unknown_summary(proof["required_obligations"], direction),
        "semantic_checks_complete": proof["success"],
        "source_count": len(source_paths),
        "processed_source_count": len(records),
        "matched_targets": matched_targets,
        "records": records,
        "smt_calls": smt_calls,
        "t_smt": t_smt,
        "unknowns": unknowns,
        "matched_source_count": sum(
            bool(record["matched"]) for record in records
        ),
        "vacuous_source_count": sum(
            bool(record["coverage_obligation_vacuous"])
            for record in records
        ),
        "coverage_status_counts": dict(sorted(coverage_counts.items())),
        "semantic_status_counts": dict(sorted(coverage_counts.items())),
        "source_feasibility_prefilter": bulk_prefilter,
        "matching_policy": (
            "multi_target_union"
            if allow_one_to_many
            else "single_target_reusable_source_subset"
        ),
        "target_reuse_allowed": True,
        "source_subset_allowed": True,
        "semantic_modes": semantic_modes,
        "confirmed_mismatches": confirmed_mismatches,
    }


def verify_complete_directional_cover(
    source_paths: list[Path],
    target_paths: list[Path],
    ranking: dict[str, list[str]],
    timeout_ms: int,
    truth_pairs: dict[str, set[str]] | None = None,
    allow_one_to_many: bool = True,
    direction: str = "old_to_new",
) -> dict[str, Any]:
    """Traverse every source for coverage, then record semantics separately."""
    source_by_id = path_index(source_paths)
    target_by_id = path_index(target_paths)
    default_targets = [path.stem for path in target_paths]
    records: list[dict[str, Any]] = []
    matched_targets: set[str] = set()
    confirmed_mismatches: list[dict[str, Any]] = []
    semantic_modes: dict[str, int] = {}
    smt_calls = 0
    t_smt = 0.0
    unknowns = 0

    for source_id, source_path in source_by_id.items():
        candidates = ranking.get(source_id, default_targets)
        selected: list[str] = []
        selected_ranks: list[int] = []
        candidate_evidence: list[dict[str, Any]] = []
        source_covered: bool | None = False
        targets_subset_source: bool | None = None
        coverage_status = "uncovered"
        saw_coverage_unknown = False

        for rank, target_id in enumerate(candidates, 1):
            target_path = target_by_id.get(target_id)
            if target_path is None:
                candidate_evidence.append(
                    {
                        "target": target_id,
                        "rank": rank,
                        "overlap": "missing_target_path",
                        "source_subset_targets": None,
                        "targets_subset_source": None,
                    }
                )
                continue
            overlap_status, overlap_time = proof_query_call(
                "overlap", direction, source_id, [target_id], verify_path_overlap,
                source_path,
                target_path,
                timeout_ms,
            )
            smt_calls += 1
            t_smt += overlap_time
            candidate_record: dict[str, Any] = {
                "target": target_id,
                "rank": rank,
                "overlap": str(overlap_status),
                "source_subset_targets": None,
                "targets_subset_source": None,
            }
            if overlap_status != sat:
                if overlap_status != unsat:
                    saw_coverage_unknown = True
                    candidate_record["coverage_state"] = "overlap_unknown"
                else:
                    candidate_record["coverage_state"] = "no_overlap"
                candidate_evidence.append(candidate_record)
                continue

            candidate_ids = (
                [*selected, target_id]
                if allow_one_to_many
                else [target_id]
            )
            candidate_ranks = (
                [*selected_ranks, rank]
                if allow_one_to_many
                else [rank]
            )
            equal, equality_time, equality_details = proof_query_call(
                "coverage", direction, source_id, candidate_ids, check_path_union_equal,
                source_path,
                [target_by_id[item] for item in candidate_ids],
                timeout_ms,
            )
            smt_calls += 1
            t_smt += equality_time
            source_covers = equality_details.get("source_subset_targets")
            target_covers = equality_details.get("targets_subset_source")
            candidate_record.update(
                {
                    "source_subset_targets": source_covers,
                    "targets_subset_source": target_covers,
                    "input_space_equal": equal,
                }
            )
            if source_covers is None:
                saw_coverage_unknown = True
                candidate_record["coverage_state"] = "coverage_unknown"
            elif source_covers is not True:
                candidate_record["coverage_state"] = "does_not_cover"
            else:
                selected = candidate_ids
                selected_ranks = candidate_ranks
                source_covered = True
                targets_subset_source = target_covers
                if targets_subset_source is True:
                    coverage_status = "covered_exact"
                elif targets_subset_source is False:
                    coverage_status = "covered_subset"
                else:
                    coverage_status = "covered_relation_unknown"
                candidate_record["coverage_state"] = coverage_status
                candidate_evidence.append(candidate_record)
                break
            candidate_evidence.append(candidate_record)
            if allow_one_to_many:
                selected = candidate_ids
                selected_ranks = candidate_ranks

        if not source_covered:
            source_covered = False
            coverage_status = (
                "coverage_unknown" if saw_coverage_unknown else "uncovered"
            )
            selected = []
            selected_ranks = []

        exact_equal = coverage_status == "covered_exact"
        intersection_verified = coverage_status in {
            "covered_exact",
            "covered_subset",
            "covered_relation_unknown",
        }
        if coverage_status == "covered_exact":
            match_type = (
                "one_to_one_exact"
                if len(selected) == 1
                else "one_to_many_exact_cover"
            )
        elif coverage_status == "covered_subset":
            match_type = (
                "one_to_one_source_subset_target"
                if len(selected) == 1
                else "one_to_many_source_subset_target_union"
            )
        elif coverage_status == "covered_relation_unknown":
            match_type = "coverage_relation_unknown"
        elif coverage_status == "coverage_unknown":
            match_type = "coverage_unknown"
        else:
            match_type = "unmatched"

        semantic_records: list[dict[str, Any]] = []
        semantic_complete = True
        semantic_all_equivalent = bool(source_covered and selected)
        source_confirmed_mismatch = False
        for target_id in selected:
            target_path = target_by_id[target_id]
            equivalent, elapsed, calls, semantic_details = proof_query_call(
                "semantics", direction, source_id, [target_id], verify_semantic_path_relation,
                source_path,
                target_path,
                timeout_ms,
                direction=direction,
            )
            smt_calls += calls
            t_smt += elapsed
            mode = str(semantic_details.get("semantic_mode", "unknown"))
            semantic_modes[mode] = semantic_modes.get(mode, 0) + 1
            semantic_records.append(
                {
                    "target": target_id,
                    "equivalent": equivalent,
                    "details": semantic_details,
                }
            )
            if equivalent is None:
                semantic_complete = False
                semantic_all_equivalent = False
                unknowns += 1
            elif equivalent is False:
                semantic_all_equivalent = False
                replay = semantic_details.get("replay") or {}
                if replay.get("confirmed"):
                    source_confirmed_mismatch = True
                    mismatch_record = {
                        "source": source_id,
                        "target": target_id,
                        "rank": selected_ranks[selected.index(target_id)],
                        "direction": direction,
                        "counterexample_source": "static_path_overlap_model",
                        "counterexample": (
                            semantic_details.get("counterexample")
                            or semantic_details.get("output_counterexample")
                        ),
                        "replay": replay,
                        "coverage_type": match_type,
                    }
                    mismatch_record = attach_candidate_identity(
                        mismatch_record,
                        query_kind="complete_ranked_semantic_replay",
                        direction=direction,
                        logical_query_sha256=(
                            semantic_details.get("overlap_query_sha256")
                        ),
                    )
                    mismatch_record["evidence_path"] = persist_confirmed_evidence(
                        mismatch_record,
                        evidence_type="complete_ranked_semantic_replay",
                    )
                    confirmed_mismatches.append(mismatch_record)

        if not selected:
            semantic_status = "no_coverage"
            semantic_complete = False
        elif semantic_all_equivalent:
            semantic_status = "all_equivalent"
        elif source_confirmed_mismatch:
            semantic_status = "confirmed_mismatch"
        elif any(item["equivalent"] is False for item in semantic_records):
            semantic_status = "unreplayed_mismatch"
        else:
            semantic_status = "unknown"
            semantic_complete = False

        if source_covered:
            matched_targets.update(selected)
        if coverage_status in {"coverage_unknown", "covered_relation_unknown"}:
            unknowns += 1
        records.append(
            {
                "query": source_id,
                "match": selected[0] if len(selected) == 1 else selected,
                "rank": (
                    selected_ranks[0]
                    if len(selected_ranks) == 1
                    else selected_ranks
                ),
                "matched": bool(source_covered),
                "coverage_success": bool(source_covered),
                "coverage_status": coverage_status,
                "matching_complete": coverage_status
                not in {"coverage_unknown", "covered_relation_unknown"},
                "match_type": match_type,
                "input_space_equal_with_match": exact_equal,
                "intersection_verified": intersection_verified,
                "source_subset_targets": source_covered,
                "targets_subset_source": targets_subset_source,
                "candidate_evidence": candidate_evidence,
                "semantic_status": semantic_status,
                "semantic_checks_complete": semantic_complete,
                "semantic_checks": semantic_records,
            }
        )

    coverage_counts = Counter(
        str(record["coverage_status"]) for record in records
    )
    semantic_counts = Counter(
        str(record["semantic_status"]) for record in records
    )
    source_count = len(source_by_id)
    processed_source_count = len(records)
    proof = summarize_required_obligations(list(source_by_id), records, direction)
    return {
        "covered": proof["matching_complete"],
        "semantic_checks_complete": proof["matching_complete"] and all(
            record["semantic_checks_complete"] for record in records),
        "semantic_all_equivalent": proof["success"],
        **proof,
        **historical_unknown_summary(proof["required_obligations"], direction),
        "source_count": source_count,
        "processed_source_count": processed_source_count,
        "coverage_status_counts": dict(sorted(coverage_counts.items())),
        "semantic_status_counts": dict(sorted(semantic_counts.items())),
        "matched_targets": matched_targets,
        "records": records,
        "smt_calls": smt_calls,
        "t_smt": t_smt,
        "unknowns": unknowns,
        "matched_source_count": sum(
            bool(record["matched"]) for record in records
        ),
        "matching_policy": (
            "multi_target_union"
            if allow_one_to_many
            else "single_target_reusable_source_subset"
        ),
        "target_reuse_allowed": True,
        "source_subset_allowed": True,
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
    left_regions = global_cells(left_state) or {}
    right_regions = global_cells(right_state) or {}
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
    """Return a unique exact 1:1 matching independent of serialization order.

    Path indices are not semantic identities: symbolic exploration may emit
    the same complete path set in a different order after an executor update.
    Matching first uses byte-identical path-condition text, then an exact
    canonical Z3 AST signature. The latter removes serializer-only ``let``
    names without normalizing values or algebraic expressions. Each match
    also requires exact return/output/global-state identity.
    """
    if not old_paths or len(old_paths) != len(new_paths):
        return None
    new_by_text: dict[str, list[Path]] = {}
    new_by_signature: dict[tuple[Any, ...] | None, list[Path]] = {}
    for new_path in new_paths:
        new_by_text.setdefault(
            exact_path_condition_text(new_path),
            [],
        ).append(new_path)
        signature = exact_path_condition_signature(new_path)
        if signature is not None:
            new_by_signature.setdefault(signature, []).append(new_path)

    pair_matches: dict[Path, list[Path]] = {}
    reverse_matches: dict[Path, list[Path]] = {}
    match_basis: dict[Path, str] = {}
    for old_path in old_paths:
        old_text = exact_path_condition_text(old_path)
        candidates = new_by_text.get(old_text, [])
        basis = "exact_path_condition_text"
        if not candidates:
            signature = exact_path_condition_signature(old_path)
            candidates = (
                new_by_signature.get(signature, [])
                if signature is not None
                else []
            )
            basis = "canonical_path_ast"
        compatible = [
            new_path
            for new_path in candidates
            if exact_path_semantics_identical(old_path, new_path)
        ]
        if not compatible:
            return None
        pair_matches[old_path] = compatible
        match_basis[old_path] = basis
        for new_path in compatible:
            reverse_matches.setdefault(new_path, []).append(old_path)

    if any(len(candidates) != 1 for candidates in pair_matches.values()):
        return None
    if len(reverse_matches) != len(new_paths):
        return None
    if any(len(candidates) != 1 for candidates in reverse_matches.values()):
        return None

    records = []
    for old_path in old_paths:
        new_path = pair_matches[old_path][0]
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
                "path_condition_identity": match_basis[old_path],
            }
        )
    return records


def exact_path_semantics_identical(
    old_path: Path,
    new_path: Path,
) -> bool:
    """Check exact path-level observables without normalizing values."""
    try:
        old_summary = extract_semantic_summary(old_path)
        new_summary = extract_semantic_summary(new_path)
        if old_summary is None or new_summary is None:
            return False
        if not return_expressions_identical(
            old_summary.get("return_value") or {},
            new_summary.get("return_value") or {},
        ):
            return False
        if not output_segments_identical(old_summary, new_summary):
            return False
        old_global = old_summary.get("global_state") or {}
        new_global = new_summary.get("global_state") or {}
        if (
            not old_global.get("available")
            or not new_global.get("available")
            or old_global.get("unresolved")
            or new_global.get("unresolved")
            or not global_regions_identical(old_global, new_global)
        ):
            return False
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return True


def exact_path_condition_text(path: Path) -> str:
    """Return the exact SMT formula text without benchmark metadata."""
    content = cached_path_text(path)
    marker = "\n; Path signature:"
    if marker in content:
        return content.split(marker, 1)[0]
    return content


def exact_path_condition_signature(
    path: Path,
) -> tuple[Any, ...] | None:
    """Return a serializer-independent structural signature for a path AST."""
    stat = path.stat()
    return _exact_path_condition_signature_cached(
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
    )


@lru_cache(maxsize=8192)
def _exact_path_condition_signature_cached(
    path_text: str,
    mtime_ns: int,
    size: int,
) -> tuple[Any, ...] | None:
    del mtime_ns, size
    path = Path(path_text)
    try:
        ctx = Context()
        formula = parse_formula(path, ctx)
        return _canonical_expr_signature(
            formula,
            definition_variable="",
        )
    except Exception:
        return None


def prescan_replayable_counterexample(
    source_paths: list[Path],
    target_paths: list[Path],
    ranking: dict[str, list[str]],
    timeout_ms: int,
    *,
    budget_ms: int = NEQ_PRESCAN_BUDGET_MS,
    direction: str = "old_to_new",
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
                "direction": direction,
            }
            records.append(record)
            replay = details.get("replay") or {}
            if replay.get("confirmed") or details.get(
                "mismatch_confirmed"
            ):
                counterexample = (
                    details.get("counterexample")
                    or details.get("output_counterexample")
                    or details.get("global_counterexample")
                    or details.get("static_model_counterexample")
                )
                record["counterexample"] = counterexample
                if isinstance(counterexample, dict) and isinstance(
                    counterexample.get("input_schema"),
                    list,
                ):
                    record["input_schema"] = counterexample["input_schema"]
                record["replay"] = replay
                record["mismatch_component"] = details.get(
                    "mismatch_component"
                )
                record["counterexample_source"] = (
                    "static_path_overlap_model"
                )
                record = attach_candidate_identity(
                    record,
                    query_kind="ranked_prescan_replay",
                    direction=direction,
                    logical_query_sha256=(
                        details.get("overlap_query_sha256")
                        or details.get("logical_query_sha256")
                    ),
                )
                record["evidence_path"] = persist_confirmed_evidence(
                    record,
                    evidence_type="ranked_prescan_replay",
                )
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


def exploration_is_complete(
    record: dict[str, Any] | None,
    *,
    path_count: int,
    require_proof_eligible: bool = True,
) -> bool:
    """Cross-check a completeness marker against the serialized path set."""
    if not isinstance(record, dict) or record.get("complete") is not True:
        return False
    if record.get("incomplete_reasons"):
        return False
    if require_proof_eligible and record.get("proof_eligible") is not True:
        return False
    for key in (
        "active_count",
        "timeout_count",
        "loop_bound_event_count",
        "recursion_depth_bound_event_count",
        "errored_count",
    ):
        if int(record.get(key, 0) or 0) != 0:
            return False
    declared_paths = record.get("terminating_path_count")
    if not isinstance(declared_paths, int) or declared_paths != path_count:
        return False
    max_paths = record.get("max_paths")
    if isinstance(max_paths, int) and path_count > max_paths:
        return False
    return True


def semantic_model_eq_audit(
    exploration: dict[str, Any],
) -> dict[str, Any]:
    """Apply Round017 model qualification without weakening legacy artifacts."""
    sides = (
        exploration.get("symbolic_oldV"),
        exploration.get("symbolic_newV"),
    )
    requires_audit = any(
        isinstance(record, dict)
        and (
            record.get("schema") == "symbolicana.exploration.v4"
            or "external_model_audit" in record
        )
        for record in sides
    )
    if not requires_audit:
        return {
            "schema": "symbolicana.round017.combined_semantic_model_audit.v1",
            "applicable": False,
            "side_count": 0,
            "validation_errors": [],
            "eq_blockers": ["legacy_artifact_has_no_semantic_model_audit"],
            "eq_eligible": True,
            "neq_replay_required_symbols": [],
            "neq_requires_current_static_candidate_and_replay": False,
            "legacy_artifact": True,
        }
    combined = combined_eq_audit(
        [
            (
                record.get("external_model_audit")
                if isinstance(record, dict)
                else None
            )
            for record in sides
        ]
    )
    combined["applicable"] = True
    modes = {(side.get("entry_state_contract") or {}).get("mode", "legacy_symbolic_globals")
             for side in sides if isinstance(side, dict)}
    if len(modes) != 1:
        combined["eq_blockers"].append("entry_state_contract_mismatch")
        combined["eq_eligible"] = False
    for side in sides:
        if not isinstance(side, dict):
            continue
        fixed = (side.get("external_model_audit") or {}).get("fixed_runtime")
        if fixed:
            try:
                actual = hashlib.sha256(Path(side["binary"]).read_bytes()).hexdigest()
                if actual != fixed.get("binary_sha256"):
                    raise ValueError("binary mismatch")
            except (OSError, KeyError, ValueError):
                combined["eq_blockers"].append("fixed_runtime_exploration_binary_mismatch")
                combined["eq_eligible"] = False
    combined["legacy_artifact"] = False
    return combined


def apply_semantic_model_gate(
    result: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """Prevent an EQ result when the Round017 model evidence is insufficient."""
    result["semantic_model_audit"] = audit
    result["semantic_model_eq_eligible"] = (
        audit.get("eq_eligible") is True
    )
    if (
        audit.get("applicable") is True
        and audit.get("eq_eligible") is not True
        and result.get("verdict") == "EQ"
    ):
        result["raw_verdict_before_semantic_model_gate"] = "EQ"
        result["prediction"] = None
        result["verdict"] = "UNK"
        result["failure_stage"] = "semantic_model_unqualified"
        result["failure_reason"] = (
            "external_function_or_ABI_evidence_does_not_authorize_EQ"
        )
        result["termination_reason"] = "semantic_model_gate_blocked_EQ"
    partial_neq_audit = partial_neq_artifact_gate(result)
    result["partial_neq_artifact_audit"] = partial_neq_audit
    requires_neq_replay = (
        audit.get("neq_requires_current_static_candidate_and_replay")
        is True
    )
    neq_mismatches = list(result.get("confirmed_mismatches") or [])
    neq_evidence_valid = True
    if requires_neq_replay:
        neq_evidence_valid = bool(
            result.get("static_only") is True
            and neq_mismatches
            and all(
                isinstance(record, dict)
                and (record.get("replay") or {}).get("confirmed") is True
                and record.get("counterexample_source")
                not in FORBIDDEN_NEQ_DISCOVERY_SOURCES
                for record in neq_mismatches
            )
        )
    if partial_neq_audit["applicable"]:
        neq_evidence_valid = (
            neq_evidence_valid
            and partial_neq_audit["eligible"]
        )
    result["semantic_model_neq_eligible"] = neq_evidence_valid
    if (
        (requires_neq_replay or partial_neq_audit["applicable"])
        and not neq_evidence_valid
        and result.get("verdict") == "NEQ"
    ):
        result["raw_verdict_before_semantic_model_gate"] = "NEQ"
        result["prediction"] = None
        result["verdict"] = "UNK"
        result["failure_stage"] = "semantic_model_neq_replay_required"
        result["failure_reason"] = (
            "unqualified_external_model_requires_current_static_candidate_replay"
        )
        result["termination_reason"] = "semantic_model_gate_blocked_NEQ"
        for record in neq_mismatches:
            if isinstance(record, dict):
                finalize_candidate_checkpoint(
                    record,
                    status="rejected",
                    reason=result["failure_reason"],
                    replay=record.get("replay") or {},
                )
    return result


def partial_neq_artifact_gate(result: dict[str, Any]) -> dict[str, Any]:
    """Check path/model reliability without requiring whole-program coverage."""
    exploration = result.get("exploration")
    if not isinstance(exploration, dict):
        return {
            "applicable": False,
            "eligible": True,
            "reason": "no_round017_exploration",
            "side_checks": {},
        }
    sides = (
        ("old", exploration.get("symbolic_oldV")),
        ("new", exploration.get("symbolic_newV")),
    )
    applicable = any(
        isinstance(record, dict)
        and record.get("schema") == "symbolicana.exploration.v4"
        for _, record in sides
    )
    if not applicable:
        return {
            "applicable": False,
            "eligible": True,
            "reason": "legacy_artifact",
            "side_checks": {},
        }
    side_checks: dict[str, Any] = {}
    blockers: list[str] = []
    for side, record in sides:
        if not isinstance(record, dict):
            side_checks[side] = {
                "reliable": False,
                "blockers": ["exploration_manifest_missing"],
            }
            blockers.append(f"{side}:exploration_manifest_missing")
            continue
        side_blockers = []
        reasons = set(record.get("incomplete_reasons") or [])
        for reason in sorted(reasons & UNRELIABLE_ADDRESS_REASONS):
            side_blockers.append(reason)
        address = record.get("address_concretization") or {}
        if int(address.get("lossy_event_count", 0) or 0) != 0:
            side_blockers.append("address_lossy_event_present")
        if int(address.get("unverified_event_count", 0) or 0) != 0:
            side_blockers.append("address_unverified_event_present")
        if address.get("coverage_verified") is not True:
            side_blockers.append("address_coverage_not_verified")
        side_checks[side] = {
            "reliable": not side_blockers,
            "blockers": sorted(set(side_blockers)),
            "address_event_count": int(address.get("event_count", 0) or 0),
        }
        blockers.extend(
            f"{side}:{blocker}" for blocker in side_blockers
        )
    for index, record in enumerate(result.get("confirmed_mismatches") or []):
        if not isinstance(record, dict):
            blockers.append(f"candidate_{index}:not_an_object")
            continue
        replay = record.get("replay") or {}
        if replay.get("confirmed") is not True:
            blockers.append(f"candidate_{index}:replay_not_confirmed")
        if (
            str(replay.get("classification") or "")
            in UB_ONLY_REPLAY_CLASSIFICATIONS
        ):
            blockers.append(f"candidate_{index}:ub_only_replay")
        direction = str(
            record.get("direction")
            or (_ACTIVE_RELATION_CONTEXT.get() or {}).get("direction")
            or "old_to_new"
        )
        try:
            identity = canonicalize_path_identity(
                record,
                direction=direction,
                task_uid=_ACTIVE_TASK_UID.get(),
                query_kind=str(
                    record.get("query_kind")
                    or record.get("query_kind")
                    or "confirmed_counterexample"
                ),
            )
        except CandidateSchemaError as exc:
            blockers.append(
                f"candidate_{index}:path_identity_conflict:{exc}"
            )
            continue
        if not identity["old_path_id"] or not identity["new_path_id"]:
            blockers.append(f"candidate_{index}:path_identity_missing")
    return {
        "applicable": True,
        "eligible": not blockers,
        "reason": (
            "partial_artifact_model_reliable"
            if not blockers
            else "partial_artifact_model_unreliable"
        ),
        "blockers": sorted(set(blockers)),
        "side_checks": side_checks,
        "completeness_required": False,
    }


def attach_b1_local_lemma(
    result: dict[str, Any],
    comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach a counted-loop lemma without promoting it to program EQ."""
    if comparison is None:
        result["b1_loop_comparison"] = None
        result["b1_local_lemma_eligible"] = None
        return result
    expected_schema = "symbolicana.round017.counted_loop_comparison.v1"
    schema_ok = comparison.get("schema") == expected_schema
    scope_ok = (
        comparison.get("eq_local_summary_eligible") is True
        and "local_loop_summary_only" in str(comparison.get("scope") or "")
    )
    result["b1_loop_comparison"] = comparison
    result["b1_local_lemma_eligible"] = bool(schema_ok and scope_ok)
    if result["b1_local_lemma_eligible"]:
        result.setdefault("supplemental_local_lemmas", []).append(
            {
                "kind": "counted_loop_summary",
                "status": comparison.get("status"),
                "scope": comparison.get("scope"),
                "authorizes_program_eq": False,
            }
        )
    return result


def attach_termination_mismatch_proof(
    result: dict[str, Any],
    proof: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply a strict static termination/divergence proof under policy A."""
    if proof is None:
        result["termination_mismatch_proof"] = None
        result["termination_mismatch_eligible"] = None
        return result
    expected_schema = "symbolicana.round017.termination_mismatch.v1"
    valid = bool(
        proof.get("schema") == expected_schema
        and proof.get("status") == "proved"
        and proof.get("proof_eligible") is True
        and proof.get("evidence_kind") == "termination_mismatch"
        and proof.get("same_input_domain") is True
        and proof.get("static_divergence") is True
        and proof.get("static_termination") is True
        and proof.get("definedness_safe") is True
        and proof.get("timeout_used_as_proof") is False
        and proof.get("concrete_replay_used_as_proof") is False
        and (proof.get("candidate") or {}).get("status") == "sat"
    )
    result["termination_mismatch_proof"] = proof
    result["termination_mismatch_eligible"] = valid
    if valid:
        if result.get("verdict") != "NEQ":
            result["raw_verdict_before_termination_mismatch_gate"] = (
                result.get("verdict")
            )
        result["verdict"] = "NEQ"
        result["prediction"] = False
        result["method"] = "termination_mismatch"
        result["failure_stage"] = None
        result["failure_reason"] = None
        result["termination_reason"] = "static_termination_mismatch_NEQ"
        result["termination_mismatch_count"] = 1
        result["termination_mismatch_evidence"] = {
            "evidence_kind": "termination_mismatch",
            "divergent_side": proof.get("divergent_side"),
            "terminating_side": proof.get("terminating_side"),
            "query_sha256": (proof.get("candidate") or {}).get(
                "query_sha256"
            ),
            "timeout_used_as_proof": False,
            "concrete_replay_used_as_proof": False,
        }
    return result


def schema_items(
    specs: tuple[tuple[str, str, int, int], ...],
) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "name": name,
            "c_type": kind,
            "kind": kind,
            "bits": int(bits),
            "precision": int(precision),
        }
        for index, (name, kind, bits, precision) in enumerate(specs)
    ]


def binary_hashes_for_paths(
    old_path: Path,
    new_path: Path,
) -> dict[str, str | None]:
    try:
        old_binary = binary_for_path(old_path)
        new_binary = binary_for_path(new_path)
    except ArtifactIdentityError:
        return {"old": None, "new": None}
    return {
        "old": sha256_file(old_binary) if old_binary and old_binary.is_file() else None,
        "new": sha256_file(new_binary) if new_binary and new_binary.is_file() else None,
    }


def validate_cached_witnesses_for_paths(
    old_paths: list[Path],
    new_paths: list[Path],
    pair_id: str | None,
    cache_path: Path | None,
) -> dict[str, Any]:
    if (
        not pair_id
        or cache_path is None
        or not old_paths
        or not new_paths
    ):
        return {"found": False, "attempts": []}
    specs = complete_input_specs_for_paths(
        old_paths[0].parent,
        old_paths[0],
        new_paths[0],
    )
    try:
        old_binary = binary_for_path(old_paths[0])
        new_binary = binary_for_path(new_paths[0])
    except ArtifactIdentityError as exc:
        return {
            "found": False,
            "attempts": [],
            "reason": "binary_identity_error",
            "identity_error": str(exc),
        }
    if old_binary is None or new_binary is None:
        return {
            "found": False,
            "attempts": [],
            "reason": "binary_unavailable",
        }
    return replay_cached_witnesses(
        cache_path,
        pair_id,
        old_binary,
        new_binary,
        schema_items(specs),
        current_binary_hashes={
            "old": sha256_file(old_binary),
            "new": sha256_file(new_binary),
        },
    )


def verified_cache_counterexample_record(
    cache_result: dict[str, Any],
    old_path: Path,
    new_path: Path,
) -> dict[str, Any]:
    replay = dict(cache_result.get("replay") or {})
    return {
        "source": old_path.stem,
        "target": new_path.stem,
        "rank": 1,
        "counterexample": {"inputs": replay.get("inputs") or []},
        "replay": replay,
        "counterexample_source": "validated_counterexample_cache",
        "cache_witness_id": cache_result.get("witness_id"),
        "cache_source": cache_result.get("source"),
        "cache_evidence_path": cache_result.get("evidence_path"),
        "reused_existing_evidence": True,
        "newly_discovered": False,
        "cache_audit": cache_result,
    }


def verify_counterexample_only(
    old_binary: Path,
    new_binary: Path,
    schema: list[dict[str, Any]],
    *,
    pair_id: str,
    cache_path: Path | None,
    artifact_status: str,
    input_ranges: dict[str, Any] | None = None,
    timeout_ms: int,
) -> dict[str, Any]:
    """Search only for a replayable NEQ; never infer EQ from absence."""
    started = time.perf_counter()
    if not old_binary.is_file() or not new_binary.is_file():
        return {
            "method": "counterexample_only_replay",
            "verdict": "UNK",
            "prediction": None,
            "failure_stage": "counterexample_execution",
            "failure_reason": "binary_unavailable",
            "analysis_mode": "counterexample_only",
            "eq_proof_eligible": False,
            "counterexample_execution_eligible": False,
            "artifact_status": artifact_status,
            "input_ranges": input_ranges,
            "old_path_count": 0,
            "new_path_count": 0,
            "candidate_pairs": 0,
            "aligned_pairs": 0,
            "smt_calls": 0,
            "unknowns": 1,
            "t_align": 0.0,
            "t_smt": time.perf_counter() - started,
            "t_total": time.perf_counter() - started,
            "matches": [],
            "reverse_matches": [],
            "confirmed_mismatches": [],
            "confirmed_counterexample_count": 0,
            "semantic_modes": {},
        }

    cache_result = replay_cached_witnesses(
        cache_path,
        pair_id,
        old_binary,
        new_binary,
        schema,
        current_binary_hashes={
            "old": sha256_file(old_binary),
            "new": sha256_file(new_binary),
        },
    )
    if cache_result.get("found"):
        replay = dict(cache_result.get("replay") or {})
        record = {
            "source": "counterexample_cache",
            "target": "original_binary_pair",
            "rank": 1,
            "counterexample": {"inputs": replay.get("inputs") or []},
            "replay": replay,
            "counterexample_source": "validated_counterexample_cache",
            "cache_witness_id": cache_result.get("witness_id"),
            "cache_source": cache_result.get("source"),
            "cache_evidence_path": cache_result.get("evidence_path"),
            "reused_existing_evidence": True,
            "newly_discovered": False,
            "cache_audit": cache_result,
        }
        elapsed = time.perf_counter() - started
        return {
            "method": "counterexample_only_replay",
            "verdict": "NEQ",
            "prediction": False,
            "failure_stage": None,
            "analysis_mode": "counterexample_only",
            "eq_proof_eligible": False,
            "counterexample_execution_eligible": True,
            "artifact_status": artifact_status,
            "input_ranges": input_ranges,
            "old_path_count": 0,
            "new_path_count": 0,
            "candidate_pairs": 1,
            "aligned_pairs": 0,
            "smt_calls": 0,
            "unknowns": 0,
            "t_align": 0.0,
            "t_smt": elapsed,
            "t_total": elapsed,
            "matches": [],
            "reverse_matches": [],
            "confirmed_mismatches": [record],
            "confirmed_counterexample_count": 1,
            "semantic_modes": {"validated_counterexample_cache": 1},
            "fast_path_branch": "counterexample_cache_NEQ",
            "termination_reason": "confirmed_neq_concrete_replay",
            "counterexample_cache": cache_result,
            "concrete_observations": [],
        }

    specs = tuple(
        (
            item["name"],
            item["kind"],
            int(item["bits"]),
            int(item.get("precision", 0) or 0),
        )
        for item in schema
    )
    seeds = standard_input_seeds(specs)
    if not seeds and not specs:
        seeds = [[]]
    observations = []
    for seed in seeds:
        inputs = list(seed)
        replay = classify_program_replay(
            old_binary,
            new_binary,
            schema,
            inputs,
        )
        observations.append(
            {
                "inputs": inputs,
                "classification": replay.get("classification"),
                "reason": replay.get("reason"),
            }
        )
        if replay.get("confirmed"):
            record = {
                "source": "counterexample_only_standard_seed",
                "target": "original_binary_pair",
                "rank": len(observations),
                "counterexample": {"inputs": inputs},
                "replay": replay,
                "counterexample_source": "counterexample_only_standard_seed_replay",
                "reused_existing_evidence": False,
                "newly_discovered": True,
            }
            elapsed = time.perf_counter() - started
            return {
                "method": "counterexample_only_replay",
                "verdict": "NEQ",
                "prediction": False,
                "failure_stage": None,
                "analysis_mode": "counterexample_only",
                "eq_proof_eligible": False,
                "counterexample_execution_eligible": True,
                "artifact_status": artifact_status,
                "input_ranges": input_ranges,
                "old_path_count": 0,
                "new_path_count": 0,
                "candidate_pairs": len(seeds),
                "aligned_pairs": 0,
                "smt_calls": 0,
                "unknowns": 0,
                "t_align": 0.0,
                "t_smt": elapsed,
                "t_total": elapsed,
                "matches": [],
                "reverse_matches": [],
                "confirmed_mismatches": [record],
                "confirmed_counterexample_count": 1,
                "semantic_modes": {"counterexample_only_standard_seed_replay": 1},
                "fast_path_branch": "counterexample_only_NEQ",
                "termination_reason": "confirmed_neq_concrete_replay",
                "counterexample_cache": cache_result,
                "concrete_observations": observations,
            }

    elapsed = time.perf_counter() - started
    return {
        "method": "counterexample_only_replay",
        "verdict": "UNK",
        "prediction": None,
        "failure_stage": "counterexample_only_unconfirmed",
        "failure_reason": "no_confirmed_counterexample",
        "analysis_mode": "counterexample_only",
        "eq_proof_eligible": False,
        "counterexample_execution_eligible": True,
        "artifact_status": artifact_status,
        "input_ranges": input_ranges,
        "old_path_count": 0,
        "new_path_count": 0,
        "candidate_pairs": len(seeds),
        "aligned_pairs": 0,
        "smt_calls": 0,
        "unknowns": 1,
        "t_align": 0.0,
        "t_smt": elapsed,
        "t_total": elapsed,
        "matches": [],
        "reverse_matches": [],
        "confirmed_mismatches": [],
        "confirmed_counterexample_count": 0,
        "semantic_modes": {"counterexample_only_replay": len(observations)},
        "fast_path_branch": "counterexample_only_UNK",
        "termination_reason": "no_confirmed_counterexample",
        "counterexample_cache": cache_result,
        "concrete_observations": observations,
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
    complete_matching: bool = False,
    pair_id: str | None = None,
    counterexample_cache: Path | None = None,
    static_only: bool = False,
) -> dict[str, Any]:
    if static_only and truth_pairs is not None:
        raise ValueError("static-only mode cannot use the path-truth oracle")
    if static_only and allow_legacy_artifacts:
        raise ValueError("static-only mode requires valid exploration manifests")
    if complete_matching and truth_pairs is not None:
        raise ValueError(
            "complete path matching cannot be combined with path-truth oracle"
        )
    removed_feasibility_filter = {
        "status": "not_performed",
        "reason": "independent_per_path_feasibility_prefilter_removed",
        "feasibility_complete": "not_applicable",
        "raw_old_path_count": None,
        "raw_new_path_count": None,
        "removed_unsat_old": "not_applicable",
        "removed_unsat_new": "not_applicable",
        "unknown_old": "not_applicable",
        "unknown_new": "not_applicable",
        "timeout_ms": "not_applicable",
    }
    matching_config = {
        "allow_one_to_many": allow_one_to_many,
        "matching_policy": (
            "multi_target_union"
            if allow_one_to_many
            else "single_target_reusable_source_subset"
        ),
        "target_reuse_allowed": True,
        "source_subset_allowed": True,
        "analysis_mode": (
            "complete_path_matching"
            if complete_matching
            else "optimized_program_verification"
        ),
        "exact_fast_path_enabled": not complete_matching,
        "neq_prescan_enabled": not complete_matching,
        "standard_seed_prescan_enabled": (
            not complete_matching and not static_only
        ),
        "domain_counterexample_prescan_enabled": (
            not complete_matching and not static_only
        ),
        "domain_prescan_invocations": 0,
        "domain_prescan_result": None,
        "fast_path_branch": None,
        "termination_reason": None,
        "exact_fast_path_triggered": False,
        "prescan_invocations": 0,
        "prescan_smt_calls": 0,
        "exact_fast_path_synthetic_records": 0,
        "static_only": static_only,
        "fresh_analysis_route_audit": {
            "historical_cache_loads": 0,
            "standard_seed_invocations": 0,
            "random_input_invocations": 0,
            "fuzz_input_invocations": 0,
        },
    }
    active_contract = _ACTIVE_INPUT_CONTRACT.get()
    old_paths = sorted(paths_dir.glob("symbolic_oldV_path_*.txt"), key=lambda p: path_number(p.stem))
    new_paths = sorted(paths_dir.glob("symbolic_newV_path_*.txt"), key=lambda p: path_number(p.stem))
    old_by_id = path_index(old_paths)
    new_by_id = path_index(new_paths)
    exploration = load_exploration_status(paths_dir)
    domain_audit = artifact_domain_audit(exploration, active_contract)
    matching_config["artifact_domain_audit"] = domain_audit
    matching_config["input_contract"] = active_contract
    if not domain_audit["compatible"]:
        return {
            "method": "domain_contract_guard",
            "prediction": None,
            "verdict": "UNK",
            "failure_stage": "domain_artifact_mismatch",
            "failure_reason": "artifact_domain_contract_is_incompatible",
            "alignment_success": False,
            "input_space_equal": None,
            "old_input_subset_new": None,
            "new_input_subset_old": None,
            "old_path_count": len(old_paths),
            "new_path_count": len(new_paths),
            "candidate_pairs": 0,
            "aligned_pairs": 0,
            "smt_calls": 0,
            "t_align": 0.0,
            "t_smt": 0.0,
            "t_total": 0.0,
            "unknowns": 1,
            "matches": [],
            "reverse_matches": [],
            "confirmed_mismatches": [],
            "exploration": exploration,
            "smt_audit": smt_audit_summary(),
            **matching_config,
        }
    exploration_ready = (
        exploration_is_complete(
            exploration["symbolic_oldV"],
            path_count=len(old_paths),
            require_proof_eligible=not allow_legacy_artifacts,
        )
        and exploration_is_complete(
            exploration["symbolic_newV"],
            path_count=len(new_paths),
            require_proof_eligible=not allow_legacy_artifacts,
        )
    )
    exploration_coverage_blocked = (
        not exploration_ready and not allow_legacy_artifacts
    )

    cached_counterexamples = (
        {"found": False, "attempts": [], "static_only_suppressed": True}
        if static_only
        else validate_cached_witnesses_for_paths(
            old_paths,
            new_paths,
            pair_id,
            counterexample_cache,
        )
    )
    if cached_counterexamples.get("found"):
        record = verified_cache_counterexample_record(
            cached_counterexamples,
            old_paths[0],
            new_paths[0],
        )
        return {
            "method": "validated_counterexample_cache",
            "prediction": False,
            "verdict": "NEQ",
            "failure_stage": None,
            "alignment_success": False,
            "input_space_equal": None,
            "old_input_subset_new": None,
            "new_input_subset_old": None,
            "old_path_count": len(old_paths),
            "new_path_count": len(new_paths),
            "raw_old_path_count": len(old_paths),
            "raw_new_path_count": len(new_paths),
            "candidate_pairs": len(old_paths) * len(new_paths),
            "aligned_pairs": 0,
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
            "semantic_modes": {"validated_counterexample_cache": 1},
            "matches": [],
            "reverse_matches": [],
            "confirmed_mismatches": [record],
            "confirmed_counterexample_count": 1,
            "exploration": exploration,
            "exploration_coverage_blocked": exploration_coverage_blocked,
            "path_feasibility_filter": {
                **removed_feasibility_filter,
                "raw_old_path_count": len(old_paths),
                "raw_new_path_count": len(new_paths),
            },
            "feasibility_complete": "not_applicable",
            "smt_audit": smt_audit_summary(),
            **matching_config,
            "counterexample_cache": cached_counterexamples,
            "fast_path_branch": "counterexample_cache_NEQ",
            "termination_reason": "confirmed_neq_concrete_replay",
            "matching_complete": False,
            "required_semantic_checks_complete": False,
            "eq_proof_eligible": exploration_ready,
            "counterexample_execution_eligible": True,
            "artifact_status": (
                "proof_eligible" if exploration_ready else "incomplete_or_lossy"
            ),
            "forward_source_count": len(old_paths),
            "forward_processed_source_count": 0,
            "reverse_source_count": len(new_paths),
            "reverse_processed_source_count": 0,
        }

    exact_records = (
        None
        if complete_matching or exploration_coverage_blocked
        else exact_path_bijection_proves_equivalence(old_paths, new_paths)
    )
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
                **removed_feasibility_filter,
                "raw_old_path_count": len(old_paths),
                "raw_new_path_count": len(new_paths),
            },
            "feasibility_complete": "not_applicable",
            "smt_audit": smt_audit_summary(),
            **matching_config,
            "exact_path_bijection": True,
            "exact_fast_path_triggered": True,
            "matching_complete": True,
            "required_semantic_checks_complete": True,
            "forward_source_count": len(old_paths),
            "forward_processed_source_count": len(old_paths),
            "reverse_source_count": len(new_paths),
            "reverse_processed_source_count": len(new_paths),
            "exact_fast_path_synthetic_records": len(exact_records),
            "fast_path_branch": "exact_identity_EQ",
            "termination_reason": "complete_identity_proof",
        }

    domain_prescan: dict[str, Any] | None = None
    if truth_pairs is None and not complete_matching and not static_only:
        domain_started = time.perf_counter()
        domain_prescan = program_domain_counterexample(old_paths, new_paths)
        domain_elapsed = time.perf_counter() - domain_started
        if domain_prescan.get("counterexample") is not None:
            record = {
                key: domain_prescan[key]
                for key in (
                    "source",
                    "target",
                    "rank",
                    "counterexample",
                    "replay",
                    "counterexample_source",
                )
                if key in domain_prescan
            }
            return {
                "method": "concrete_program_domain_replay",
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
                "t_align": 0.0,
                "t_smt": domain_elapsed,
                "t_total": domain_elapsed,
                "unknowns": 0,
                "semantic_definition": [
                    "input_space_equivalence",
                    "function_return_value_equivalence",
                    "program_output_equivalence",
                    "globally_observable_memory_state_equivalence",
                ],
                "semantic_modes": {
                    "concrete_program_domain_replay": 1,
                },
                "matches": [],
                "reverse_matches": [],
                "confirmed_mismatches": [record],
                "confirmed_counterexample_count": 1,
                "exploration": exploration,
                "exploration_coverage_blocked": (
                    exploration_coverage_blocked
                ),
                "path_feasibility_filter": {
                    **removed_feasibility_filter,
                    "raw_old_path_count": len(old_paths),
                    "raw_new_path_count": len(new_paths),
                },
                "feasibility_complete": "not_applicable",
                "smt_audit": smt_audit_summary(),
                **matching_config,
                "domain_prescan_invocations": 1,
                "domain_prescan_result": domain_prescan,
                "fast_path_branch": "standard_domain_seed_replay",
                "termination_reason": "confirmed_neq_concrete_replay",
                "matching_complete": False,
                "required_semantic_checks_complete": False,
                "forward_source_count": len(old_paths),
                "forward_processed_source_count": 0,
                "reverse_source_count": len(new_paths),
                "reverse_processed_source_count": 0,
            }

    raw_old_path_count = len(old_paths)
    raw_new_path_count = len(new_paths)
    feasibility_filter = {
        **removed_feasibility_filter,
        "raw_old_path_count": raw_old_path_count,
        "raw_new_path_count": raw_new_path_count,
    }
    if not old_paths or not new_paths:
        return {
            "method": str(ranking_path) if ranking_path else "naive_all_pairs",
            "verdict": "UNK",
            "prediction": None,
            "failure_stage": "symbolic_execution",
            "failure_reason": "no_complete_paths",
            "old_path_count": len(old_paths),
            "new_path_count": len(new_paths),
            "raw_old_path_count": raw_old_path_count,
            "raw_new_path_count": raw_new_path_count,
            "candidate_pairs": len(old_paths) * len(new_paths),
            "aligned_pairs": 0,
            "smt_calls": 0,
            "t_align": 0.0,
            "t_smt": 0.0,
            "t_total": 0.0,
            "unknowns": 1,
            "matches": [],
            "reverse_matches": [],
            "confirmed_mismatches": [],
            "semantic_modes": {},
            "exploration": exploration,
            "path_feasibility_filter": feasibility_filter,
            "feasibility_complete": "not_applicable",
            "matching_complete": False,
            "required_semantic_checks_complete": False,
            "forward_source_count": 0,
            "forward_processed_source_count": 0,
            "reverse_source_count": 0,
            "reverse_processed_source_count": 0,
            "smt_audit": smt_audit_summary(),
            **matching_config,
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

    smt_calls = 0
    t_smt = 0.0
    unknowns = 0
    semantic_modes: dict[str, int] = {}

    reverse_ranking = invert_ranking(ranking, old_paths, new_paths)
    reverse_truth_pairs = None
    if truth_pairs is not None:
        reverse_truth_pairs = {}
        for old_id, new_ids in truth_pairs.items():
            for new_id in new_ids:
                reverse_truth_pairs.setdefault(new_id, set()).add(old_id)

    prescan_invocations = 0
    prescan_smt_calls = 0
    if truth_pairs is None and not complete_matching:
        prescan_invocations = 1
        prescan = prescan_replayable_counterexample(
            old_paths,
            new_paths,
            ranking,
            timeout_ms,
            direction="old_to_new",
        )
        if prescan["mismatch"] is None:
            prescan_invocations = 2
            reverse_prescan = prescan_replayable_counterexample(
                new_paths,
                old_paths,
                reverse_ranking,
                timeout_ms,
                direction="new_to_old",
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
        prescan_smt_calls = int(prescan["smt_calls"]) + int(
            reverse_prescan["smt_calls"]
        )
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
                "exploration_coverage_blocked": (
                    exploration_coverage_blocked
                ),
                "path_feasibility_filter": feasibility_filter,
                "feasibility_complete": "not_applicable",
                "smt_audit": smt_audit_summary(),
                **matching_config,
                "counterexample_prescan": True,
                "domain_prescan_invocations": 1 if domain_prescan else 0,
                "domain_prescan_result": domain_prescan,
                "fast_path_branch": "ranked_prescan_NEQ",
                "termination_reason": "confirmed_neq_ranked_prescan",
                "matching_complete": False,
                "required_semantic_checks_complete": False,
                "forward_source_count": len(old_paths),
                "forward_processed_source_count": 0,
                "reverse_source_count": len(new_paths),
                "reverse_processed_source_count": 0,
                "prescan_invocations": prescan_invocations,
                "prescan_smt_calls": prescan_smt_calls,
            }

    if exploration_coverage_blocked:
        return {
            "method": method,
            "prediction": None,
            "verdict": "UNK",
            "failure_stage": "incomplete_symbolic_exploration",
            "failure_reason": "missing_or_incomplete_exploration_manifest",
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
            "unknowns": 1,
            "semantic_definition": [
                "input_space_equivalence",
                "function_return_value_equivalence",
                "program_output_equivalence",
                "globally_observable_memory_state_equivalence",
            ],
            "semantic_modes": semantic_modes,
            "matches": [],
            "reverse_matches": [],
            "confirmed_mismatches": [],
            "exploration": exploration,
            "exploration_coverage_blocked": True,
            "path_feasibility_filter": feasibility_filter,
            "feasibility_complete": "not_applicable",
            "smt_audit": smt_audit_summary(),
            **matching_config,
            "domain_prescan_invocations": 1 if domain_prescan else 0,
            "domain_prescan_result": domain_prescan,
            "prescan_invocations": prescan_invocations,
            "prescan_smt_calls": prescan_smt_calls,
            "fast_path_branch": "incomplete_artifact_NEQ_prescan_only",
            "termination_reason": (
                "no_confirmed_counterexample_under_incomplete_artifact"
            ),
            "matching_complete": False,
            "required_semantic_checks_complete": False,
            "forward_source_count": len(old_paths),
            "forward_processed_source_count": 0,
            "reverse_source_count": len(new_paths),
            "reverse_processed_source_count": 0,
        }

    input_ranges = configured_input_ranges() or (
        (exploration.get("symbolic_oldV") or {}).get("input_ranges")
    )
    old_domain_evidence = proof_query_call(
        "input_domain", "old_domain_subset_new_domain", None,
        [path.stem for path in new_paths], check_union_coverage_evidence,
        old_paths,
        new_paths,
        timeout_ms,
        direction="old_domain_subset_new_domain",
        input_ranges=input_ranges,
    )
    new_domain_evidence = proof_query_call(
        "input_domain", "new_domain_subset_old_domain", None,
        [path.stem for path in old_paths], check_union_coverage_evidence,
        new_paths,
        old_paths,
        timeout_ms,
        direction="new_domain_subset_old_domain",
        input_ranges=input_ranges,
    )
    smt_calls += sum(
        evidence.get("method") == "smt_union_exclusion"
        for evidence in (old_domain_evidence, new_domain_evidence)
    )
    t_smt += float(old_domain_evidence["elapsed_seconds"]) + float(
        new_domain_evidence["elapsed_seconds"]
    )
    old_subset_new = old_domain_evidence["subset"]
    new_subset_old = new_domain_evidence["subset"]
    if old_subset_new is None or new_subset_old is None:
        unknowns += 1
    if old_subset_new is False or new_subset_old is False:
        input_space_equal: bool | None = False
    elif old_subset_new is True and new_subset_old is True:
        input_space_equal = True
    else:
        input_space_equal = None
    global_input_space_evidence = {
        "definition": "path-condition union over the configured input domain",
        "input_ranges": input_ranges,
        "old_domain_subset_new_domain": old_domain_evidence,
        "new_domain_subset_old_domain": new_domain_evidence,
    }
    domain_mismatches = [
        evidence
        for evidence in (old_domain_evidence, new_domain_evidence)
        if evidence.get("subset") is False
    ]
    domain_witness_audits: list[dict[str, Any]] = []
    if domain_mismatches and exploration_ready and not allow_legacy_artifacts:
        for evidence in domain_mismatches:
            audit = audit_domain_witness(old_paths, new_paths, evidence)
            evidence_path = persist_confirmed_evidence(
                audit,
                evidence_type="domain_witness_replay_audit",
            )
            if evidence_path:
                audit["evidence_path"] = evidence_path
            domain_witness_audits.append(audit)
    confirmed_domain_mismatches = [
        audit for audit in domain_witness_audits if audit.get("supports_neq")
    ]
    artifact_coverage_defects = [
        audit
        for audit in domain_witness_audits
        if audit.get("classification") == "artifact_coverage_defect"
    ]
    unconfirmed_domain_witnesses = [
        audit
        for audit in domain_witness_audits
        if not audit.get("supports_neq")
        and audit not in artifact_coverage_defects
    ]
    domain_evidence_authoritative = bool(confirmed_domain_mismatches)
    domain_evidence_blocked = bool(
        domain_mismatches
        and (
            not domain_witness_audits
            or artifact_coverage_defects
            or unconfirmed_domain_witnesses
        )
    )
    if exploration_coverage_blocked:
        input_space_equal = None
        domain_evidence_blocked = True
    if domain_evidence_authoritative:
        input_space_equal = False
    elif domain_evidence_blocked:
        input_space_equal = None
    global_input_space_evidence["authoritative"] = domain_evidence_authoritative
    global_input_space_evidence["blocked"] = domain_evidence_blocked
    global_input_space_evidence["confirmed_mismatch_count"] = len(
        confirmed_domain_mismatches
    )
    global_input_space_evidence["artifact_coverage_defect_count"] = len(
        artifact_coverage_defects
    )
    global_input_space_evidence["unconfirmed_witness_count"] = len(
        unconfirmed_domain_witnesses
    )
    global_input_space_evidence["exploration_coverage_blocked"] = (
        exploration_coverage_blocked
    )
    global_input_space_evidence["witness_audits"] = domain_witness_audits
    if domain_mismatches and domain_evidence_authoritative:
        global_input_space_evidence["evidence_path"] = persist_confirmed_evidence(
            {
                "domain_mismatches": domain_mismatches,
                "confirmed_domain_mismatches": confirmed_domain_mismatches,
                "input_ranges": input_ranges,
            },
            evidence_type="global_input_space_mismatch",
        )

    if (
        domain_mismatches
        and domain_evidence_authoritative
        and not complete_matching
    ):
        return {
            "method": method,
            "prediction": False,
            "verdict": "NEQ",
            "failure_stage": None,
            "alignment_success": False,
            "input_space_equal": False,
            "old_input_subset_new": old_subset_new,
            "new_input_subset_old": new_subset_old,
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
            "matches": [],
            "reverse_matches": [],
            "confirmed_mismatches": confirmed_domain_mismatches,
            "domain_mismatches": domain_mismatches,
            "domain_mismatch_count": len(domain_mismatches),
            "domain_witness_audits": domain_witness_audits,
            "confirmed_domain_mismatch_count": len(
                confirmed_domain_mismatches
            ),
            "confirmed_counterexample_count": len(
                confirmed_domain_mismatches
            ),
            "global_input_space_evidence": global_input_space_evidence,
            "exploration": exploration,
            "exploration_coverage_blocked": (
                exploration_coverage_blocked
            ),
            "path_feasibility_filter": feasibility_filter,
            "feasibility_complete": "not_applicable",
            "smt_audit": smt_audit_summary(),
            **matching_config,
            "fast_path_branch": "confirmed_domain_NEQ",
            "termination_reason": "confirmed_domain_witness",
            "matching_complete": False,
            "required_semantic_checks_complete": False,
            "forward_source_count": len(old_paths),
            "forward_processed_source_count": 0,
            "reverse_source_count": len(new_paths),
            "reverse_processed_source_count": 0,
        }

    directional_verifier = (
        verify_complete_directional_cover
        if complete_matching
        else verify_directional_cover
    )
    forward = directional_verifier(
        old_paths,
        new_paths,
        ranking,
        timeout_ms,
        truth_pairs,
        allow_one_to_many,
        direction="old_to_new",
    )
    reverse = directional_verifier(
        new_paths,
        old_paths,
        reverse_ranking,
        timeout_ms,
        reverse_truth_pairs,
        allow_one_to_many,
        direction="new_to_old",
    )

    smt_calls += int(forward["smt_calls"]) + int(reverse["smt_calls"])
    t_smt += float(forward["t_smt"]) + float(reverse["t_smt"])
    unknowns += int(forward["unknowns"]) + int(reverse["unknowns"])
    merge_counter(semantic_modes, forward["semantic_modes"])
    merge_counter(semantic_modes, reverse["semantic_modes"])

    forward_proof = summarize_required_obligations(
        list(path_index(old_paths)), forward["records"], "old_to_new")
    reverse_proof = summarize_required_obligations(
        list(path_index(new_paths)), reverse["records"], "new_to_old")
    proof = {
        key: forward_proof[key] + reverse_proof[key]
        for key in ("required_obligations", "unresolved_required_obligations", "proof_accounting_errors")
    }
    for direction, evidence in (("old_domain_subset_new_domain", old_domain_evidence),
                                ("new_domain_subset_old_domain", new_domain_evidence)):
        obligation = {"obligation_id": direction, "direction": direction,
                      "source": None, "kind": "input_domain",
                      "status": "discharged" if evidence["subset"] is True else "unresolved",
                      "reason": None if evidence["subset"] is True else "global_input_domain_unproven"}
        proof["required_obligations"].append(obligation)
        if obligation["status"] == "unresolved":
            proof["unresolved_required_obligations"].append(obligation)
    proof["unresolved_required_obligation_count"] = len(proof["unresolved_required_obligations"])
    matching_complete = forward_proof["matching_complete"] and reverse_proof["matching_complete"]
    required_semantic_checks_complete = not any(
        item["kind"] == "semantics" for item in proof["unresolved_required_obligations"]
    ) and not proof["proof_accounting_errors"]
    alignment_success = bool(
        input_space_equal
        and not domain_evidence_blocked
        and forward_proof["success"]
        and reverse_proof["success"]
        and matching_complete
        and required_semantic_checks_complete
    )
    confirmed_mismatches = [
        *forward.get("confirmed_mismatches", []),
        *reverse.get("confirmed_mismatches", []),
    ]
    unresolved_sources = {(item["direction"], item["source"])
                          for item in proof["unresolved_required_obligations"]}
    abstract_candidates = [
        {"direction": direction, **candidate}
        for direction, result in (("old_to_new", forward), ("new_to_old", reverse))
        for candidate in abstract_difference_candidates(result["records"])
        if (direction, candidate["source"]) in unresolved_sources
    ]
    if domain_mismatches and domain_evidence_authoritative:
        verdict = "NEQ"
        prediction = False
        failure_stage = None
    elif confirmed_mismatches:
        verdict = "NEQ"
        prediction = False
        failure_stage = None
    elif alignment_success and not domain_evidence_blocked:
        verdict = "EQ"
        prediction = True
        failure_stage = None
    else:
        verdict = "UNK"
        prediction = None
        if exploration_coverage_blocked:
            failure_stage = "incomplete_symbolic_exploration"
        elif artifact_coverage_defects:
            failure_stage = "domain_artifact_coverage_defect"
        elif domain_mismatches and not confirmed_domain_mismatches:
            failure_stage = "domain_witness_unconfirmed"
        elif old_subset_new is None or new_subset_old is None:
            failure_stage = "global_input_space_unknown"
        elif input_space_equal is False:
            failure_stage = "global_input_space_mismatch"
        else:
            failure_stage = classify_directional_failure(proof, abstract_candidates)

    if complete_matching:
        fast_path_branch = "complete_path_traversal"
        termination_reason = (
            "confirmed_counterexample"
            if confirmed_mismatches
            else "confirmed_domain_witness"
            if domain_mismatches and domain_evidence_authoritative
            else "traversal_completed"
        )
    elif confirmed_mismatches or (
        domain_mismatches and domain_evidence_authoritative
    ):
        forward_complete = int(
            forward.get("source_count", len(old_paths))
        ) == int(
            forward.get("processed_source_count", len(forward["records"]))
        )
        reverse_complete = int(
            reverse.get("source_count", len(new_paths))
        ) == int(
            reverse.get("processed_source_count", len(reverse["records"]))
        )
        fast_path_branch = (
            "confirmed_domain_NEQ"
            if domain_mismatches and domain_evidence_authoritative
            else "directional_NEQ"
            if forward_complete and reverse_complete
            else "directional_early_NEQ"
        )
        termination_reason = (
            "confirmed_domain_witness"
            if domain_mismatches and domain_evidence_authoritative
            else "confirmed_counterexample"
        )
    elif verdict == "EQ":
        fast_path_branch = "directional_EQ"
        termination_reason = "complete_directional_proof"
    else:
        if exploration_coverage_blocked:
            fast_path_branch = "incomplete_artifact_NEQ_prescan_only"
            termination_reason = "no_confirmed_counterexample_under_incomplete_artifact"
        elif domain_evidence_blocked:
            fast_path_branch = "domain_witness_UNK"
            termination_reason = (
                "domain_artifact_coverage_defect"
                if artifact_coverage_defects
                else "domain_witness_unconfirmed"
            )
        else:
            fast_path_branch = "directional_UNK"
            termination_reason = "no_confirmed_counterexample"

    return {
        "method": method,
        "prediction": prediction,
        "verdict": verdict,
        "failure_stage": failure_stage,
        "alignment_success": alignment_success,
        "matching_complete": matching_complete,
        "feasibility_complete": "not_applicable",
        "required_semantic_checks_complete": required_semantic_checks_complete,
        **proof,
        **historical_unknown_summary(proof["required_obligations"]),
        "proof_accounting_scope": "directional_coverage_semantics_and_global_domain",
        "abstract_difference_candidates": abstract_candidates,
        "forward_source_count": int(
            forward.get("source_count", len(old_paths))
        ),
        "forward_processed_source_count": int(
            forward.get("processed_source_count", len(forward["records"]))
        ),
        "reverse_source_count": int(
            reverse.get("source_count", len(new_paths))
        ),
        "reverse_processed_source_count": int(
            reverse.get("processed_source_count", len(reverse["records"]))
        ),
        "coverage_status_counts": {
            "forward": forward.get("coverage_status_counts", {}),
            "reverse": reverse.get("coverage_status_counts", {}),
        },
        "semantic_status_counts": {
            "forward": forward.get("semantic_status_counts", {}),
            "reverse": reverse.get("semantic_status_counts", {}),
        },
        "input_space_equal": input_space_equal,
        "old_input_subset_new": old_subset_new,
        "new_input_subset_old": new_subset_old,
        "old_path_count": len(old_paths),
        "new_path_count": len(new_paths),
        "candidate_pairs": len(old_paths) * len(new_paths),
        "aligned_pairs": int(forward["matched_source_count"]),
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
        "confirmed_counterexample_count": len(
            confirmed_mismatches
        ) + len(confirmed_domain_mismatches),
        "domain_mismatches": domain_mismatches,
        "domain_mismatch_count": len(domain_mismatches),
        "domain_witness_audits": domain_witness_audits,
        "confirmed_domain_mismatches": confirmed_domain_mismatches,
        "confirmed_domain_mismatch_count": len(
            confirmed_domain_mismatches
        ),
        "domain_artifact_coverage_defects": artifact_coverage_defects,
        "domain_artifact_coverage_defect_count": len(
            artifact_coverage_defects
        ),
        "unconfirmed_domain_witnesses": unconfirmed_domain_witnesses,
        "domain_witness_unconfirmed_count": len(
            unconfirmed_domain_witnesses
        ),
        "domain_evidence_blocked": domain_evidence_blocked,
        "global_input_space_evidence": global_input_space_evidence,
        "exact_fast_path_triggered": False,
        "exact_fast_path_synthetic_records": 0,
        "prescan_invocations": prescan_invocations,
        "prescan_smt_calls": prescan_smt_calls,
        "exploration": exploration,
        "exploration_coverage_blocked": exploration_coverage_blocked,
        "failure_reason": (
            "missing_or_incomplete_exploration_manifest"
            if exploration_coverage_blocked
            else None
        ),
        "path_feasibility_filter": feasibility_filter,
        "feasibility_complete": "not_applicable",
        **matching_config,
        "domain_prescan_invocations": 1 if domain_prescan else 0,
        "domain_prescan_result": domain_prescan,
        "fast_path_branch": fast_path_branch,
        "termination_reason": termination_reason,
        "smt_audit": smt_audit_summary(),
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


def enforce_result_domain_contract(
    result: dict[str, Any],
    contract: dict[str, Any] | None,
) -> dict[str, Any]:
    if not contract:
        result["domain_acceptance"] = {
            "status": "not_configured",
            "accepted": 0,
            "rejected": 0,
        }
        return result
    accepted = []
    rejected = []
    for record in result.get("confirmed_mismatches") or []:
        schema = record.get("input_schema")
        if not schema:
            schema = [
                {
                    key: value
                    for key, value in item.items()
                    if key
                    in {
                        "index",
                        "name",
                        "kind",
                        "bits",
                        "precision",
                        "c_type",
                    }
                }
                for item in contract.get("inputs") or []
            ]
        inputs = (record.get("counterexample") or {}).get("inputs")
        _ordered, errors = validate_values(
            schema,
            inputs,
            contract.get("profile"),
        )
        if errors:
            finalize_candidate_checkpoint(
                record,
                status="rejected",
                reason="candidate_model_outside_input_domain",
                replay=record.get("replay") or {},
            )
            rejected.append(
                {
                    "source": record.get("source"),
                    "target": record.get("target"),
                    "errors": errors,
                    "inputs": inputs,
                }
            )
        else:
            accepted.append(record)
    result["confirmed_mismatches"] = accepted
    result["confirmed_counterexample_count"] = len(accepted)
    result["domain_rejected_counterexamples"] = rejected
    result["domain_acceptance"] = {
        "status": "pass" if not rejected else "rejected_candidates",
        "accepted": len(accepted),
        "rejected": len(rejected),
        "profile_id": contract.get("profile_id"),
        "domain_hash": contract.get("domain_hash"),
    }
    if (
        result.get("verdict") == "NEQ"
        and result.get("prediction") is False
        and not accepted
    ):
        result["raw_verdict_before_domain_gate"] = "NEQ"
        result["verdict"] = "UNK"
        result["prediction"] = None
        result["failure_stage"] = "domain_unverified"
        result["failure_reason"] = "no_in_domain_confirmed_counterexample"
        result["fast_path_branch"] = "domain_rejected_candidate_UNK"
        result["termination_reason"] = "domain_gate_rejected_all_neq_candidates"
    return result


def attach_failure_classification(result: dict[str, Any]) -> dict[str, Any]:
    """Separate execution, semantics, artifacts, eligibility, and causes."""
    verdict = str(result.get("verdict") or "UNK")
    artifact_status = str(
        result.get("artifact_status")
        or ("proof_eligible" if result.get("eq_proof_eligible") else "unknown")
    )
    secondary = []
    semantic_audit = result.get("semantic_model_audit") or {}
    secondary.extend(
        f"semantic_model:{item}"
        for item in semantic_audit.get("eq_blockers") or []
    )
    partial = result.get("partial_neq_artifact_audit") or {}
    secondary.extend(
        f"partial_neq:{item}" for item in partial.get("blockers") or []
    )
    candidates = result.get("candidate_audit") or {}
    for candidate in candidates.get("candidates") or []:
        if candidate.get("status") == "indeterminate":
            secondary.append(
                "candidate_indeterminate:"
                + str(candidate.get("reason") or "unspecified")
            )
    primary = str(result.get("failure_reason") or "")
    if verdict == "UNK" and not primary:
        primary = str(
            result.get("failure_stage")
            or "unresolved_without_qualified_proof"
        )
        result["failure_reason"] = primary
    result["failure_classification"] = {
        "schema": "symbolicana.round018.failure_classification.v1",
        "execution_status": "semantic_engine_completed",
        "semantic_verdict": verdict,
        "artifact_completeness": artifact_status,
        "proof_eligibility": {
            "eq": result.get("eq_proof_eligible"),
            "neq": result.get("semantic_model_neq_eligible"),
        },
        "primary_reason": primary or None,
        "secondary_reasons": list(dict.fromkeys(secondary)),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths-dir", type=Path)
    parser.add_argument("--ranking", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pair-id", default="")
    parser.add_argument("--attempt-uid", default="")
    parser.add_argument("--counterexample-only", action="store_true")
    parser.add_argument("--old-binary", type=Path)
    parser.add_argument("--new-binary", type=Path)
    parser.add_argument(
        "--artifact-identity-json",
        type=Path,
        help=(
            "Manifest-backed artifact identity for this task. Formal runs "
            "require this record and validate it before replay."
        ),
    )
    parser.add_argument(
        "--require-artifact-identity",
        action="store_true",
        help="Fail closed unless --artifact-identity-json is supplied and valid.",
    )
    parser.add_argument("--input-schema-json")
    parser.add_argument(
        "--entry-signature",
        help=(
            "Canonical C prototype such as double(int,double); its return "
            "type controls observable return-value semantics."
        ),
    )
    parser.add_argument("--domain-profile-json", type=Path)
    parser.add_argument(
        "--static-only",
        action="store_true",
        help=(
            "Round016 static route: suppress historical cache and standalone "
            "concrete/random/fuzz counterexample discovery."
        ),
    )
    parser.add_argument("--artifact-status", default="not_proof_eligible")
    parser.add_argument("--input-ranges-json")
    parser.add_argument("--counterexample-cache", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--naive", action="store_true")
    parser.add_argument("--truth-pairs-json")
    parser.add_argument(
        "--program-ground-truth",
        help="Deprecated compatibility argument; it is ignored by the verifier.",
    )
    parser.add_argument(
        "--allow-legacy-artifacts",
        action="store_true",
        help="Permit path files without exploration manifests (cannot authorize paper-grade EQ).",
    )
    parser.add_argument(
        "--one-to-one-only",
        action="store_true",
        help=(
            "Historical single-target ablation: each source may use at most "
            "one target; target reuse and source-subset-target remain allowed."
        ),
    )
    parser.add_argument(
        "--complete-path-matching",
        action="store_true",
        help=(
            "Disable program-level fast exits and traverse every source path "
            "in both directions before deciding the program pair."
        ),
    )
    parser.add_argument(
        "--solver-strategy",
        choices=STRATEGIES,
        default="Z60",
        help="Frozen solver strategy for this verification run.",
    )
    parser.add_argument(
        "--smt-audit-all-queries",
        action="store_true",
        help="Persist every solver query, including SAT and UNSAT results.",
    )
    parser.add_argument(
        "--b1-comparison-json",
        type=Path,
        help="Optional counted-loop local lemma produced by the B1 comparer.",
    )
    parser.add_argument(
        "--termination-proof-json",
        type=Path,
        help="Optional strict static termination/divergence proof.",
    )
    args = parser.parse_args()
    if args.static_only and args.counterexample_only:
        parser.error("--counterexample-only is not part of the static-only route")
    if args.static_only and args.counterexample_cache is not None:
        parser.error("--static-only cannot load --counterexample-cache")
    if args.static_only and args.truth_pairs_json:
        parser.error("--static-only cannot use a path-truth oracle")
    domain_profile = load_profile(args.domain_profile_json)
    return_type = signature_return_type(args.entry_signature)
    if args.entry_signature and return_type is None:
        parser.error("--entry-signature must use the canonical ret(args...) form")
    _ACTIVE_RETURN_TYPE.set(return_type)
    input_contract = None
    if args.input_schema_json:
        raw_contract_schema = json.loads(args.input_schema_json)
        if isinstance(raw_contract_schema, dict):
            raw_contract_schema = raw_contract_schema.get("inputs", [])
        if not isinstance(raw_contract_schema, list):
            parser.error(
                "--input-schema-json must contain a list or {'inputs': list}"
            )
        input_contract = build_contract(
            raw_contract_schema,
            profile=domain_profile,
            pair_id=args.pair_id,
            source="verifier_cli",
        )
        _ACTIVE_INPUT_CONTRACT.set(input_contract)

    configure_solver_strategy(
        args.solver_strategy,
        audit_callback=(
            persist_backend_check if args.smt_audit_all_queries else None
        ),
        audit_all_queries=args.smt_audit_all_queries,
    )
    configure_smt_audit(
        evidence_session_directory(args.out, args.attempt_uid or None),
        persist_all_queries=args.smt_audit_all_queries,
    )
    artifact_identity = None
    if args.artifact_identity_json is not None:
        artifact_identity = json.loads(
            args.artifact_identity_json.read_text(encoding="utf-8-sig")
        )
    if args.require_artifact_identity and artifact_identity is None:
        parser.error(
            "--require-artifact-identity needs --artifact-identity-json"
        )
    identity_check = None
    identity_validation_error = None
    if artifact_identity is not None:
        if args.paths_dir is None or args.old_binary is None or args.new_binary is None:
            parser.error(
                "artifact identity requires --paths-dir, --old-binary, "
                "and --new-binary"
            )
        try:
            identity_check = validate_live_artifact_identity(
                artifact_identity,
                paths_dir=args.paths_dir,
                old_binary=args.old_binary,
                new_binary=args.new_binary,
                task_uid=args.pair_id or None,
                require_executable=True,
                expected_input_schema_hash=(
                    input_contract.get("schema_hash")
                    if input_contract
                    else None
                ),
                expected_domain_hash=(
                    input_contract.get("domain_hash")
                    if input_contract
                    else None
                ),
            )
        except ArtifactIdentityError as exc:
            identity_validation_error = str(exc)
        else:
            _ACTIVE_ARTIFACT_IDENTITY.set(artifact_identity)
    _ACTIVE_TASK_UID.set(args.pair_id)
    if identity_validation_error is not None:
        result = {
            "method": "artifact_identity_guard",
            "prediction": None,
            "verdict": "UNK",
            "program_verdict": "UNK",
            "failure_stage": "artifact_identity_error",
            "failure_reason": identity_validation_error,
            "artifact_status": "identity_error",
            "eq_proof_eligible": False,
            "counterexample_execution_eligible": False,
            "pair_id": args.pair_id,
            "artifact_identity": artifact_identity,
            "artifact_identity_check": None,
            "artifact_identity_hash": artifact_identity.get(
                "artifact_identity_sha256"
            ),
            "binary_identity_source": "fresh_build_manifest",
            "candidate_audit": candidate_audit_summary(),
        }
        result = attach_failure_classification(result)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        report_payload = public_candidate_value(result)
        _atomic_write_text(
            args.out,
            json.dumps(
                report_payload,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
        )
        print(json.dumps(report_payload, ensure_ascii=False))
        return 3
    if args.counterexample_only:
        if args.old_binary is None or args.new_binary is None:
            parser.error("--counterexample-only requires both binary paths")
        if not args.input_schema_json:
            parser.error("--counterexample-only requires --input-schema-json")
        raw_schema = json.loads(args.input_schema_json)
        if isinstance(raw_schema, dict):
            raw_schema = raw_schema.get("inputs", [])
        if not isinstance(raw_schema, list):
            parser.error("--input-schema-json must contain a list or {'inputs': list}")
        result = verify_counterexample_only(
            args.old_binary,
            args.new_binary,
            raw_schema,
            pair_id=args.pair_id,
            cache_path=args.counterexample_cache,
            artifact_status=args.artifact_status,
            input_ranges=(
                json.loads(args.input_ranges_json)
                if args.input_ranges_json
                else None
            ),
            timeout_ms=args.timeout_ms,
        )
    else:
        if args.paths_dir is None:
            parser.error("--paths-dir is required unless --counterexample-only is used")
        result = verify_ranked_queue(
            args.paths_dir,
            args.ranking,
            args.timeout_ms,
            args.naive,
            parse_truth_pairs(args.truth_pairs_json),
            parse_bool(args.program_ground_truth),
            args.allow_legacy_artifacts,
            not args.one_to_one_only,
            args.complete_path_matching,
            pair_id=args.pair_id or None,
            counterexample_cache=args.counterexample_cache,
            static_only=args.static_only,
        )
        exploration = load_exploration_status(args.paths_dir)
        semantic_audit = semantic_model_eq_audit(exploration)
        eq_proof_eligible = (
            exploration_is_complete(
                exploration["symbolic_oldV"],
                path_count=len(
                    list(args.paths_dir.glob("symbolic_oldV_path_*.txt"))
                ),
                require_proof_eligible=not args.allow_legacy_artifacts,
            )
            and exploration_is_complete(
                exploration["symbolic_newV"],
                path_count=len(
                    list(args.paths_dir.glob("symbolic_newV_path_*.txt"))
                ),
                require_proof_eligible=not args.allow_legacy_artifacts,
            )
            and semantic_audit.get("eq_eligible") is True
        )
        result["eq_proof_eligible"] = eq_proof_eligible
        result["return_value_contract"] = {
            "entry_signature": args.entry_signature,
            "return_type": return_type,
            "kind": (
                "float"
                if is_float_return_type(return_type)
                else ("non_float" if return_type else "unspecified")
            ),
            "source": "verifier_cli" if return_type else "path_metadata_only",
        }
        result = apply_semantic_model_gate(result, semantic_audit)
        result["counterexample_execution_eligible"] = bool(
            args.old_binary
            or (
                args.paths_dir
                and list(args.paths_dir.glob("symbolic_oldV_path_*.txt"))
                and list(args.paths_dir.glob("symbolic_newV_path_*.txt"))
            )
        )
        result["artifact_status"] = (
            "proof_eligible"
            if eq_proof_eligible
            else "incomplete_or_lossy"
        )
    result = enforce_result_domain_contract(result, input_contract)
    b1_comparison = (
        json.loads(args.b1_comparison_json.read_text(encoding="utf-8-sig"))
        if args.b1_comparison_json
        else None
    )
    result = attach_b1_local_lemma(result, b1_comparison)
    termination_proof = (
        json.loads(
            args.termination_proof_json.read_text(encoding="utf-8-sig")
        )
        if args.termination_proof_json
        else None
    )
    result = attach_termination_mismatch_proof(
        result,
        termination_proof,
    )
    result["program_verdict"] = result.get("verdict")
    result["candidate_audit"] = candidate_audit_summary()
    result.update(historical_unknown_summary(result.get("required_obligations", [])))
    result["pair_id"] = args.pair_id
    result["program_ground_truth_used"] = False
    result["oracle_path_truth_used"] = args.truth_pairs_json is not None
    result["solver_strategy"] = active_strategy()
    result["solver_audit"] = solver_audit_summary()
    result["smt_audit_all_queries"] = args.smt_audit_all_queries
    result["artifact_identity"] = artifact_identity
    result["artifact_identity_check"] = identity_check
    result["artifact_identity_hash"] = (
        artifact_identity.get("artifact_identity_sha256")
        if artifact_identity is not None
        else None
    )
    result["binary_identity_source"] = (
        "fresh_build_manifest"
        if artifact_identity is not None
        else "legacy_path_inference"
    )
    result["static_only"] = args.static_only
    result["input_contract"] = input_contract
    result["input_domain_profile_id"] = (
        input_contract.get("profile_id") if input_contract else None
    )
    result["domain_hash"] = (
        input_contract.get("domain_hash") if input_contract else None
    )
    result = attach_failure_classification(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report_payload = public_candidate_value(result)
    _atomic_write_text(
        args.out,
        json.dumps(
            report_payload,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )
    print(json.dumps(report_payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
