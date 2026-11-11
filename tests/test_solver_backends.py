from __future__ import annotations

import importlib.util
import gc
import json
import sys
import tempfile
import unittest
from pathlib import Path

from z3 import (
    BitVec,
    BitVecVal,
    Context,
    FP,
    FPSort,
    If,
    Not,
    Solver as Z3Solver,
    fpToIEEEBV,
    fpIsNaN,
    parse_smt2_string,
    sat,
    unsat,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import solver_backends  # noqa: E402
import verify_ranked_path_equivalence as verifier  # noqa: E402
import verify_ranked_path_equivalence as verifier  # noqa: E402
import backend_preflight  # noqa: E402


HAS_BITWUZLA = importlib.util.find_spec("bitwuzla") is not None


class SolverBackendTests(unittest.TestCase):
    def tearDown(self) -> None:
        solver_backends.configure_solver_strategy("Z60")
        verifier.configure_smt_audit(None)

    def test_all_z3_division_aliases_translate_to_standard_operators(self) -> None:
        text = """
(set-logic QF_BV)
(declare-const x (_ BitVec 8))
(declare-const y (_ BitVec 8))
(assert (= (bvudiv_i x y) (bvudiv x y)))
(assert (= (bvsdiv_i x y) (bvsdiv x y)))
(assert (= (bvurem_i x y) (bvurem x y)))
(assert (= (bvsrem_i x y) (bvsrem x y)))
(assert (= (bvsmod_i x y) (bvsmod x y)))
(check-sat)
"""
        translated, info = solver_backends.translate_z3_division_aliases(text)
        self.assertEqual(
            info["aliases"],
            {
                "bvsdiv_i": 1,
                "bvudiv_i": 1,
                "bvsrem_i": 1,
                "bvurem_i": 1,
                "bvsmod_i": 1,
            },
        )
        for alias in solver_backends.DIVISION_ALIASES:
            self.assertNotIn(alias, translated)

    def test_division_alias_pairs_are_semantically_equivalent(self) -> None:
        for alias, standard in solver_backends.DIVISION_ALIASES.items():
            equalities = parse_smt2_string(
                "(set-logic QF_BV)\n"
                "(declare-const x (_ BitVec 8))\n"
                "(declare-const y (_ BitVec 8))\n"
                f"(assert (= ({alias} x y) ({standard} x y)))\n"
            )
            solver = Z3Solver()
            solver.add(Not(equalities[0]))
            self.assertEqual(solver.check(), unsat)

    def test_backend_solver_keeps_explicit_context_alive(self) -> None:
        context = Context()
        solver_backends.configure_solver_strategy("Z60")
        solver = solver_backends.BackendSolver(ctx=context)
        value = BitVec("arg_0", 8, ctx=context)
        solver.add(value == BitVecVal(7, 8, ctx=context))
        solver.set("timeout", 5_000)
        del context
        gc.collect()
        self.assertEqual(solver.check(), sat)
        self.assertIsNotNone(solver.model())

    def test_fp_bridge_uses_the_expression_context(self) -> None:
        context = Context()
        value = FP("arg_0", FPSort(11, 53, ctx=context), ctx=context)
        encoded = BitVec(
            "__test_fp_ieee_bits",
            64,
            ctx=context,
        )
        assertions = [
            Not(fpIsNaN(value, ctx=context)),
            fpToIEEEBV(value, ctx=context) == encoded,
        ]
        translation = backend_preflight.translate_fp_to_ieee_bv(
            assertions,
            proof_timeout_ms=1_000,
        )
        self.assertEqual(translation.status, "translated")
        self.assertEqual(translation.conversion_count, 1)
        self.assertFalse(
            backend_preflight._collect_fp_to_ieee_bv(
                translation.assertions
            )
        )

    @unittest.skipUnless(HAS_BITWUZLA, "Bitwuzla is not installed")
    def test_bitwuzla_solves_dynamic_division_after_alias_translation(self) -> None:
        query = """
(set-logic QF_BV)
(declare-const x (_ BitVec 8))
(declare-const y (_ BitVec 8))
(assert (= (bvudiv_i x y) #x02))
(check-sat)
"""
        result = solver_backends.run_bitwuzla(query, 5_000)
        self.assertEqual(result.status, "sat")
        self.assertTrue(result.model_available)
        self.assertGreaterEqual(
            result.translation["aliases"].get("bvudiv_i", 0),
            1,
        )

    @unittest.skipUnless(HAS_BITWUZLA, "Bitwuzla is not installed")
    def test_b60_extracts_bitvector_model(self) -> None:
        solver_backends.configure_solver_strategy("B60")
        solver = solver_backends.BackendSolver()
        x = BitVec("arg_0", 8)
        solver.add(x == BitVecVal(7, 8))
        solver.set("timeout", 5_000)
        self.assertEqual(solver.check(), sat)
        concrete = solver.model().concrete_value(x)
        self.assertEqual(concrete["unsigned"], 7)
        backend_inputs = solver.last_backend_inputs()
        self.assertEqual(len(backend_inputs), 1)
        self.assertEqual(backend_inputs[0]["backend"], "bitwuzla")
        self.assertIn(
            "(check-sat)",
            backend_inputs[0]["backend_query"],
        )

    @unittest.skipUnless(HAS_BITWUZLA, "Bitwuzla is not installed")
    def test_b10z50_exactly_bridges_provably_non_nan_extension(self) -> None:
        x = BitVec("arg_0", 8)
        base = Z3Solver()
        base.add(x == BitVecVal(3, 8))
        query = base.to_smt2().replace(
            "(check-sat)",
            "(assert (= (fp.to_ieee_bv ((_ to_fp 8 24) #x00000000)) #x00000000))\n(check-sat)",
        )
        parsed = Z3Solver()
        parsed.from_string(query)
        solver_backends.configure_solver_strategy("B10Z50")
        solver = solver_backends.BackendSolver()
        solver.add(*parsed.assertions())
        self.assertEqual(solver.check(), sat)
        attempts = solver.last_attempts()
        self.assertEqual([item["backend"] for item in attempts], ["bitwuzla"])
        self.assertEqual(attempts[0]["status"], "sat")
        backend_input = solver.last_backend_inputs()[0]
        translation = backend_input["translation"]["fp_to_ieee_bv"]
        self.assertEqual(translation["status"], "translated")
        self.assertTrue(translation["exact_non_nan_inverse"])
        self.assertNotIn("fp.to_ieee_bv", backend_input["backend_query"])
        self.assertEqual(
            solver_backends.solver_audit_summary()["counts"][
                "fp_bridge.translated"
            ],
            1,
        )

    @unittest.skipUnless(HAS_BITWUZLA, "Bitwuzla is not installed")
    def test_b10z50_falls_back_when_conversion_may_be_nan(self) -> None:
        context = Context()
        value = FP("arg_0", FPSort(11, 53, ctx=context), ctx=context)
        solver_backends.configure_solver_strategy("B10Z50")
        solver = solver_backends.BackendSolver(ctx=context)
        solver.add(fpIsNaN(value, ctx=context))
        solver.add(
            fpToIEEEBV(value, ctx=context)
            == fpToIEEEBV(value, ctx=context)
        )
        solver.set("timeout", 5_000)
        self.assertEqual(solver.check(), sat)
        attempts = solver.last_attempts()
        self.assertEqual(
            [item["backend"] for item in attempts],
            ["bitwuzla", "z3"],
        )
        self.assertEqual(attempts[0]["status"], "unsupported")
        self.assertEqual(
            attempts[0]["fp_translation"]["status"],
            "possible_nan",
        )
        with tempfile.TemporaryDirectory() as raw:
            verifier.configure_smt_audit(Path(raw))
            event = verifier.persist_smt_query(
                solver,
                stage="backend_row_smoke",
                timeout_ms=5_000,
                elapsed=0.1,
                status=sat,
                force=True,
            )
            verifier.configure_smt_audit(None)
        self.assertIsNotNone(event)
        rows = event["backend_rows"]
        self.assertEqual([row["backend"] for row in rows], ["bitwuzla", "z3"])
        self.assertEqual([row["status"] for row in rows], ["unsupported", "sat"])
        self.assertEqual(
            rows[1]["fp_translation_status"],
            "not_applicable",
        )

    @unittest.skipUnless(HAS_BITWUZLA, "Bitwuzla is not installed")
    def test_translated_backend_query_is_persisted_separately(self) -> None:
        query = (
            "(set-logic QF_BV)\n"
            "(declare-const x (_ BitVec 8))\n"
            "(declare-const y (_ BitVec 8))\n"
            "(assert (= (bvudiv_i x y) #x02))\n"
            "(check-sat)\n"
        )
        solver_backends.configure_solver_strategy("B60")
        solver = solver_backends.BackendSolver()
        solver.from_string(query)
        solver.set("timeout", 5_000)
        self.assertEqual(solver.check(), sat)
        inputs = solver.last_backend_inputs()
        self.assertIn("bvudiv_i", inputs[0]["logical_query"])
        self.assertIn("bvudiv ", inputs[0]["backend_query"])
        self.assertNotIn("bvudiv_i", inputs[0]["backend_query"])
        with tempfile.TemporaryDirectory() as temporary:
            audit_dir = Path(temporary) / "audit"
            verifier.configure_smt_audit(audit_dir)
            event = verifier.persist_smt_query(
                solver,
                stage="translated_backend",
                timeout_ms=5_000,
                elapsed=0.01,
                status=sat,
                force=True,
            )
            backend_path = Path(event["backend_query_path"])
            self.assertTrue(backend_path.is_file())
            self.assertIn(
                "bvudiv ",
                backend_path.read_text(encoding="utf-8"),
            )

    @unittest.skipUnless(HAS_BITWUZLA, "Bitwuzla is not installed")
    def test_audit_all_persists_sat_queries_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            audit_dir = Path(temporary) / "audit"
            verifier.configure_smt_audit(audit_dir, persist_all_queries=True)
            solver_backends.configure_solver_strategy(
                "Z60",
                audit_callback=verifier.persist_backend_check,
                audit_all_queries=True,
            )
            solver = solver_backends.BackendSolver()
            x = BitVec("arg_0", 8)
            solver.add(x == BitVecVal(4, 8))
            solver.set("timeout", 5_000)
            self.assertEqual(solver.check(), sat)
            verifier.persist_smt_query(
                solver,
                stage="test_stage",
                timeout_ms=5_000,
                elapsed=0.01,
                status=sat,
            )
            self.assertEqual(verifier.smt_audit_summary()["query_count"], 1)
            self.assertEqual(len(list(audit_dir.glob("*.smt2"))), 1)
            metadata_path = next(audit_dir.glob("*.json"))
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["backend"], "z3")
            self.assertEqual(
                len(metadata["pre_invocation_backend_inputs"]),
                1,
            )
            self.assertEqual(
                metadata["pre_invocation_backend_inputs"][0][
                    "transport"
                ],
                "python_api_assertions",
            )

if __name__ == "__main__":
    unittest.main()
