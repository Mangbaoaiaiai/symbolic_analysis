from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from z3 import Context, FP, FPVal, FPSort, Solver


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_ardiff_path_benchmarks as benchmark_builder
import prepare_osf_all
import verify_ranked_path_equivalence as verifier
from run_evaluation import Group, GroupResult, infer_prediction
from translate_ardiff_java_to_typed_c import printf_format
from symbolic_analysis.analysis.path_constraint_features import extract_features


SMT_HEADER = """(set-info :status unknown)
(declare-fun x () (_ BitVec 32))
"""


class BenchmarkManifestTests(unittest.TestCase):
    def test_relative_paths_use_posix_separators(self) -> None:
        rel = benchmark_builder.rel_to(ROOT / "a" / "b" / "ranking.json", ROOT / "a")
        self.assertEqual(rel, "b/ranking.json")
        self.assertNotIn("\\", rel)


class FeatureVectorTests(unittest.TestCase):
    def test_dominant_bitvector_width_uses_mode(self) -> None:
        content = """\
(declare-fun x () (_ BitVec 32))
(declare-fun y () (_ BitVec 32))
(declare-fun z () (_ BitVec 64))
(assert (= x y))
(assert (= y z))
"""
        raw, names = extract_features(content)
        self.assertEqual(raw[2], 32)
        self.assertEqual(names["main_bv_width"], 32.0)


