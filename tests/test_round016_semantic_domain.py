from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from z3 import And, BitVec, BoolVal, Context, Not, Solver, unsat


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from input_domain_contract import build_contract, sha256_json  # noqa: E402
from verify_ranked_path_equivalence import (  # noqa: E402
    _ACTIVE_INPUT_CONTRACT,
    add_active_domain_constraints,
    artifact_domain_audit,
    check_union_coverage_evidence,
    find_output_counterexample,
    verify_observable_expr_equivalence,
    verify_return_smt_equivalence,
)


DOUBLE_SCHEMA = [
    {
        "index": 0,
        "name": "arg_0",
        "c_type": "%lf",
        "kind": "float",
        "bits": 64,
        "precision": 0,
    }
]


class SemanticDomainConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tokens = []
        self._activate(DOUBLE_SCHEMA)

    def tearDown(self) -> None:
        for token in reversed(self.tokens):
            _ACTIVE_INPUT_CONTRACT.reset(token)

    def _activate(self, schema: list[dict]) -> None:
        self.contract = build_contract(schema)
        self.tokens.append(_ACTIVE_INPUT_CONTRACT.set(self.contract))

    @staticmethod
    def _return_summary(variable: str, value: int) -> dict:
        return {
            "available": True,
            "bits": 64,
            "kind": "bitvec",
            "variable": variable,
            "smt": (
                "(declare-fun FP_arg_0_0_64 () "
                "(_ FloatingPoint 11 53))\n"
                f"(declare-fun {variable} () (_ BitVec 64))\n"
                "(assert (fp.isNaN FP_arg_0_0_64))\n"
                f"(assert (= {variable} (_ bv{value} 64)))"
            ),
        }

    def test_return_difference_on_nan_is_excluded_by_finite_domain(self) -> None:
        equivalent, _elapsed, calls = verify_return_smt_equivalence(
            self._return_summary("__return_value_left", 1),
            self._return_summary("__return_value_right", 2),
            2_000,
        )
        self.assertTrue(equivalent)
        self.assertEqual(calls, 1)

    def test_observable_difference_on_nan_is_excluded_by_finite_domain(
        self,
    ) -> None:
        left = self._return_summary("__observable_left", 1)
        right = self._return_summary("__observable_right", 2)
        left["variable"] = "__observable_left"
        right["variable"] = "__observable_right"
        equivalent, _elapsed = verify_observable_expr_equivalence(
            left,
            right,
            2_000,
        )
        self.assertTrue(equivalent)

    def test_output_counterexample_is_filtered_by_numeric_domain(self) -> None:
        _ACTIVE_INPUT_CONTRACT.reset(self.tokens.pop())
        self._activate(
            [
                {
                    "index": 0,
                    "name": "arg_0",
                    "c_type": "%d",
                    "kind": "bitvec",
                    "bits": 32,
                    "precision": 0,
                }
            ]
        )

        def output_summary(variable: str, value: int) -> dict:
            smt = (
                "(declare-fun arg_0_0_32 () (_ BitVec 32))\n"
                f"(declare-fun {variable} () (_ BitVec 32))\n"
                "(assert (= arg_0_0_32 (_ bv1000 32)))\n"
                f"(assert (= {variable} (_ bv{value} 32)))"
            )
            return {
                "program_output": {
                    "available": True,
                    "unresolved": [],
                    "events": [
                        {
                            "sink": "stdout",
                            "segments": [
                                {
                                    "kind": "formatted_value",
                                    "specifier": "%d",
                                    "bits": 32,
                                    "variable": variable,
                                    "smt": smt,
                                }
                            ],
                        }
                    ],
                }
            }

        counterexample = find_output_counterexample(
            output_summary("__output_left", 1),
            output_summary("__output_right", 2),
            2_000,
        )
        self.assertIsNone(counterexample)

    def test_unbounded_artifact_requires_matching_schema_for_reuse(self) -> None:
        matching = artifact_domain_audit(
            {
                "symbolic_oldV": {"input_schema": DOUBLE_SCHEMA},
                "symbolic_newV": {"input_schema": DOUBLE_SCHEMA},
            },
            self.contract,
        )
        self.assertTrue(matching["compatible"])
        self.assertTrue(
            matching["sides"]["old"][
                "external_domain_conjunction_required"
            ]
        )

        mismatch = artifact_domain_audit(
            {
                "symbolic_oldV": {
                    "input_schema": [
                        *DOUBLE_SCHEMA,
                        {
                            "index": 1,
                            "name": "arg_1",
                            "c_type": "%lf",
                            "kind": "float",
                            "bits": 64,
                            "precision": 0,
                        },
                    ]
                },
                "symbolic_newV": {"input_schema": DOUBLE_SCHEMA},
            },
            self.contract,
        )
        self.assertFalse(mismatch["compatible"])
        self.assertIn(
            "domain_input_schema_mismatch",
            mismatch["sides"]["old"]["reasons"],
        )

    def test_domain_audit_uses_semantic_hash_for_pair_specific_storage(
        self,
    ) -> None:
        semantic_artifact = dict(self.contract)
        pair_specific_contract = {
            **self.contract,
            "pair_id": "opaque-task",
            "source": "round017_p0",
            "status": "supported",
            "domain_hash": "pair-specific-stored-hash",
        }
        exploration = {
            side: {
                "input_schema": DOUBLE_SCHEMA,
                "input_contract": semantic_artifact,
                "input_domain_profile_hash": sha256_json(
                    self.contract["profile"]
                ),
            }
            for side in ("symbolic_oldV", "symbolic_newV")
        }
        audit = artifact_domain_audit(
            exploration,
            pair_specific_contract,
        )
        self.assertTrue(audit["compatible"])
        self.assertEqual(
            audit["sides"]["old"]["contract_hash_basis"],
            "semantic_canonical",
        )

        changed_contract = {
            **self.contract,
            "inputs": [
                {
                    **self.contract["inputs"][0],
                    "bounds": {
                        **self.contract["inputs"][0]["bounds"],
                        "minimum": -1.0,
                    },
                }
            ],
        }
        exploration["symbolic_oldV"]["input_contract"] = changed_contract
        mismatch = artifact_domain_audit(
            exploration,
            pair_specific_contract,
        )
        self.assertFalse(mismatch["compatible"])
        self.assertIn(
            "domain_contract_hash_mismatch",
            mismatch["sides"]["old"]["reasons"],
        )

    def test_joint_formula_domain_closes_true_path_gap(self) -> None:
        _ACTIVE_INPUT_CONTRACT.reset(self.tokens.pop())
        self._activate(
            [
                {
                    "index": 0,
                    "name": "arg_0",
                    "c_type": "%d",
                    "kind": "bitvec",
                    "bits": 32,
                    "precision": 0,
                }
            ]
        )
        context = Context()
        source = BoolVal(True, ctx=context)
        argument = BitVec("arg_0_0_32", 32, ctx=context)
        target = And(argument >= -100, argument <= 100)
        solver = Solver(ctx=context)
        solver.add(source, Not(target))
        add_active_domain_constraints(
            solver,
            context,
            source,
            target,
        )
        self.assertEqual(solver.check(), unsat)

    def test_global_union_query_applies_domain_to_unconstrained_side(
        self,
    ) -> None:
        _ACTIVE_INPUT_CONTRACT.reset(self.tokens.pop())
        self._activate(
            [
                {
                    "index": 0,
                    "name": "arg_0",
                    "c_type": "%d",
                    "kind": "bitvec",
                    "bits": 32,
                    "precision": 0,
                }
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "symbolic_oldV_path_1.txt"
            target = root / "symbolic_newV_path_1.txt"
            declarations = (
                "(declare-fun arg_0_0_32 () (_ BitVec 32))\n"
            )
            source.write_text(
                declarations + "(assert true)\n(check-sat)\n",
                encoding="utf-8",
            )
            target.write_text(
                declarations
                + "(assert (and "
                "(bvsge arg_0_0_32 (_ bv4294967196 32)) "
                "(bvsle arg_0_0_32 (_ bv100 32))))\n"
                "(check-sat)\n",
                encoding="utf-8",
            )
            evidence = check_union_coverage_evidence(
                [source],
                [target],
                2_000,
                direction="old_domain_subset_new_domain",
            )
        self.assertEqual(evidence["status"], "unsat")
        self.assertTrue(evidence["subset"])
        self.assertEqual(
            evidence["representation"],
            "compact_smt_lib_union",
        )
        self.assertEqual(
            evidence["input_ranges"],
            {
                "integer": [-100, 100],
                "floating_point": [-100.0, 100.0],
            },
        )


if __name__ == "__main__":
    unittest.main()
