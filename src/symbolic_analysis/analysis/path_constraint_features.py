"""Versioned 11-dimensional path-constraint feature extraction.

Features are extracted from the SMT-LIB assertions only. The parser keeps
source assertions intact, retains free-symbol identity, and expands ``let``
bindings only for occurrence counting.
"""

from __future__ import annotations

import math
import re
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import z3

FEATURE_NAMES = [
    "assert_count",
    "variable_count",
    "main_bv_width",
    "operator_type_count",
    "comparison_ratio",
    "nest_depth",
    "dominant_constant_type",
    "variable_range_span",
    "shift_coefficient",
    "extend_count",
    "extract_count",
]

FEATURE_RANGES: dict[str, tuple[float, float]] = {
    "assert_count": (0, 25),
    "variable_count": (0, 30),
    "main_bv_width": (0, 64),
    "operator_type_count": (0, 20),
    "comparison_ratio": (0, 1),
    "nest_depth": (0, 8),
    "dominant_constant_type": (0, 2),
    "variable_range_span": (0, 2**20),
    "shift_coefficient": (0, 16),
    "extend_count": (0, 15),
    "extract_count": (0, 20),
}

FEATURE_SCHEMA = "symbolicana.pcfv.v2"

_BV_COMPARISONS = {
    "bvult",
    "bvule",
    "bvugt",
    "bvuge",
    "bvslt",
    "bvsle",
    "bvsgt",
    "bvsge",
}
_FP_COMPARISONS = {"fp.eq", "fp.lt", "fp.leq", "fp.gt", "fp.geq"}
_EQUALITY_OPS = {"=", "distinct"}
_COMPARISON_OPS = _BV_COMPARISONS | _FP_COMPARISONS | _EQUALITY_OPS
_SHIFT_OPS = {"bvshl", "bvlshr", "bvashr"}
_EXTEND_OPS = {"zero_extend", "sign_extend"}
_EXTRACT_OP = "extract"
_LOGICAL_OPS = {"and", "or", "not", "xor", "=>", "ite"}
_BV_CORE_OPS = {
    "bvadd",
    "bvsub",
    "bvmul",
    "bvudiv",
    "bvsdiv",
    "bvurem",
    "bvsrem",
    "bvsmod",
    "bvand",
    "bvor",
    "bvxor",
    "bvnot",
    "bvneg",
    "bvnand",
    "bvnor",
    "bvshl",
    "bvlshr",
    "bvashr",
    "bvcomp",
    "bvconcat",
    "zero_extend",
    "sign_extend",
    "extract",
    "rotate_left",
    "rotate_right",
    "repeat",
    "int2bv",
    "bv2int",
    "bvredand",
    "bvredor",
}
_FP_CORE_OPS = {
    "fp.add",
    "fp.sub",
    "fp.mul",
    "fp.div",
    "fp.rem",
    "fp.neg",
    "fp.abs",
    "fp.sqrt",
    "fp.roundToIntegral",
    "fp.fma",
    "fp.min",
    "fp.max",
    "fp.eq",
    "fp.lt",
    "fp.leq",
    "fp.gt",
    "fp.geq",
    "fp.isNaN",
    "fp.isInfinite",
    "fp.isZero",
    "fp.isNormal",
    "fp.isSubnormal",
    "fp.to_ieee_bv",
    "to_fp",
    "to_fp_unsigned",
    "fp.to_sbv",
    "fp.to_ubv",
}
_ARRAY_OPS = {"select", "store"}
_ARITH_OPS = {"+", "-", "*", "/", "div", "mod", "<", "<=", ">", ">="}
_CORE_OPS = (
    _BV_CORE_OPS
    | _FP_CORE_OPS
    | _ARRAY_OPS
    | _ARITH_OPS
    | _COMPARISON_OPS
    | _LOGICAL_OPS
)

_INPUT_SYMBOL_RE = re.compile(
    r"^(?:arg_\d+|FP_arg_\d+|scanf_\d+|count_param|array_b_\d+)"
    r"(?:_\d+)*(?:_\d+)?$"
)


class FeatureExtractionError(ValueError):
    """Raised when a path constraint cannot be parsed as complete SMT-LIB."""


