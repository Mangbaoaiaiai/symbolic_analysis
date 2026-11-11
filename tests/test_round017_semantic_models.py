from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import round017_semantic_models as models  # noqa: E402
import se_script_improved as symbolic_execution  # noqa: E402
import verify_ranked_path_equivalence as verifier  # noqa: E402


class Round017SemanticModelTests(unittest.TestCase):
    def test_sqrt_rules_use_distinct_float_and_double_abis(self) -> None:
        sqrt_rule = models.model_rule("sqrt@GLIBC_2.2.5")
        sqrtf_rule = models.model_rule("sqrtf@GLIBC_2.2.5")
        self.assertEqual(sqrt_rule["abi_prototype"], "double sqrt(double)")
        self.assertEqual(sqrtf_rule["abi_prototype"], "float sqrtf(float)")
        self.assertEqual(sqrt_rule["model_status"], "modeled_ieee754")
        self.assertEqual(sqrtf_rule["model_status"], "modeled_ieee754")

    def test_sqrt_formula_preserves_binary32_and_binary64_sorts(self) -> None:
        fp32 = symbolic_execution.claripy.FPS(
            "fp32",
            symbolic_execution.claripy.FSORT_FLOAT,
        )
        fp64 = symbolic_execution.claripy.FPS(
            "fp64",
            symbolic_execution.claripy.FSORT_DOUBLE,
        )
        bv32 = symbolic_execution.claripy.BVS("bv32", 32)
        bv64 = symbolic_execution.claripy.BVS("bv64", 64)
        self.assertEqual(
            symbolic_execution.ieee754_sqrt_formula(fp32, 32).sort,
            symbolic_execution.claripy.FSORT_FLOAT,
        )
        self.assertEqual(
            symbolic_execution.ieee754_sqrt_formula(bv32, 32).sort,
            symbolic_execution.claripy.FSORT_FLOAT,
        )
        self.assertEqual(
            symbolic_execution.ieee754_sqrt_formula(fp64, 64).sort,
            symbolic_execution.claripy.FSORT_DOUBLE,
        )
        self.assertEqual(
            symbolic_execution.ieee754_sqrt_formula(bv64, 64).sort,
            symbolic_execution.claripy.FSORT_DOUBLE,
        )
        with self.assertRaises(ValueError):
            symbolic_execution.ieee754_sqrt_formula(bv32, 64)
        with self.assertRaises(ValueError):
            symbolic_execution.ieee754_sqrt_formula(bv64, 16)

    def test_runtime_nonnegative_sqrt_can_support_eq(self) -> None:
        audit = models.audit_binary_imports(
            ["printf", "sqrt", "sqrtf"]
        )
        self.assertFalse(audit["eq_eligible"])
        finalized = models.finalize_runtime_audit(
            audit,
            [
                {
                    "function": "sqrt",
                    "precision": 64,
                    "argument_nonnegative": True,
                    "argument_expr_sha256": "a" * 64,
                },
                {
                    "function": "sqrtf",
                    "precision": 32,
                    "argument_nonnegative": True,
                    "argument_expr_sha256": "b" * 64,
                },
            ],
        )
        self.assertTrue(finalized["eq_eligible"])
        self.assertEqual(
            models.validate_binary_model_audit(finalized),
            [],
        )

    def test_negative_sqrt_argument_blocks_eq(self) -> None:
        audit = models.audit_binary_imports(["sqrt"])
        finalized = models.finalize_runtime_audit(
            audit,
            [
                {
                    "function": "sqrt",
                    "precision": 64,
                    "argument_nonnegative": False,
                    "argument_expr_sha256": "c" * 64,
                }
            ],
        )
        self.assertFalse(finalized["eq_eligible"])
        self.assertIn(
            "sqrt_argument_not_proved_nonnegative:sqrt",
            finalized["eq_blockers"],
        )

    def test_unconstrained_return_and_fenv_observation_block_eq(self) -> None:
        exp_audit = models.finalize_runtime_audit(
            models.audit_binary_imports(["exp"]),
            [],
        )
        self.assertFalse(exp_audit["eq_eligible"])
        self.assertIn(
            "unqualified_external_model:exp",
            exp_audit["eq_blockers"],
        )

        fenv_audit = models.finalize_runtime_audit(
            models.audit_binary_imports(
                ["sqrt", "fetestexcept", "__errno_location"]
            ),
            [],
        )
        self.assertFalse(fenv_audit["eq_eligible"])
        self.assertTrue(
            any(
                blocker.startswith("floating_point_environment_observable:")
                for blocker in fenv_audit["eq_blockers"]
            )
        )

    def test_verifier_gate_downgrades_unqualified_eq(self) -> None:
        unqualified = models.finalize_runtime_audit(
            models.audit_binary_imports(["exp"]),
            [],
        )
        exploration = {
            "symbolic_oldV": {
                "schema": "symbolicana.exploration.v4",
                "external_model_audit": unqualified,
            },
            "symbolic_newV": {
                "schema": "symbolicana.exploration.v4",
                "external_model_audit": unqualified,
            },
        }
        audit = verifier.semantic_model_eq_audit(exploration)
        self.assertFalse(audit["eq_eligible"])
        result = verifier.apply_semantic_model_gate(
            {"verdict": "EQ", "prediction": True},
            audit,
        )
        self.assertEqual(result["verdict"], "UNK")
        self.assertEqual(result["raw_verdict_before_semantic_model_gate"], "EQ")
        self.assertEqual(result["failure_stage"], "semantic_model_unqualified")

    def test_unqualified_neq_requires_static_path_replay(self) -> None:
        unqualified = models.finalize_runtime_audit(
            models.audit_binary_imports(["exp"]),
            [],
        )
        exploration = {
            "symbolic_oldV": {
                "schema": "symbolicana.exploration.v4",
                "external_model_audit": unqualified,
            },
            "symbolic_newV": {
                "schema": "symbolicana.exploration.v4",
                "external_model_audit": unqualified,
            },
        }
        audit = verifier.semantic_model_eq_audit(exploration)
        static_result = verifier.apply_semantic_model_gate(
            {
                "verdict": "NEQ",
                "prediction": False,
                "static_only": True,
                "confirmed_mismatches": [
                    {
                        "replay": {"confirmed": True},
                    }
                ],
            },
            audit,
        )
        self.assertEqual(static_result["verdict"], "NEQ")
        self.assertTrue(static_result["semantic_model_neq_eligible"])

        seed_result = verifier.apply_semantic_model_gate(
            {
                "verdict": "NEQ",
                "prediction": False,
                "static_only": True,
                "confirmed_mismatches": [
                    {
                        "replay": {"confirmed": True},
                        "counterexample_source": "standard_domain_seed_replay",
                    }
                ],
            },
            audit,
        )
        self.assertEqual(seed_result["verdict"], "UNK")
        self.assertEqual(
            seed_result["failure_stage"],
            "semantic_model_neq_replay_required",
        )

    def test_legacy_artifacts_keep_existing_behavior(self) -> None:
        audit = verifier.semantic_model_eq_audit(
            {
                "symbolic_oldV": {"schema": "symbolicana.exploration.v3"},
                "symbolic_newV": {"schema": "symbolicana.exploration.v3"},
            }
        )
        self.assertTrue(audit["eq_eligible"])
        self.assertFalse(audit["applicable"])
        self.assertTrue(audit["legacy_artifact"])


if __name__ == "__main__":
    unittest.main()
