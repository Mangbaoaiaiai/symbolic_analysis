"""Program-level input, replay, and witness-cache helpers.

This module deliberately does not assign equivalence labels. It only checks
whether a fully typed concrete input produces a stable observed difference on
the original binaries. Path completeness and EQ proof eligibility are managed
by the caller.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


CACHE_SCHEMA = "symbolicana.counterexample_witness_cache.v1"
INPUT_SCHEMA = "symbolicana.program_input_schema.v1"
_SCANF_CONVERSION = re.compile(
    r"%(?:\*|\d+|\d+\$)*(?:hh|h|ll|l|j|z|t|L)?"
    r"[diouxXfFeEgGaAcspn]"
)
_FLOAT_ZERO_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"([+-]?(?:(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?"
    r"|\d+[eE][+-]?\d+|0[xX][0-9A-Fa-f]+(?:\.[0-9A-Fa-f]*)?[pP][+-]?\d+))"
    r"(?![A-Za-z0-9_])"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_schema(schema: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, raw in enumerate(schema):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "bitvec")
        if kind not in {"bitvec", "float"}:
            raise ValueError(f"unsupported input kind at {index}: {kind}")
        bits = int(raw.get("bits", 32) or 32)
        if bits <= 0:
            raise ValueError(f"invalid input width at {index}: {bits}")
        normalized.append(
            {
                "index": int(raw.get("index", index) or index),
                "name": str(raw.get("name") or f"arg_{index}"),
                "c_type": str(raw.get("c_type") or kind),
                "kind": kind,
                "bits": bits,
                "precision": int(raw.get("precision", 0) or 0),
            }
        )
    normalized.sort(key=lambda item: item["index"])
    return normalized


def schema_digest(schema: Iterable[dict[str, Any]]) -> str:
    canonical = canonical_schema(schema)
    payload = json.dumps(
        [
            {
                "index": item["index"],
                "name": item["name"],
                "kind": item["kind"],
                "bits": item["bits"],
                "precision": item["precision"],
            }
            for item in canonical
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def scalar_type_info(c_type: str, *, arch_bits: int = 64) -> dict[str, Any]:
    """Return the ABI scalar kind and width for supported C input types."""
    text = re.sub(r"\s+", " ", c_type.strip())
    text = re.sub(r"\b(const|volatile|register|restrict)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    if "*" in text:
        return {
            "c_type": c_type,
            "kind": "bitvec",
            "bits": int(arch_bits),
            "precision": 0,
            "supported": False,
            "reason": "pointer_arguments_require_explicit_input_parser",
        }
    if text in {"double"}:
        return {
            "c_type": c_type,
            "kind": "float",
            "bits": 64,
            "precision": 0,
            "supported": True,
        }
    if text in {"float"}:
        return {
            "c_type": c_type,
            "kind": "float",
            "bits": 32,
            "precision": 0,
            "supported": True,
        }
    if text.endswith(" long double"):
        return {
            "c_type": c_type,
            "kind": "float",
            "bits": 80,
            "precision": 0,
            "supported": False,
            "reason": "long_double_not_supported_by_replay_schema",
        }
    widths = {
        "_bool": 8,
        "bool": 8,
        "char": 8,
        "signed char": 8,
        "unsigned char": 8,
        "short": 16,
        "short int": 16,
        "unsigned short": 16,
        "unsigned short int": 16,
        "int": 32,
        "signed": 32,
        "signed int": 32,
        "unsigned": 32,
        "unsigned int": 32,
        "enum": 32,
        "long": 64 if arch_bits == 64 else 32,
        "long int": 64 if arch_bits == 64 else 32,
        "unsigned long": 64 if arch_bits == 64 else 32,
        "unsigned long int": 64 if arch_bits == 64 else 32,
        "long long": 64,
        "long long int": 64,
        "unsigned long long": 64,
        "unsigned long long int": 64,
        "size_t": int(arch_bits),
        "ssize_t": int(arch_bits),
        "intptr_t": int(arch_bits),
        "uintptr_t": int(arch_bits),
    }
    if text in widths:
        return {
            "c_type": c_type,
            "kind": "bitvec",
            "bits": widths[text],
            "precision": 0,
            "supported": True,
        }
    return {
        "c_type": c_type,
        "kind": "bitvec",
        "bits": 32,
        "precision": 0,
        "supported": False,
        "reason": "unknown_scalar_type",
    }


def _scanf_conversion_type(conversion: str, *, arch_bits: int) -> dict[str, Any]:
    match = re.search(
        r"(?:hh|h|ll|l|j|z|t|L)?[diouxXfFeEgGaAcspn]$",
        conversion,
        flags=re.IGNORECASE,
    )
    if match is None:
        return {
            "kind": "bitvec",
            "bits": 32,
            "precision": 0,
            "supported": False,
            "reason": "unparsed_scanf_conversion",
        }
    specifier = conversion
    length = re.search(r"(hh|h|ll|l|j|z|t|L)(?=[diouxXfFeEgGaAcspn]$)", specifier)
    conversion_char = specifier[-1]
    length_token = length.group(1) if length else ""
    if conversion_char in "fFeEgGaA":
        if length_token == "L":
            return {
                "kind": "float",
                "bits": 80,
                "precision": 0,
                "supported": False,
                "reason": "long_double_not_supported_by_replay_schema",
            }
        return {
            "kind": "float",
            "bits": 32 if conversion_char in "fFeEgGaA" and length_token != "l" else 64,
            "precision": 0,
            "supported": True,
        }
    widths = {
        "hh": 8,
        "h": 16,
        "": 32,
        "l": 64 if arch_bits == 64 else 32,
        "ll": 64,
        "j": 64,
        "z": int(arch_bits),
        "t": int(arch_bits),
    }
    return {
        "kind": "bitvec",
        "bits": widths.get(length_token, 32),
        "precision": 0,
        "supported": conversion_char not in "spn",
        "reason": (
            "scanf_string_or_pointer_input_not_supported"
            if conversion_char in "spn"
            else ""
        ),
    }


def parse_scanf_schema(
    source: Path,
    *,
    arch_bits: int = 64,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a generated benchmark's single concrete scanf format."""
    text = source.read_text(encoding="utf-8", errors="replace")
    matches = list(
        re.finditer(
            r"\bscanf\s*\(\s*\"((?:\\.|[^\"\\])*)\"",
            text,
        )
    )
    if not matches:
        return [], {
            "schema": INPUT_SCHEMA,
            "source": str(source),
            "zero_input": True,
            "supported": True,
            "reason": "no_scanf_input",
        }
    if len(matches) != 1:
        return [], {
            "schema": INPUT_SCHEMA,
            "source": str(source),
            "zero_input": False,
            "supported": False,
            "reason": "multiple_scanf_calls",
        }
    raw_format = matches[0].group(1)
    try:
        format_text = bytes(raw_format, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        format_text = raw_format
    conversions = _SCANF_CONVERSION.findall(format_text)
    schema = []
    supported = True
    reasons = []
    for index, conversion in enumerate(conversions):
        info = _scanf_conversion_type(conversion, arch_bits=arch_bits)
        supported = supported and bool(info["supported"])
        if info.get("reason"):
            reasons.append(str(info["reason"]))
        schema.append(
            {
                "index": index,
                "name": f"arg_{index}",
                "c_type": conversion,
                "kind": info["kind"],
                "bits": int(info["bits"]),
                "precision": int(info.get("precision", 0) or 0),
            }
        )
    return canonical_schema(schema), {
        "schema": INPUT_SCHEMA,
        "source": str(source),
        "format": format_text,
        "zero_input": not schema,
        "supported": supported,
        "reason": ";".join(dict.fromkeys(reasons)),
    }


def make_inputs(
    schema: Iterable[dict[str, Any]],
    values: Iterable[int | float],
) -> list[dict[str, Any]]:
    canonical = canonical_schema(schema)
    value_list = list(values)
    if len(canonical) != len(value_list):
        raise ValueError(
            f"input schema has {len(canonical)} positions, got {len(value_list)} values"
        )
    inputs = []
    for spec, value in zip(canonical, value_list):
        if spec["kind"] == "float":
            number = float(value)
            raw = None
            if math.isfinite(number) and number == 0:
                raw = 0
            inputs.append(
                {
                    "name": spec["name"],
                    "kind": "float",
                    "bits": spec["bits"],
                    "value": number,
                    "ieee_bits": raw,
                }
            )
        else:
            integer = int(value)
            mask = (1 << spec["bits"]) - 1
            inputs.append(
                {
                    "name": spec["name"],
                    "kind": "bitvec",
                    "bits": spec["bits"],
                    "value": integer,
                    "unsigned": integer & mask,
                }
            )
    return inputs


def validate_inputs(
    schema: Iterable[dict[str, Any]],
    inputs: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    canonical = canonical_schema(schema)
    errors = []
    if not isinstance(inputs, list):
        return [], ["inputs_not_a_list"]
    if len(inputs) != len(canonical):
        errors.append(
            f"input_count_mismatch:{len(inputs)}!={len(canonical)}"
        )
    ordered = []
    for index, spec in enumerate(canonical):
        if index >= len(inputs) or not isinstance(inputs[index], dict):
            errors.append(f"position_{index}_missing")
            continue
        item = inputs[index]
        if item.get("kind") != spec["kind"]:
            errors.append(
                f"position_{index}_kind:{item.get('kind')}!={spec['kind']}"
            )
        if int(item.get("bits", 0) or 0) != spec["bits"]:
            errors.append(
                f"position_{index}_bits:{item.get('bits')}!={spec['bits']}"
            )
        normalized = dict(item)
        normalized["name"] = spec["name"]
        ordered.append(normalized)
    return ordered, errors


def format_replay_value(item: dict[str, Any]) -> str:
    value = item.get("value")
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return value.hex()
    return str(value)


def normalize_signed_zero_text(text: str) -> tuple[str, int]:
    """Normalize textual floating-point zero signs without touching integers."""
    replacements = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        token = match.group(1)
        try:
            value = (
                float.fromhex(token)
                if token.lower().startswith(("-0x", "+0x", "0x"))
                else float(token)
            )
        except ValueError:
            return token
        if value == 0.0:
            replacements += 1
            return "0.0"
        return token

    return _FLOAT_ZERO_TOKEN.sub(replace, text), replacements


def run_program(
    binary: Path,
    stdin: str,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(binary)],
            input=stdin,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "completed": True,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "completed": False,
            "reason": type(exc).__name__,
            "error": str(exc),
        }


def classify_replay(
    left_binary: Path,
    right_binary: Path,
    schema: Iterable[dict[str, Any]],
    inputs: Any,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    ordered, validation_errors = validate_inputs(schema, inputs)
    if validation_errors:
        return {
            "confirmed": False,
            "classification": "unconfirmed",
            "reason": "input_schema_validation_failed",
            "validation_errors": validation_errors,
        }
    stdin = " ".join(format_replay_value(item) for item in ordered) + "\n"
    left_runs = [
        run_program(left_binary, stdin, timeout_seconds=timeout_seconds)
        for _ in range(2)
    ]
    right_runs = [
        run_program(right_binary, stdin, timeout_seconds=timeout_seconds)
        for _ in range(2)
    ]
    runs = left_runs + right_runs
    if any(not run.get("completed") for run in runs):
        return {
            "confirmed": False,
            "classification": "unconfirmed",
            "reason": "replay_failed",
            "stdin": stdin,
            "inputs": ordered,
            "left_runs": left_runs,
            "right_runs": right_runs,
        }
    if left_runs[0] != left_runs[1] or right_runs[0] != right_runs[1]:
        return {
            "confirmed": False,
            "classification": "unstable",
            "reason": "repeated_execution_unstable",
            "stdin": stdin,
            "inputs": ordered,
            "left_runs": left_runs,
            "right_runs": right_runs,
        }
    left = left_runs[0]
    right = right_runs[0]
    left_stdout, left_zeroes = normalize_signed_zero_text(str(left.get("stdout", "")))
    right_stdout, right_zeroes = normalize_signed_zero_text(
        str(right.get("stdout", ""))
    )
    left_stderr, left_stderr_zeroes = normalize_signed_zero_text(
        str(left.get("stderr", ""))
    )
    right_stderr, right_stderr_zeroes = normalize_signed_zero_text(
        str(right.get("stderr", ""))
    )
    observables_equal = (
        left_stdout == right_stdout and left_stderr == right_stderr
    )
    left_rc = int(left.get("returncode", 0) or 0)
    right_rc = int(right.get("returncode", 0) or 0)
    if left_rc < 0 or right_rc < 0:
        classification = (
            "both_ub_candidate"
            if left_rc < 0 and right_rc < 0
            else "one_sided_ub_candidate"
        )
        confirmed = False
        reason = "fatal_signal_requires_ub_evidence"
    elif left_rc == 0 and right_rc == 0 and not observables_equal:
        classification = "observable_mismatch"
        confirmed = True
        reason = "both_defined_with_observable_difference"
    elif (left_rc == 0) != (right_rc == 0):
        classification = "definedness_mismatch"
        confirmed = True
        reason = "one_side_success_other_defined_rejection"
    elif not observables_equal:
        classification = "defined_rejection_mismatch"
        confirmed = True
        reason = "both_sides_defined_with_different_outcome"
    else:
        classification = "same_observed_behavior"
        confirmed = False
        reason = "no_observable_difference"
    return {
        "confirmed": confirmed,
        "classification": classification,
        "reason": reason,
        "stdin": stdin,
        "inputs": ordered,
        "left": left,
        "right": right,
        "left_runs": left_runs,
        "right_runs": right_runs,
        "comparison": {
            "stdout_equal_after_signed_zero_normalization": left_stdout == right_stdout,
            "stderr_equal_after_signed_zero_normalization": left_stderr == right_stderr,
            "signed_zero_replacements": (
                left_zeroes
                + right_zeroes
                + left_stderr_zeroes
                + right_stderr_zeroes
            ),
        },
    }


def load_witness_cache(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"schema": CACHE_SCHEMA, "witnesses": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != CACHE_SCHEMA:
        raise ValueError(f"unexpected witness cache schema: {payload.get('schema')}")
    witnesses = payload.get("witnesses")
    if not isinstance(witnesses, list):
        raise ValueError("witness cache witnesses must be a list")
    return payload


def witnesses_for_case(payload: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    return [
        item
        for item in payload.get("witnesses", [])
        if isinstance(item, dict) and str(item.get("case_id")) == case_id
    ]


def provenance_errors(
    witness: dict[str, Any],
    expected_hashes: dict[str, str | None],
) -> list[str]:
    errors = []
    recorded = witness.get("binary_sha256")
    if not isinstance(recorded, dict):
        return ["missing_binary_sha256"]
    for side, expected in expected_hashes.items():
        actual = recorded.get(side)
        if not expected:
            errors.append(f"missing_current_hash:{side}")
        elif not actual:
            errors.append(f"missing_cached_hash:{side}")
        elif str(actual).lower() != str(expected).lower():
            errors.append(f"binary_sha256_mismatch:{side}")
    schema_hash = witness.get("input_schema_sha256")
    if not schema_hash:
        errors.append("missing_input_schema_sha256")
    return errors


def replay_cached_witnesses(
    cache_path: Path | None,
    case_id: str,
    left_binary: Path,
    right_binary: Path,
    schema: Iterable[dict[str, Any]],
    *,
    current_binary_hashes: dict[str, str | None],
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    payload = load_witness_cache(cache_path)
    witnesses = witnesses_for_case(payload, case_id)
    attempts = []
    current_schema_hash = schema_digest(schema)
    for witness in witnesses:
        errors = provenance_errors(witness, current_binary_hashes)
        if witness.get("input_schema_sha256") not in {None, current_schema_hash}:
            errors.append("input_schema_sha256_mismatch")
        if errors:
            attempts.append(
                {
                    "witness_id": witness.get("witness_id"),
                    "provenance_ok": False,
                    "provenance_errors": errors,
                }
            )
            continue
        replay = classify_replay(
            left_binary,
            right_binary,
            schema,
            witness.get("inputs"),
            timeout_seconds=timeout_seconds,
        )
        attempts.append(
            {
                "witness_id": witness.get("witness_id"),
                "source": witness.get("source"),
                "evidence_path": witness.get("evidence_path"),
                "discovered_by": witness.get("discovered_by"),
                "provenance_ok": True,
                "replay": replay,
            }
        )
        if replay.get("confirmed"):
            return {
                "found": True,
                "cache_path": str(cache_path) if cache_path else None,
                "witness_id": witness.get("witness_id"),
                "source": witness.get("source"),
                "evidence_path": witness.get("evidence_path"),
                "reused_existing_evidence": True,
                "newly_discovered": False,
                "replay": replay,
                "attempts": attempts,
            }
    return {
        "found": False,
        "cache_path": str(cache_path) if cache_path else None,
        "attempts": attempts,
    }