@dataclass
class FeatureRecord:
    raw: list[float]
    values: dict[str, float]
    valid: dict[str, bool]
    missing: dict[str, str]
    details: dict[str, Any] = field(default_factory=dict)
    schema: str = FEATURE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "feature_names": list(FEATURE_NAMES),
            "raw": self.raw,
            "values": self.values,
            "valid": self.valid,
            "missing": self.missing,
            "details": self.details,
        }


@dataclass
class _ExprStats:
    operator_counts: Counter[str] = field(default_factory=Counter)
    total_operators: int = 0
    depth: int = 0
    variables: set[tuple[str, str]] = field(default_factory=set)
    variable_exprs: dict[tuple[str, str], z3.ExprRef] = field(default_factory=dict)
    boundary_constants: list[tuple[str, int]] = field(default_factory=list)
    shift_constants: list[int] = field(default_factory=list)
    symbolic_shifts: int = 0


def _constraint_body(content: str) -> str:
    if "; Path signature:" in content:
        content = content.split("; Path signature:", 1)[0]
    if "(check-sat)" in content:
        content = content.split("(check-sat)", 1)[0]
    lines = [
        line
        for line in content.splitlines()
        if not line.lstrip().startswith("(set-info :status")
    ]
    return "\n".join(lines).strip()


def parse_constraints(path_content: str) -> list[z3.BoolRef]:
    body = _constraint_body(path_content)
    if not body:
        return []
    try:
        formulas = z3.parse_smt2_string(body, ctx=z3.Context())
    except z3.Z3Exception as exc:
        raise FeatureExtractionError(f"invalid SMT-LIB path constraint: {exc}") from exc
    if not all(isinstance(formula, z3.BoolRef) for formula in formulas):
        raise FeatureExtractionError("path constraint contains a non-Boolean assertion")
    return list(formulas)


def _operator_name(expr: z3.ExprRef) -> str:
    if not z3.is_app(expr):
        return ""
    return str(expr.decl().name())


def _is_numeric_constant(expr: z3.ExprRef) -> bool:
    return bool(
        z3.is_int_value(expr)
        or z3.is_rational_value(expr)
        or z3.is_bv_value(expr)
        or z3.is_fp_value(expr)
    )


def _sort_identity(sort: z3.SortRef) -> str:
    return str(sort)


def _collect_stats(
    expr: z3.ExprRef,
    *,
    under_comparison: bool = False,
    _cache: dict[tuple[int, bool], _ExprStats] | None = None,
    _constant_cache: dict[tuple[int, bool], tuple[tuple[str, int], ...]]
    | None = None,
) -> _ExprStats:
    cache = {} if _cache is None else _cache
    constant_cache = {} if _constant_cache is None else _constant_cache
    cache_key = (expr.get_id(), under_comparison)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if z3.is_app(expr) and expr.num_args() == 0 and not _is_numeric_constant(expr):
        key = (str(expr), _sort_identity(expr.sort()))
        stats = _ExprStats(
            variables={key},
            variable_exprs={key: expr},
        )
        cache[cache_key] = stats
        return stats

    if not z3.is_app(expr):
        stats = _ExprStats()
        cache[cache_key] = stats
        return stats

    name = _operator_name(expr)
    stats = _ExprStats()
    child_stats = [
        _collect_stats(
            expr.arg(index),
            under_comparison=under_comparison or name in _COMPARISON_OPS,
            _cache=cache,
            _constant_cache=constant_cache,
        )
        for index in range(expr.num_args())
    ]
    for child in child_stats:
        stats.operator_counts.update(child.operator_counts)
        stats.total_operators += child.total_operators
        stats.variables.update(child.variables)
        stats.variable_exprs.update(child.variable_exprs)
        stats.boundary_constants.extend(child.boundary_constants)
        stats.shift_constants.extend(child.shift_constants)
        stats.symbolic_shifts += child.symbolic_shifts

    if name in _CORE_OPS:
        stats.operator_counts[name] += 1
        stats.total_operators += 1
        stats.depth = 1 + max((child.depth for child in child_stats), default=0)
    else:
        stats.depth = max((child.depth for child in child_stats), default=0)

    if name in _SHIFT_OPS and expr.num_args() >= 2:
        amount = expr.arg(1)
        folded = z3.simplify(amount)
        if z3.is_bv_value(folded):
            stats.shift_constants.append(int(folded.as_long()))
        else:
            stats.symbolic_shifts += 1

    if name in _COMPARISON_OPS and bool(stats.variables):
        for index in range(expr.num_args()):
            operand = expr.arg(index)
            stats.boundary_constants.extend(
                _bitvector_constants(
                    operand,
                    skip_shift_amounts=True,
                    _cache=constant_cache,
                )
            )

    cache[cache_key] = stats
    return stats


