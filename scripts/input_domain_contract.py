#!/usr/bin/env python3
"""Shared Round016 input-domain contract and value validation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from program_counterexample import parse_scanf_schema, scalar_type_info


DEFAULT_PROFILE_ID = "ardiff_numeric_bounds_v1"
DEFAULT_PROFILE: dict[str, Any] = {
    "schema": "symbolicana.input_domain_profile.v1",
    "profile_id": DEFAULT_PROFILE_ID,
    "integer": {
        "minimum": -100,
        "maximum": 100,
        "unsigned_intersection": [0, 100],
        "apply_to_pointer_addresses": False,
    },
    "floating_point": {
        "minimum": -100.0,
        "maximum": 100.0,
        "include_endpoints": True,
        "include_positive_zero": True,
        "include_negative_zero": True,
        "include_subnormal": True,
        "include_nan": False,
        "include_positive_infinity": False,
        "include_negative_infinity": False,
    },
    "internal_values": {
        "restrict": False,
        "nan_inf_follow_program_semantics": True,
    },
    "application": {
        "se": True,
        "smt": True,
        "model_to_input": True,
        "replay": True,
        "final_acceptance": True,
    },
}


def load_profile(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        return json.loads(json.dumps(DEFAULT_PROFILE))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_schema(
    schema: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(schema):
        item = dict(raw)
        item["index"] = int(item.get("index", index) or index)
        item["name"] = str(item.get("name") or f"arg_{index}")
        item["kind"] = str(item.get("kind") or "bitvec")
        item["c_type"] = str(item.get("c_type") or item["kind"])
        item["bits"] = int(item.get("bits", 32) or 32)
        item["precision"] = int(item.get("precision", 0) or 0)
        if item["kind"] not in {"bitvec", "float"}:
            raise ValueError(f"unsupported input kind at {index}: {item['kind']}")
        if item["bits"] <= 0:
            raise ValueError(f"invalid input width at {index}: {item['bits']}")
        normalized.append(item)
    normalized.sort(key=lambda entry: entry["index"])
    return normalized


def schema_from_signature(
    signature: str | None,
    *,
    arch_bits: int = 64,
) -> list[dict[str, Any]]:
    """Build an ABI input schema from a canonical ``ret(types...)`` signature."""
    if not signature:
        return []
    match = re.match(r"^\s*[^()]+\((?P<args>[^()]*)\)\s*$", signature)
    if match is None:
        raise ValueError(f"invalid canonical signature: {signature}")
    raw_args = match.group("args").strip()
    if not raw_args or raw_args == "void":
        return []
    schema: list[dict[str, Any]] = []
    for index, raw_type in enumerate(raw_args.split(",")):
        c_type = raw_type.strip()
        info = scalar_type_info(c_type, arch_bits=arch_bits)
        schema.append(
            {
                "index": index,
                "name": f"arg_{index}",
                "c_type": c_type,
                "kind": info["kind"],
                "bits": int(info["bits"]),
                "precision": int(info.get("precision", 0) or 0),
            }
        )
    return canonical_schema(schema)


def signature_return_type(signature: str | None) -> str | None:
    """Return the canonical C return type from a ``ret(args...)`` signature."""
    if not signature:
        return None
    match = re.match(r"^\s*(?P<ret>[^()]+)\([^()]*\)\s*$", signature)
    if match is None:
        return None
    return " ".join(match.group("ret").split())


def is_float_return_type(c_type: str | None) -> bool:
    """Recognize scalar IEEE floating-point C return types."""
    if not c_type:
        return False
    text = re.sub(r"\s+", " ", str(c_type).strip().lower())
    if "*" in text:
        return False
    words = [
        word
        for word in text.split()
        if word not in {"const", "volatile", "restrict", "_atomic"}
    ]
    normalized = " ".join(words)
    return normalized in {"float", "double", "long double"}


def semantic_schema_key(
    schema: Iterable[dict[str, Any]],
) -> tuple[tuple[str, int, int, bool], ...]:
    """Return the ABI-semantic schema fields used for artifact compatibility."""
    return tuple(
        (
            str(item["kind"]),
            int(item["bits"]),
            int(item["precision"]),
            is_unsigned_type(str(item["c_type"])),
        )
        for item in canonical_schema(schema)
    )


def extract_c_snippet_signature(source: Path | None) -> str | None:
    if not source or not source.is_file():
        return None
    text = source.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"\b(?P<ret>bool|char|int|long|double|float|short)\s+snippet"
        r"\s*\((?P<args>[^)]*)\)",
        text,
    )
    if not match:
        return None
    arg_types = []
    type_words = {
        "bool",
        "_Bool",
        "char",
        "short",
        "int",
        "long",
        "signed",
        "unsigned",
        "float",
        "double",
        "size_t",
        "ssize_t",
        "intptr_t",
        "uintptr_t",
    }
    for raw_arg in match.group("args").split(","):
        raw_arg = raw_arg.strip()
        if not raw_arg or raw_arg == "void":
            continue
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\*", raw_arg)
        words = [
            token
            for token in tokens
            if token in type_words and token not in {"const", "volatile"}
        ]
        if not words:
            continue
        if "double" in words and "long" in words:
            c_type = "long double"
        elif "unsigned" in words:
            base = [
                word
                for word in ("short", "long", "int", "char")
                if word in words
            ]
            c_type = " ".join(["unsigned", *base]) or "unsigned int"
        elif "signed" in words:
            base = [
                word
                for word in ("short", "long", "int", "char")
                if word in words
            ]
            c_type = " ".join(["signed", *base]) or "signed int"
        elif "double" in words:
            c_type = "double"
        elif "float" in words:
            c_type = "float"
        elif "long long" in " ".join(words):
            c_type = "long long"
        elif "long" in words:
            c_type = "long"
        elif "short" in words:
            c_type = "short"
        elif "char" in words:
            c_type = "char"
        elif "bool" in words or "_Bool" in words:
            c_type = "bool"
        else:
            c_type = "int"
        if "*" in tokens:
            c_type += " *"
        arg_types.append(c_type)
    return f"{match.group('ret')}({','.join(arg_types)})"


def input_schema_for_source(
    source: Path,
    *,
    arch_bits: int = 64,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Resolve a source's concrete ABI input schema without guessing inputs."""
    scanf_schema, metadata = parse_scanf_schema(source, arch_bits=arch_bits)
    signature = extract_c_snippet_signature(source)
    signature_schema = schema_from_signature(signature, arch_bits=arch_bits)
    metadata = dict(metadata)
    metadata["signature"] = signature
    signature_supported = True
    if signature:
        match = re.match(r"^\s*[^()]+\((?P<args>[^()]*)\)\s*$", signature)
        raw_args = match.group("args").strip() if match else ""
        type_args = (
            []
            if not raw_args or raw_args == "void"
            else [item.strip() for item in raw_args.split(",")]
        )
        signature_supported = all(
            bool(scalar_type_info(item, arch_bits=arch_bits).get("supported"))
            for item in type_args
        )
    metadata["signature_supported"] = signature_supported
    if scanf_schema:
        compatible = (
            semantic_schema_key(scanf_schema)
            == semantic_schema_key(signature_schema)
        )
        metadata["schema_source"] = "scanf"
        metadata["signature_schema"] = signature_schema
        metadata["signature_schema_compatible"] = compatible
        if not compatible:
            metadata["supported"] = False
            metadata["reason"] = "scanf_and_snippet_schema_mismatch"
        return scanf_schema, metadata
    if signature is not None:
        schema = signature_schema
        return schema, {
            "schema": metadata.get("schema"),
            "source": str(source),
            "signature": signature,
            "schema_source": "snippet_signature",
            "format": None,
            "zero_input": not schema,
            "supported": signature_supported,
            "reason": (
                ""
                if signature_supported
                else "unsupported_snippet_signature_type"
            ),
        }
    metadata["schema_source"] = "none"
    metadata["supported"] = False
    metadata["reason"] = "no_input_schema_source"
    return scanf_schema, metadata