class HarnessFormattingTests(unittest.TestCase):
    def test_float_replay_uses_hex_float(self) -> None:
        self.assertEqual(printf_format("double"), "%a")
        self.assertEqual(printf_format("float"), "%a")
        self.assertEqual(printf_format("int"), "%d")

    def test_c_source_wrapper_preserves_helper_functions(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            source = Path(raw_dir) / "source.c"
            source.write_text(
                "static int helper(int x) { return x + 1; }\n"
                "int snippet(int x) { return helper(x); }\n",
                encoding="utf-8",
            )
            wrapped = prepare_osf_all.wrap_snippet_source(source)
            self.assertIn("static int helper(int x)", wrapped)
            self.assertIn("int snippet(int x)", wrapped)
            self.assertIn("int result = snippet(x);", wrapped)
            self.assertIn("Result: %d", wrapped)

    def test_main_wrapper_analyzes_the_declared_main_body(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            source = Path(raw_dir) / "source.c"
            source.write_text(
                "int foo(int a, int b) { return a + b; }\n"
                "int main(void) { return foo(2, 3); }\n",
                encoding="utf-8",
            )
            wrapped = prepare_osf_all.wrap_main_source(source)
            self.assertIn("benchmark_original_main", wrapped)
            self.assertIn("int snippet(void) { return benchmark_original_main(); }", wrapped)
            self.assertIn("int result = snippet();", wrapped)
            self.assertNotIn("scanf(", wrapped.rsplit("int main(void)", 1)[-1])

    def test_main_scalar_parameter_is_preserved_and_argv_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            source = Path(raw_dir) / "source.c"
            source.write_text(
                "int foo(int a) { return a + 1; }\n"
                "int main(int x, char*argv[]) { return foo(x); }\n",
                encoding="utf-8",
            )
            wrapped = prepare_osf_all.wrap_main_source(source)
            self.assertIn("int benchmark_original_main(int x)", wrapped)
            self.assertIn("int snippet(int x) { return benchmark_original_main(x); }", wrapped)
            self.assertIn("scanf(\"%d\", &x);", wrapped)


class EvaluationVerdictTests(unittest.TestCase):
    def test_missing_verdict_is_not_inferred_from_alignment(self) -> None:
        result = GroupResult(
            pair_id="Airy/MAX_Eq",
            subset="Airy",
            program="MAX_Eq",
            group=Group.NAIVE,
            status="ok",
        )
        result.pairing.aligned_pairs = 1
        self.assertIsNone(infer_prediction(result))

    def test_missing_exploration_manifest_is_unk(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            paths_dir = Path(raw_dir)
            (paths_dir / "symbolic_oldV_path_1.txt").write_text(
                SMT_HEADER + "(assert (= x (_ bv1 32)))\n", encoding="utf-8"
            )
            (paths_dir / "symbolic_newV_path_1.txt").write_text(
                SMT_HEADER + "(assert (= x (_ bv1 32)))\n", encoding="utf-8"
            )
            result = verifier.verify_ranked_queue(
                paths_dir,
                None,
                timeout_ms=1_000,
                naive=True,
                truth_pairs=None,
                program_ground_truth=True,
                allow_legacy_artifacts=False,
            )
            self.assertEqual(result["verdict"], "UNK")
            self.assertIsNone(result["prediction"])

    def test_identical_return_expressions_are_equivalence_proof(self) -> None:
        summary = {
            "available": True,
            "bits": 64,
            "repr": "<BV64 fpToIEEEBV(fpAdd(RM.RM_NearestTiesEven, x, y))>",
            "smt": "not valid SMT; the reflexive check must run first",
        }
        equivalent, elapsed, calls = verifier.verify_return_smt_equivalence(
            summary, dict(summary), 60_000
        )
        self.assertTrue(equivalent)
        self.assertEqual(elapsed, 0.0)
        self.assertEqual(calls, 0)

    def test_float_model_value_is_converted_without_fp_to_bv_query(self) -> None:
        context = Context()
        value = FP("value", FPSort(11, 53, ctx=context))
        solver = Solver(ctx=context)
        solver.add(value == FPVal(2.0, ctx=context))
        self.assertEqual(str(solver.check()), "sat")
        concrete = verifier.z3_value_to_concrete(
            solver.model(),
            solver.model().eval(value, model_completion=True),
        )
        self.assertEqual(concrete["kind"], "float")
        self.assertEqual(concrete["bits"], 64)
        self.assertEqual(concrete["value"], 2.0)

    def test_seeded_overlap_model_finds_counterexample(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            header = """(set-info :status unknown)
(declare-fun arg_0 () (_ BitVec 32))
"""
            left_path = root / "symbolic_oldV_path_1.txt"
            right_path = root / "symbolic_newV_path_1.txt"
            left_path.write_text(
                header + "(assert (bvsle arg_0 (_ bv10 32)))\n",
                encoding="utf-8",
            )
            right_path.write_text(
                header + "(assert (bvsle arg_0 (_ bv10 32)))\n",
                encoding="utf-8",
            )
            left = {
                "return_value": {
                    "available": True,
                    "bits": 32,
                    "repr": "arg_0",
                    "smt": header
                    + "(declare-fun __return_value () (_ BitVec 32))\n"
                    + "(assert (= __return_value arg_0))\n"
                    + "(check-sat)\n",
                }
            }
            right = {
                "return_value": {
                    "available": True,
                    "bits": 32,
                    "repr": "arg_0 + 1",
                    "smt": header
                    + "(declare-fun __return_value () (_ BitVec 32))\n"
                    + "(assert (= __return_value (bvadd arg_0 (_ bv1 32))))\n"
                    + "(check-sat)\n",
                }
            }
            seed = [
                {
                    "name": "arg_0",
                    "kind": "bitvec",
                    "bits": 32,
                    "value": 3,
                    "unsigned": 3,
                }
            ]
            counterexample = verifier.find_return_counterexample(
                left,
                right,
                1_000,
                left_path,
                right_path,
                seed_inputs=seed,
            )
            self.assertIsNotNone(counterexample)
            self.assertEqual(counterexample["inputs"], seed)


class ProgramOutputTests(unittest.TestCase):
    def test_missing_output_metadata_is_unknown(self) -> None:
        equivalent, _elapsed, _calls = verifier.verify_output_equivalence({}, {}, 1_000)
        self.assertIsNone(equivalent)

    def test_text_output_difference_is_detected(self) -> None:
        left = {
            "program_output": {
                "available": True,
                "events": [
                    {
                        "call": "printf",
                        "sink": "stdout",
                        "segments": [{"kind": "text", "value": "negative\n"}],
                    }
                ],
            }
        }
        right = {
            "program_output": {
                "available": True,
                "events": [],
            }
        }
        equivalent, _elapsed, calls = verifier.verify_output_equivalence(
            left, right, 1_000
        )
        self.assertFalse(equivalent)
        self.assertEqual(calls, 0)

    def test_symbolic_output_values_are_compared_by_smt(self) -> None:
        header = """(set-info :status unknown)
(declare-fun arg_0 () (_ BitVec 32))
"""
        left = {
            "program_output": {
                "available": True,
                "events": [
                    {
                        "call": "printf",
                        "sink": "stdout",
                        "segments": [
                            {
                                "kind": "formatted_value",
                                "available": True,
                                "specifier": "%d",
                                "bits": 32,
                                "variable": "__output_0_0",
                                "repr": "arg_0",
                                "smt": header
                                + "(declare-fun __output_0_0 () (_ BitVec 32))\n"
                                + "(assert (= __output_0_0 arg_0))\n",
                            }
                        ],
                    }
                ],
            }
        }
        right = {
            "program_output": {
                "available": True,
                "events": [
                    {
                        "call": "printf",
                        "sink": "stdout",
                        "segments": [
                            {
                                "kind": "formatted_value",
                                "available": True,
                                "specifier": "%d",
                                "bits": 32,
                                "variable": "__output_0_0",
                                "repr": "arg_0 + 0",
                                "smt": header
                                + "(declare-fun __output_0_0 () (_ BitVec 32))\n"
                                + "(assert (= __output_0_0 "
                                + "(bvadd arg_0 (_ bv0 32))))\n",
                            }
                        ],
                    }
                ],
            }
        }
        equivalent, _elapsed, calls = verifier.verify_output_equivalence(
            left, right, 1_000
        )
        self.assertTrue(equivalent)
        self.assertEqual(calls, 1)

    def test_output_difference_is_neq_only_after_replay(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            header = """(set-info :status unknown)
(declare-fun arg_0 () (_ BitVec 32))
"""
            old = directory / "symbolic_oldV_path_1.txt"
            new = directory / "symbolic_newV_path_1.txt"
            base = {
                "return_value": {
                    "available": True,
                    "bits": 32,
                    "repr": "0",
                },
                "global_state": {
                    "available": True,
                    "regions": {},
                },
            }
            old_summary = {
                **base,
                "program_output": {
                    "available": True,
                    "events": [
                        {
                            "call": "printf",
                            "sink": "stdout",
                            "segments": [
                                {"kind": "text", "value": "negative\n"}
                            ],
                        }
                    ],
                },
            }
            new_summary = {
                **base,
                "program_output": {
                    "available": True,
                    "events": [],
                },
            }
            condition = "(assert (bvslt arg_0 (_ bv0 32)))\n"
            for path, summary in ((old, old_summary), (new, new_summary)):
                path.write_text(
                    header
                    + condition
                    + "; Semantic summary JSON: "
                    + verifier.json.dumps(summary)
                    + "\n",
                    encoding="utf-8",
                )
            with mock.patch.object(
                verifier,
                "replay_counterexample",
                return_value={"confirmed": True, "reason": "test"},
            ) as replay:
                result = verifier.verify_directional_cover(
                    [old],
                    [new],
                    {"symbolic_oldV_path_1": ["symbolic_newV_path_1"]},
                    timeout_ms=2_000,
                )
            self.assertEqual(len(result["confirmed_mismatches"]), 1)
            self.assertEqual(
                result["confirmed_mismatches"][0]["replay"]["reason"], "test"
            )
            replay.assert_called_once()


class CoverageTests(unittest.TestCase):
    def _path(self, directory: Path, name: str, predicate: str) -> Path:
        path = directory / name
        path.write_text(SMT_HEADER + f"(assert {predicate})\n", encoding="utf-8")
        return path

    def test_one_to_many_union_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old_neg = self._path(directory, "old_neg.txt", "(bvslt x (_ bv0 32))")
            old_nonneg = self._path(directory, "old_nonneg.txt", "(bvsge x (_ bv0 32))")
            new_neg = self._path(directory, "new_neg.txt", "(bvslt x (_ bv0 32))")
            new_nonneg = self._path(directory, "new_nonneg.txt", "(bvsge x (_ bv0 32))")
            covered, _ = verifier.check_union_coverage(
                [old_neg, old_nonneg], [new_neg, new_nonneg], 5_000
            )
            self.assertTrue(covered)

    def test_simplifiable_equal_paths_are_covered(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = directory / "old.txt"
            new = directory / "new.txt"
            old.write_text(
                SMT_HEADER
                + "(assert (let ((?x10 (bvadd x (_ bv1 32)))) "
                + "(= ?x10 (_ bv3 32))))\n",
                encoding="utf-8",
            )
            new.write_text(
                SMT_HEADER
                + "(assert (let ((?x99 (bvadd x (_ bv1 32)))) "
                + "(= ?x99 (_ bv3 32))))\n",
                encoding="utf-8",
            )
            covered, elapsed = verifier.check_union_coverage([old], [new], 5_000)
            self.assertTrue(covered)
            self.assertEqual(elapsed, 0.0)

    def test_exact_path_bijection_checks_return_and_global_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(directory, "symbolic_oldV_path_1.txt", "(= x (_ bv1 32))")
            new = self._path(directory, "symbolic_newV_path_1.txt", "(= x (_ bv1 32))")
            summary = {
                "return_value": {
                    "available": True,
                    "bits": 32,
                    "repr": "x",
                },
                "program_output": {
                    "available": True,
                    "events": [],
                },
                "global_state": {
                    "available": True,
                    "regions": {},
                },
            }
            for path in (old, new):
                with path.open("a", encoding="utf-8") as stream:
                    stream.write("; Semantic summary JSON: " + verifier.json.dumps(summary) + "\n")
            records = verifier.exact_path_bijection_proves_equivalence([old], [new])
            self.assertIsNotNone(records)
            self.assertEqual(records[0]["match_type"], "one_to_one_exact")

    def test_exact_path_bijection_rejects_different_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(
                directory, "symbolic_oldV_path_1.txt", "(= x (_ bv1 32))"
            )
            new = self._path(
                directory, "symbolic_newV_path_1.txt", "(= x (_ bv1 32))"
            )
            base = {
                "return_value": {
                    "available": True,
                    "bits": 32,
                    "repr": "x",
                },
                "global_state": {
                    "available": True,
                    "regions": {},
                },
            }
            old_summary = {
                **base,
                "program_output": {
                    "available": True,
                    "events": [
                        {
                            "call": "printf",
                            "sink": "stdout",
                            "segments": [{"kind": "text", "value": "old\n"}],
                        }
                    ],
                },
            }
            new_summary = {
                **base,
                "program_output": {
                    "available": True,
                    "events": [],
                },
            }
            for path, summary in ((old, old_summary), (new, new_summary)):
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(
                        "; Semantic summary JSON: "
                        + verifier.json.dumps(summary)
                        + "\n"
                    )
            records = verifier.exact_path_bijection_proves_equivalence([old], [new])
            self.assertIsNone(records)

    def test_exact_path_bijection_requires_output_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(
                directory, "symbolic_oldV_path_1.txt", "(= x (_ bv1 32))"
            )
            new = self._path(
                directory, "symbolic_newV_path_1.txt", "(= x (_ bv1 32))"
            )
            summary = {
                "return_value": {
                    "available": True,
                    "bits": 32,
                    "repr": "x",
                },
                "global_state": {
                    "available": True,
                    "regions": {},
                },
            }
            for path in (old, new):
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(
                        "; Semantic summary JSON: "
                        + verifier.json.dumps(summary)
                        + "\n"
                    )
            records = verifier.exact_path_bijection_proves_equivalence([old], [new])
            self.assertIsNone(records)

    def test_missing_target_region_is_not_covered(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(directory, "old.txt", "(bvsge x (_ bv0 32))")
            target = self._path(directory, "target.txt", "(bvslt x (_ bv0 32))")
            covered, _ = verifier.check_union_coverage([old], [target], 5_000)
            self.assertFalse(covered)

    def test_unsat_path_is_removed_before_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            sat_path = self._path(directory, "sat.txt", "(= x (_ bv1 32))")
            unsat_path = directory / "unsat.txt"
            unsat_path.write_text(
                SMT_HEADER
                + "(assert (= x (_ bv1 32)))\n"
                + "(assert (= x (_ bv2 32)))\n",
                encoding="utf-8",
            )
            feasible, removed, unknown, _elapsed = verifier.filter_definitely_unsat_paths(
                [sat_path, unsat_path], 1_000
            )
            self.assertEqual(feasible, [sat_path])
            self.assertEqual(removed, 1)
            self.assertEqual(unknown, 0)

    def test_confirmed_neq_stops_directional_scan(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            header = SMT_HEADER
            old = []
            new = []
            for index, value in ((1, 0), (2, 1)):
                old_path = directory / f"symbolic_oldV_path_{index}.txt"
                new_path = directory / f"symbolic_newV_path_{index}.txt"
                old_summary = {
                    "return_value": {
                        "available": True,
                        "bits": 32,
                        "repr": f"x+{value}",
                        "smt": header
                        + "(declare-fun __return_value () (_ BitVec 32))\n"
                        + f"(assert (= __return_value (bvadd x (_ bv{value} 32))))\n"
                        + "(check-sat)\n",
                    }
                }
                new_summary = {
                    "return_value": {
                        "available": True,
                        "bits": 32,
                        "repr": f"x+{value + 1}",
                        "smt": header
                        + "(declare-fun __return_value () (_ BitVec 32))\n"
                        + f"(assert (= __return_value (bvadd x (_ bv{value + 1} 32))))\n"
                        + "(check-sat)\n",
                    }
                }
                condition = f"(assert (= x (_ bv{value} 32)))\n"
                old_path.write_text(
                    header + condition + "; Semantic summary JSON: "
                    + verifier.json.dumps(old_summary) + "\n",
                    encoding="utf-8",
                )
                new_path.write_text(
                    header + condition + "; Semantic summary JSON: "
                    + verifier.json.dumps(new_summary) + "\n",
                    encoding="utf-8",
                )
                old.append(old_path)
                new.append(new_path)
            ranking = {
                "symbolic_oldV_path_1": ["symbolic_newV_path_1"],
                "symbolic_oldV_path_2": ["symbolic_newV_path_2"],
            }
            with mock.patch.object(
                verifier,
                "replay_counterexample",
                return_value={"confirmed": True, "reason": "test"},
            ):
                result = verifier.verify_directional_cover(
                    old, new, ranking, timeout_ms=2_000
                )
            self.assertEqual(len(result["confirmed_mismatches"]), 1)
            self.assertEqual(len(result["records"]), 1)
            self.assertEqual(result["records"][0]["query"], "symbolic_oldV_path_1")


if __name__ == "__main__":
    unittest.main()