def _bitvector_constants(
    expr: z3.ExprRef,
    *,
    skip_shift_amounts: bool = False,
    _cache: dict[tuple[int, bool], tuple[tuple[str, int], ...]] | None = None,
) -> list[tuple[str, int]]:
    cache = {} if _cache is None else _cache
    cache_key = (expr.get_id(), skip_shift_amounts)
    cached = cache.get(cache_key)
    if cached is not None:
        return list(cached)

    out: list[tuple[str, int]] = []
    if z3.is_bv_value(expr):
        out.append((_sort_identity(expr.sort()), int(expr.as_long())))
    elif z3.is_app(expr):
        if skip_shift_amounts and _operator_name(expr) in _SHIFT_OPS:
            if expr.num_args():
                out.extend(
                    _bitvector_constants(
                        expr.arg(0),
                        skip_shift_amounts=True,
                        _cache=cache,
                    )
                )
        else:
            for index in range(expr.num_args()):
                out.extend(
                    _bitvector_constants(
                        expr.arg(index),
                        skip_shift_amounts=skip_shift_amounts,
                        _cache=cache,
                    )
                )
    cache[cache_key] = tuple(out)
    return out


def _variable_widths(variables: set[tuple[str, str]]) -> list[int]:
    widths = []
    for _name, sort_text in variables:
        match = re.fullmatch(r"BitVec\((\d+)\)", sort_text)
        if match:
            widths.append(int(match.group(1)))
    return widths


def _signed_value(value: int, bits: int) -> int:
    return value - (1 << bits) if value >= (1 << (bits - 1)) else value


