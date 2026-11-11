from __future__ import annotations

import sys
import unittest
from pathlib import Path

from z3 import (
    BitVec,
    BitVecVal,
    FP,
    FPVal,
    FPSort,
    Solver,
    fpToIEEEBV,
    fpIsNaN,
    sat,
    unsat,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_preflight import (  # noqa: E402
    preflight_bitwuzla,
    translate_fp_to_ieee_bv,
)


class BackendPreflightTests(unittest.TestCase):
    def test_plain_bitvector_formula_is_not_rejected(self) -> None:
        value = BitVec("value", 8)
        result = preflight_bitwuzla((value == BitVecVal(1, 8),))
        self.assertTrue(result.supported)
        self.assertEqual(result.unsupported_operators, ())

    def test_z3_ieee_bit_conversion_is_rejected_exactly(self) -> None:
        value = FP("value", FPSort(11, 53))
        converted = fpToIEEEBV(value)
        result = preflight_bitwuzla((converted == BitVecVal(0, 64),))
        self.assertFalse(result.supported)
        self.assertEqual(
            result.unsupported_operators,
            ("fp.to_ieee_bv",),
        )
        self.assertEqual(
            result.reason,
            "z3_specific_floating_point_to_ieee_bits",
        )

    def test_provably_non_nan_conversion_has_exact_bitvector_bridge(self) -> None:
        value = FPVal(0.0, FPSort(11, 53))
        converted = fpToIEEEBV(value)
        translation = translate_fp_to_ieee_bv(
            (converted == BitVecVal(0, 64),)
        )
        self.assertEqual(translation.status, "translated")
        self.assertTrue(translation.exact_non_nan_inverse)
        self.assertEqual(translation.conversion_count, 1)
        self.assertTrue(
            all(
                query["status"] == "unsat"
                for query in translation.proof_queries
            )
        )
        self.assertTrue(
            all(
                "fp.to_ieee_bv" not in assertion.sexpr()
                for assertion in translation.assertions
            )
        )

    def test_possible_nan_keeps_z3_extension_and_falls_back(self) -> None:
        value = FP("value", FPSort(11, 53))
        converted = fpToIEEEBV(value)
        translation = translate_fp_to_ieee_bv(
            (
                converted == BitVecVal(0x7FF8000000000000, 64),
                fpIsNaN(value),
            )
        )
        self.assertEqual(translation.status, "possible_nan")
        self.assertFalse(translation.exact_non_nan_inverse)
        self.assertIn(
            "fp.to_ieee_bv",
            translation.assertions[0].sexpr(),
        )

    def test_exact_bridge_preserves_signed_zero_and_float_width(self) -> None:
        for sort, expected in (
            (FPSort(8, 24), 0x80000000),
            (FPSort(11, 53), 0x8000000000000000),
        ):
            with self.subTest(sort=sort):
                bits = sort.ebits() + sort.sbits()
                converted = fpToIEEEBV(FPVal(-0.0, sort))
                translation = translate_fp_to_ieee_bv(
                    (converted == BitVecVal(expected, bits),)
                )
                self.assertEqual(translation.status, "translated")
                solver = Solver()
                solver.add(*translation.assertions)
                self.assertEqual(solver.check(), sat)
                solver.add(converted == BitVecVal(0, bits))
                self.assertEqual(solver.check(), unsat)


if __name__ == "__main__":
    unittest.main()