def schema_hash(schema: Iterable[dict[str, Any]]) -> str:
    canonical = canonical_schema(schema)
    return sha256_json(
        [
            {
                "index": item["index"],
                "name": item["name"],
                "kind": item["kind"],
                "c_type": item["c_type"],
                "bits": item["bits"],
                "precision": item["precision"],
            }
            for item in canonical
        ]
    )


def is_unsigned_type(c_type: str) -> bool:
    text = re.sub(r"\s+", " ", str(c_type).strip().lower())
    if text.startswith("%"):
        specifier = text.rsplit("%", 1)[-1]
        conversion = specifier[-1:] if specifier else ""
        return conversion in {"u", "o", "x", "X"}
    return "unsigned" in text or "size_t" in text or "uint" in text


def is_bool_type(c_type: str) -> bool:
    text = str(c_type).strip().lower()
    return text in {"bool", "_bool"} or text.endswith(" bool")


def is_enum_type(c_type: str) -> bool:
    return str(c_type).strip().lower().startswith("enum ")


def input_bounds(
    spec: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = profile or DEFAULT_PROFILE
    item = canonical_schema([spec])[0]
    if item["kind"] == "float":
        floats = contract["floating_point"]
        return {
            "kind": "float",
            "minimum": float(floats["minimum"]),
            "maximum": float(floats["maximum"]),
            "finite": True,
            "include_negative_zero": bool(floats.get("include_negative_zero", True)),
            "include_positive_zero": bool(floats.get("include_positive_zero", True)),
            "include_subnormal": bool(floats.get("include_subnormal", True)),
        }
    integers = contract["integer"]
    bits = int(item["bits"])
    minimum = int(integers["minimum"])
    maximum = int(integers["maximum"])
    if is_unsigned_type(item["c_type"]):
        unsigned = integers.get("unsigned_intersection") or [
            0,
            maximum,
        ]
        minimum = max(0, int(unsigned[0]))
        maximum = min((1 << bits) - 1, max(0, int(unsigned[1])))
        signed = False
    else:
        minimum = max(-(1 << (bits - 1)), minimum)
        maximum = min((1 << (bits - 1)) - 1, maximum)
        signed = True
    if is_bool_type(item["c_type"]):
        minimum = max(minimum, 0)
        maximum = min(maximum, 1)
    return {
        "kind": "bitvec",
        "minimum": minimum,
        "maximum": maximum,
        "signed": signed,
        "bits": bits,
    }


def build_contract(
    schema: Iterable[dict[str, Any]],
    *,
    profile: dict[str, Any] | None = None,
    pair_id: str = "",
    source: str = "",
) -> dict[str, Any]:
    contract = profile or DEFAULT_PROFILE
    canonical = canonical_schema(schema)
    inputs = []
    unsupported = []
    for item in canonical:
        c_type = item["c_type"]
        if "*" in c_type:
            unsupported.append(
                {
                    "index": item["index"],
                    "reason": "pointer_input_requires_object_layout",
                }
            )
            bounds = {
                "kind": item["kind"],
                "domain": "not_applicable_pointer_address",
            }
        else:
            bounds = input_bounds(item, contract)
        inputs.append(
            {
                **item,
                "signed": (
                    bounds.get("signed")
                    if bounds.get("signed") is not None
                    else None
                ),
                "bool": is_bool_type(c_type),
                "enum": is_enum_type(c_type),
                "bounds": bounds,
            }
        )
    payload = {
        "schema": "symbolicana.input_contract.v1",
        "pair_id": pair_id,
        "source": source,
        "profile_id": str(contract.get("profile_id") or DEFAULT_PROFILE_ID),
        "profile": contract,
        "schema_hash": schema_hash(canonical),
        "inputs": inputs,
        "unsupported_inputs": unsupported,
        "status": "supported" if not unsupported else "unsupported",
        "source_preconditions": [],
    }
    payload["domain_hash"] = sha256_json(
        {
            "profile_id": payload["profile_id"],
            "profile": contract,
            "schema_hash": payload["schema_hash"],
            "inputs": payload["inputs"],
            "source_preconditions": payload["source_preconditions"],
        }
    )
    return payload


def value_in_domain(
    item: dict[str, Any],
    spec: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    canonical = canonical_schema([spec])[0]
    bounds = input_bounds(canonical, profile)
    bits = int(canonical["bits"])
    if canonical["kind"] == "float":
        raw_value = item.get("value")
        if not isinstance(raw_value, (int, float)):
            return False, "float_value_not_numeric"
        value = float(raw_value)
        if not math.isfinite(value):
            return False, "non_finite_float"
        if value < float(bounds["minimum"]) or value > float(bounds["maximum"]):
            return False, "float_outside_numeric_bounds"
        ieee_bits = item.get("ieee_bits")
        if ieee_bits is not None:
            if not isinstance(ieee_bits, int) or not 0 <= ieee_bits < (1 << bits):
                return False, "invalid_ieee_bits"
        return True, ""

    raw_value = item.get("value")
    if not isinstance(raw_value, int):
        return False, "integer_value_not_int"
    if bounds.get("signed", True):
        lower = -(1 << (bits - 1))
        upper = (1 << (bits - 1)) - 1
        value = int(raw_value)
    else:
        lower = 0
        upper = (1 << bits) - 1
        value = int(item.get("unsigned", raw_value))
    if value < lower or value > upper:
        return False, "integer_outside_target_type"
    if value < int(bounds["minimum"]) or value > int(bounds["maximum"]):
        return False, "integer_outside_numeric_bounds"
    return True, ""


def validate_values(
    schema: Iterable[dict[str, Any]],
    inputs: Any,
    profile: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    canonical = canonical_schema(schema)
    if not isinstance(inputs, list):
        return [], ["inputs_not_a_list"]
    if len(inputs) != len(canonical):
        return [], [f"input_count_mismatch:{len(inputs)}!={len(canonical)}"]
    ordered: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, (item, spec) in enumerate(zip(inputs, canonical)):
        if not isinstance(item, dict):
            errors.append(f"position_{index}_not_an_object")
            continue
        for key in ("kind", "bits"):
            actual = item.get(key)
            expected = spec[key]
            if str(actual) != str(expected):
                errors.append(
                    f"position_{index}_{key}:{actual}!={expected}"
                )
        valid, reason = value_in_domain(item, spec, profile)
        if not valid:
            errors.append(f"position_{index}:{reason}")
        normalized = dict(item)
        normalized["name"] = spec["name"]
        ordered.append(normalized)
    return ordered, errors


def claripy_domain_constraints(
    expression: Any,
    spec: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    claripy_module: Any = None,
):
    claripy = claripy_module
    if claripy is None:
        import claripy as claripy  # type: ignore
    canonical = canonical_schema([spec])[0]
    bounds = input_bounds(canonical, profile)
    if canonical["kind"] == "float":
        sort = (
            claripy.FSORT_DOUBLE
            if int(canonical["bits"]) == 64
            else claripy.FSORT_FLOAT
        )
        return [
            claripy.fpGEQ(
                expression,
                claripy.FPV(float(bounds["minimum"]), sort),
            ),
            claripy.fpLEQ(
                expression,
                claripy.FPV(float(bounds["maximum"]), sort),
            ),
        ]
    bits = int(canonical["bits"])
    lower = claripy.BVV(int(bounds["minimum"]), bits)
    upper = claripy.BVV(int(bounds["maximum"]), bits)
    if bounds.get("signed", True):
        return [
            claripy.SGE(expression, lower),
            claripy.SLE(expression, upper),
        ]
    return [
        claripy.UGE(expression, claripy.BVV(0, bits)),
        claripy.ULE(expression, upper),
    ]


def z3_domain_constraints(
    expression: Any,
    spec: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
):
    from z3 import BitVecVal, BoolRef, FPVal, FPSort, UGE, ULE
    from z3.z3core import Z3_mk_fpa_geq, Z3_mk_fpa_leq

    canonical = canonical_schema([spec])[0]
    bounds = input_bounds(canonical, profile)
    if canonical["kind"] == "float":
        ctx = expression.ctx
        sort = (
            FPSort(11, 53, ctx=ctx)
            if int(canonical["bits"]) == 64
            else FPSort(8, 24, ctx=ctx)
        )
        lower = FPVal(float(bounds["minimum"]), sort, ctx=ctx)
        upper = FPVal(float(bounds["maximum"]), sort, ctx=ctx)
        return [
            BoolRef(
                Z3_mk_fpa_geq(
                    ctx.ref(),
                    expression.as_ast(),
                    lower.as_ast(),
                ),
                ctx,
            ),
            BoolRef(
                Z3_mk_fpa_leq(
                    ctx.ref(),
                    expression.as_ast(),
                    upper.as_ast(),
                ),
                ctx,
            ),
        ]
    bits = int(canonical["bits"])
    ctx = expression.ctx
    lower = BitVecVal(int(bounds["minimum"]), bits, ctx=ctx)
    upper = BitVecVal(int(bounds["maximum"]), bits, ctx=ctx)
    if bounds.get("signed", True):
        return [expression >= lower, expression <= upper]
    return [UGE(expression, BitVecVal(0, bits, ctx=ctx)), ULE(expression, upper)]


def candidate_symbol_names(spec: dict[str, Any]) -> tuple[str, ...]:
    index = int(spec["index"])
    bits = int(spec["bits"])
    name = str(spec["name"])
    return tuple(
        dict.fromkeys(
            [
                name,
                f"arg_{index}",
                f"FP_arg_{index}_{index}_{bits}",
                f"FP_arg_{index}_{bits}",
                f"scanf_{index}",
            ]
        )
    )


def symbol_matches_spec(name: str, spec: dict[str, Any]) -> bool:
    """Match canonical and version-suffixed input symbols by position."""
    if name in candidate_symbol_names(spec):
        return True
    index = int(spec["index"])
    patterns = (
        rf"arg_{index}(?:_\d+)*",
        rf"scanf_{index}(?:_\d+)*",
        rf"FP_arg_{index}(?:_\d+)*",
    )
    return any(re.fullmatch(pattern, name) for pattern in patterns)