def _fp_value_to_float(value: z3.ExprRef) -> float:
    if not z3.is_fp_value(value):
        raise FeatureExtractionError(f"not a floating-point value: {value}")
    exponent_bits = int(value.ebits())
    significand_bits = int(value.sbits())
    bits = exponent_bits + significand_bits
    if bits not in {32, 64}:
        raise FeatureExtractionError(f"unsupported FP width: {bits}")
    raw = (
        (int(bool(value.sign())) << (bits - 1))
        | (int(value.exponent_as_long()) << (bits - exponent_bits - 1))
        | int(value.significand_as_long())
    )
    return struct.unpack(
        ">f" if bits == 32 else ">d",
        raw.to_bytes(bits // 8, "big"),
    )[0]


def _is_same_expr(left: z3.ExprRef, right: z3.ExprRef) -> bool:
    return bool(left.eq(right))


def _input_bounds(
    variables: list[z3.ExprRef],
    formulas: list[z3.BoolRef],
) -> tuple[float | None, dict[str, Any]]:
    inputs = [
        variable
        for variable in variables
        if _INPUT_SYMBOL_RE.match(str(variable))
    ]
    if not inputs:
        return None, {"inputs": [], "reason": "no input symbols"}

    bounds: dict[tuple[str, str], dict[str, list[tuple[Any, str, bool]]]] = {}
    comparisons: list[z3.ExprRef] = []
    seen_nodes: set[int] = set()
    for formula in formulas:
        stack = [formula]
        while stack:
            current = stack.pop()
            if not z3.is_app(current):
                continue
            node_id = current.get_id()
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            if _operator_name(current) in _COMPARISON_OPS:
                comparisons.append(current)
            stack.extend(current.arg(i) for i in range(current.num_args()))

    for variable in inputs:
        key = (str(variable), _sort_identity(variable.sort()))
        if z3.is_bv(variable):
            bounds[key] = {"signed": [], "unsigned": []}
            bits = variable.size()
            for comparison in comparisons:
                if comparison.num_args() != 2:
                    continue
                left, right = comparison.arg(0), comparison.arg(1)
                if _is_same_expr(left, variable) and z3.is_bv_value(z3.simplify(right)):
                    op = _operator_name(comparison)
                    raw = int(z3.simplify(right).as_long())
                    signed = _signed_value(raw, bits)
                    if op in {"bvsge", "bvsgt"}:
                        bounds[key]["signed"].append((signed, "lower", op.endswith("gt")))
                    elif op in {"bvsle", "bvslt"}:
                        bounds[key]["signed"].append((signed, "upper", op.endswith("lt")))
                    elif op in {"bvuge", "bvugt"}:
                        bounds[key]["unsigned"].append((raw, "lower", op.endswith("gt")))
                    elif op in {"bvule", "bvult"}:
                        bounds[key]["unsigned"].append((raw, "upper", op.endswith("lt")))
                    elif op == "=":
                        bounds[key]["signed"].extend(
                            [(signed, "lower", False), (signed, "upper", False)]
                        )
                elif _is_same_expr(right, variable) and z3.is_bv_value(z3.simplify(left)):
                    op = _operator_name(comparison)
                    raw = int(z3.simplify(left).as_long())
                    signed = _signed_value(raw, bits)
                    if op in {"bvsle", "bvslt"}:
                        bounds[key]["signed"].append((signed, "lower", op.endswith("lt")))
                    elif op in {"bvsge", "bvsgt"}:
                        bounds[key]["signed"].append((signed, "upper", op.endswith("gt")))
                    elif op in {"bvule", "bvult"}:
                        bounds[key]["unsigned"].append((raw, "lower", op.endswith("lt")))
                    elif op in {"bvuge", "bvugt"}:
                        bounds[key]["unsigned"].append((raw, "upper", op.endswith("gt")))
        elif z3.is_fp(variable):
            bounds[key] = {"fp": []}
            for comparison in comparisons:
                if comparison.num_args() != 2:
                    continue
                left, right = comparison.arg(0), comparison.arg(1)
                if _is_same_expr(left, variable) and z3.is_fp_value(z3.simplify(right)):
                    op = _operator_name(comparison)
                    value = _fp_value_to_float(z3.simplify(right))
                    if op in {"fp.geq", "fp.gt"}:
                        bounds[key]["fp"].append((value, "lower", op.endswith("gt")))
                    elif op in {"fp.leq", "fp.lt"}:
                        bounds[key]["fp"].append((value, "upper", op.endswith("lt")))
        else:
            bounds[key] = {}

    spans = []
    evidence = {"inputs": []}
    for variable in inputs:
        key = (str(variable), _sort_identity(variable.sort()))
        if z3.is_bv(variable):
            candidates = []
            for signedness in ("signed", "unsigned"):
                items = bounds[key][signedness]
                lowers = [value + (1 if strict else 0) for value, side, strict in items if side == "lower"]
                uppers = [value - (1 if strict else 0) for value, side, strict in items if side == "upper"]
                if lowers and uppers:
                    lo = max(lowers)
                    hi = min(uppers)
                    if hi >= lo:
                        candidates.append(
                            {
                                "signedness": signedness,
                                "lower": lo,
                                "upper": hi,
                                "span": hi - lo,
                            }
                        )
            if not candidates:
                return None, {
                    "inputs": evidence["inputs"],
                    "reason": f"incomplete bounds for {key[0]}",
                }
            selected = max(candidates, key=lambda item: item["span"])
            spans.append(selected["span"])
            evidence["inputs"].append({**selected, "name": key[0], "kind": "bitvec"})
        elif z3.is_fp(variable):
            items = bounds[key]["fp"]
            lowers = [value for value, side, _strict in items if side == "lower"]
            uppers = [value for value, side, _strict in items if side == "upper"]
            if not lowers or not uppers:
                return None, {
                    "inputs": evidence["inputs"],
                    "reason": f"incomplete bounds for {key[0]}",
                }
            lo, hi = max(lowers), min(uppers)
            if hi < lo:
                return None, {
                    "inputs": evidence["inputs"],
                    "reason": f"empty bounds for {key[0]}",
                }
            span = hi - lo
            spans.append(span)
            evidence["inputs"].append(
                {"name": key[0], "kind": "float", "lower": lo, "upper": hi, "span": span}
            )
        else:
            return None, {
                "inputs": evidence["inputs"],
                "reason": f"unsupported input sort for {key[0]}: {key[1]}",
            }
    if not spans:
        return None, {"inputs": evidence["inputs"], "reason": "no span evidence"}
    evidence["maximum"] = max(spans)
    return float(max(spans)), evidence


def extract_feature_record(path_content: str) -> FeatureRecord:
    formulas = parse_constraints(path_content)
    stats = _ExprStats()
    for formula in formulas:
        item = _collect_stats(formula)
        stats.operator_counts.update(item.operator_counts)
        stats.total_operators += item.total_operators
        stats.depth = max(stats.depth, item.depth)
        stats.variables.update(item.variables)
        stats.variable_exprs.update(item.variable_exprs)
        stats.boundary_constants.extend(item.boundary_constants)
        stats.shift_constants.extend(item.shift_constants)
        stats.symbolic_shifts += item.symbolic_shifts

    variables = list(stats.variable_exprs.values())
    widths = _variable_widths(stats.variables)
    if widths:
        counts = Counter(widths)
        top = max(counts.values())
        main_bv_width = max(width for width, count in counts.items() if count == top)
    else:
        main_bv_width = 0

    comparison_count = sum(
        count for op, count in stats.operator_counts.items() if op in _COMPARISON_OPS
    )
    comparison_ratio = (
        comparison_count / stats.total_operators if stats.total_operators else 0.0
    )
    has_range = bool(stats.boundary_constants)
    has_shift = bool(stats.shift_constants)
    dominant_constant_type = (
        0 if has_range and not has_shift
        else 1 if has_shift and not has_range
        else 2
    )

    span, span_evidence = _input_bounds(variables, formulas)
    valid = {name: True for name in FEATURE_NAMES}
    missing: dict[str, str] = {}
    if span is None:
        valid["variable_range_span"] = False
        missing["variable_range_span"] = span_evidence.get("reason", "missing")

    raw = [
        float(len(formulas)),
        float(len(stats.variables)),
        float(main_bv_width),
        float(len(stats.operator_counts)),
        float(comparison_ratio),
        float(stats.depth),
        float(dominant_constant_type),
        float(span or 0.0),
        float(max(stats.shift_constants) if stats.shift_constants else 0),
        float(sum(stats.operator_counts.get(op, 0) for op in _EXTEND_OPS)),
        float(stats.operator_counts.get(_EXTRACT_OP, 0)),
    ]
    values = dict(zip(FEATURE_NAMES, raw))
    details = {
        "assertions": len(formulas),
        "variables": [
            {"name": name, "sort": sort_text}
            for name, sort_text in sorted(stats.variables)
        ],
        "operator_counts": dict(sorted(stats.operator_counts.items())),
        "comparison_count": comparison_count,
        "total_operator_occurrences": stats.total_operators,
        "constant_evidence": {
            "range": len(stats.boundary_constants),
            "shift": len(stats.shift_constants),
            "symbolic_shift": stats.symbolic_shifts,
        },
        "input_span_evidence": span_evidence,
    }
    return FeatureRecord(raw, values, valid, missing, details)


def extract_features(path_content: str) -> tuple[list[float], dict[str, float]]:
    """Return the backward-compatible raw vector and named values.

    Missing optional dimensions keep slot 8 at zero, but callers that need
    ranking validity must use :func:`extract_feature_record`.
    """
    record = extract_feature_record(path_content)
    return record.raw, record.values


def normalize_features(
    raw: list[float],
    min_max: dict[str, tuple[float, float]] | None = None,
) -> list[float]:
    names = list(FEATURE_NAMES)
    ranges = min_max or {name: FEATURE_RANGES[name] for name in names}
    out = []
    for index, name in enumerate(names):
        lo, hi = ranges.get(name, (0.0, 1.0))
        value = raw[index]
        if hi <= lo:
            out.append(0.0)
        else:
            out.append(max(0.0, min(1.0, (value - lo) / (hi - lo))))
    return out


def cosine_with_validity(
    left: list[float],
    right: list[float],
    left_valid: list[bool] | None = None,
    right_valid: list[bool] | None = None,
) -> float:
    if len(left) != len(right):
        return 0.0
    mask = [
        (left_valid is None or left_valid[index])
        and (right_valid is None or right_valid[index])
        for index in range(len(left))
    ]
    if not any(mask):
        return 0.0
    dot = sum(left[index] * right[index] for index in range(len(left)) if mask[index])
    left_norm = math.sqrt(sum(left[index] ** 2 for index in range(len(left)) if mask[index]))
    right_norm = math.sqrt(sum(right[index] ** 2 for index in range(len(right)) if mask[index]))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))
