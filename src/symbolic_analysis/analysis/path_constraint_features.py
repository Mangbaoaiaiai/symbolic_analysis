"""
Path constraint feature extraction for similarity ranking (BinDiffNN-style).

Extracts 11 structural/semantic features from SMT-LIB path constraint text
for use in cosine-similarity-based ordering (no match/unmatch threshold).
"""

import re
from typing import Dict, List, Optional, Tuple

# SMT-LIB operators we count
COMPARISON_OPS = {"bvuge", "bvule", "bvslt", "bvsge", "bvsgt", "bvsle", "bvult", "bvugt"}
SHIFT_OPS = {"bvshl", "bvlshr", "bvashr"}
EXTEND_OPS = {"zero_extend", "sign_extend"}
EXTRACT_OP = "extract"
OTHER_OPS = {
    "bvand", "bvor", "bvxor", "bvnot", "bvadd", "bvsub", "bvmul", "bvconcat",
    "bvnand", "bvnor", "bvneg",
}
ALL_OPS = COMPARISON_OPS | SHIFT_OPS | EXTEND_OPS | OTHER_OPS
ALL_OPS.add(EXTRACT_OP)


def _constraint_body(content: str) -> str:
    """Return SMT constraint part only (before ; Path signature or check-sat)."""
    if "; Path signature:" in content:
        content = content.split("; Path signature:")[0]
    if "(check-sat)" in content:
        content = content.split("(check-sat)")[0]
    return content.strip()


def _count_asserts(body: str) -> int:
    return len(re.findall(r"\(\s*assert\s+", body))


def _variable_names(body: str) -> set:
    # Declared: (declare-fun name () (_ BitVec N))
    declared = set(re.findall(r"\(\s*declare-fun\s+(\S+)\s+\(\)", body))
    # Temp vars in let: ?x38, ?x44, etc.
    temps = set(re.findall(r"\?x\d+", body))
    return declared | temps


def _bitvec_widths(body: str) -> List[int]:
    return [int(m) for m in re.findall(r"\(\s*_\s+BitVec\s+(\d+)\s*\)", body)]


def _operator_counts(body: str) -> Dict[str, int]:
    counts = {}
    for op in ALL_OPS:
        if op == EXTRACT_OP:
            # (_ extract 31 0) style
            n = len(re.findall(r"\(\s*_\s+extract\s+", body))
        elif op in EXTEND_OPS:
            # (_ zero_extend 32) or (_ sign_extend 32)
            n = len(re.findall(r"\(\s*_\s+" + re.escape(op) + r"\s+", body))
        else:
            n = len(re.findall(r"\(\s*" + re.escape(op) + r"\s+", body))
        if n > 0:
            counts[op] = n
    return counts


def _max_nesting_depth(body: str) -> int:
    depth = 0
    max_d = 0
    # Skip comments
    without_comments = re.sub(r";[^\n]*", "", body)
    for c in without_comments:
        if c == "(":
            depth += 1
            max_d = max(max_d, depth)
        elif c == ")":
            depth -= 1
    return max_d


def _constraint_bounds(body: str) -> List[int]:
    """Extract numeric constants from bvuge/bvule/bvsge/bvsle (variable bounds)."""
    # e.g. (bvuge x (_ bv0 32)) or (bvule x (_ bv15 32))
    constants = []
    for m in re.findall(r"\(\s*(?:bvuge|bvule|bvsge|bvsle|bvslt|bvsgt)\s+[^)]+\(\s*_\s+bv(\d+)\s+\d+\s*\)", body):
        constants.append(int(m))
    # Also (_ bvN M) as second arg in comparison
    for m in re.findall(r"\(\s*_\s+bv(\d+)\s+\d+\s*\)", body):
        constants.append(int(m))
    return constants


def _shift_constants(body: str) -> List[int]:
    """Constants used in bvshl/bvlshr/bvashr (e.g. (_ bv3 64))."""
    # Match shift op followed eventually by (_ bvN M)
    constants = []
    for m in re.findall(r"\(\s*(?:bvshl|bvlshr|bvashr)\s+[^)]*\(\s*_\s+bv(\d+)\s+\d+\s*\)", body):
        constants.append(int(m))
    return constants


def _dominant_constant_type(body: str) -> int:
    """
    0 = range-dominated (bounds), 1 = shift-dominated, 2 = other/mixed.
    """
    bounds = _constraint_bounds(body)
    shifts = _shift_constants(body)
    if bounds and not shifts:
        return 0
    if shifts and not bounds:
        return 1
    if bounds and shifts:
        return 2
    return 2


def extract_features(path_content: str) -> Tuple[List[float], Dict[str, float]]:
    """
    Extract 11-dimensional raw feature vector from path constraint file content.

    Returns:
        (raw_features, feature_dict): raw_features is list of 11 numbers,
        feature_dict maps feature names to values for inspection.
    """
    body = _constraint_body(path_content)

    # 1. Assert count
    n_asserts = _count_asserts(body)

    # 2. Variable count
    n_vars = len(_variable_names(body))

    # 3. Main bit-vector width (most frequent, or max if tie)
    widths = _bitvec_widths(body)
    main_bv_width = max(widths) if widths else 0

    # 4. Core operator type count (unique operator kinds)
    op_counts = _operator_counts(body)
    n_op_types = len(op_counts)

    # 5. Comparison op ratio
    total_ops = sum(op_counts.values())
    comp_ops = sum(op_counts.get(op, 0) for op in COMPARISON_OPS)
    comparison_ratio = (comp_ops / total_ops) if total_ops else 0.0

    # 6. Nested expression depth
    nest_depth = _max_nesting_depth(body)

    # 7. Dominant constant type (0/1/2)
    dom_const = _dominant_constant_type(body)

    # 8. Variable constraint range span (max - min of bound constants)
    bounds = _constraint_bounds(body)
    range_span = (max(bounds) - min(bounds)) if len(bounds) >= 2 else 0

    # 9. Shift coefficient (max shift constant, or 0)
    shift_consts = _shift_constants(body)
    shift_coef = max(shift_consts) if shift_consts else 0

    # 10. Zero-extend + sign-extend count
    ext_count = sum(op_counts.get(op, 0) for op in EXTEND_OPS)

    # 11. Extract count
    extract_count = op_counts.get(EXTRACT_OP, 0)

    raw = [
        float(n_asserts),
        float(n_vars),
        float(main_bv_width),
        float(n_op_types),
        comparison_ratio,
        float(nest_depth),
        float(dom_const),
        float(range_span),
        float(shift_coef),
        float(ext_count),
        float(extract_count),
    ]
    names = [
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
    return raw, dict(zip(names, raw))


# Default min/max for normalization (empirical for typical path constraints)
FEATURE_RANGES: Dict[str, Tuple[float, float]] = {
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


def normalize_features(
    raw: List[float],
    min_max: Optional[Dict[str, Tuple[float, float]]] = None,
) -> List[float]:
    """
    Normalize raw 11-dim vector to [0, 1] per feature.
    If min_max is None, use FEATURE_RANGES.
    """
    names = list(FEATURE_RANGES.keys())
    min_max = min_max or {n: FEATURE_RANGES[n] for n in names}
    out = []
    for i, name in enumerate(names):
        lo, hi = min_max.get(name, (0, 1))
        v = raw[i]
        if hi <= lo:
            out.append(0.0)
        else:
            out.append(max(0.0, min(1.0, (v - lo) / (hi - lo))))
    return out
