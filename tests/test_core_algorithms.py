from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
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
from generate_path_truth import compute_pair_truth
from translate_ardiff_java_to_typed_c import printf_format
from symbolic_analysis.analysis.hybrid_path_matching import bindiff_path_similarity
from symbolic_analysis.analysis.path_constraint_features import (
    FEATURE_NAMES,
    FeatureExtractionError,
    cosine_with_validity,
    extract_feature_record,
    extract_features,
)
import symbolic_analysis.analysis.path_constraint_features as path_features


SMT_HEADER = """(set-info :status unknown)
(declare-fun x () (_ BitVec 32))
"""


class BenchmarkManifestTests(unittest.TestCase):
    def test_bool_float_snippet_signature_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            source = Path(raw_tmp) / "symbolic_oldV.c"
            source.write_text(
                "bool snippet(float a, float b) { return a < b; }\n",
                encoding="utf-8",
            )
            self.assertEqual(
                benchmark_builder.extract_c_snippet_signature(source),
                "bool(float,float)",
            )

    def test_relative_paths_use_posix_separators(self) -> None:
        rel = benchmark_builder.rel_to(ROOT / "a" / "b" / "ranking.json", ROOT / "a")
        self.assertEqual(rel, "b/ranking.json")
        self.assertNotIn("\\", rel)

    def test_per_family_domain_override_keeps_default_fallback(self) -> None:
        config = ROOT / "configs" / "paper_62_domains.csv"
        domains = benchmark_builder.load_case_domains(config)
        args = SimpleNamespace(
            int_min=-100,
            int_max=100,
            float_min=-100.0,
            float_max=100.0,
            case_domains=domains,
        )
        resolved = benchmark_builder.case_domain_args(args, "ell")
        self.assertEqual(
            (resolved.int_min, resolved.int_max), (0, 10)
        )
        self.assertEqual(
            (resolved.float_min, resolved.float_max), (-1.0, 1.0)
        )
        fallback = benchmark_builder.case_domain_args(args, "bess")
        self.assertEqual(
            (fallback.int_min, fallback.int_max), (-100, 100)
        )
        self.assertEqual(
            (fallback.float_min, fallback.float_max), (-100.0, 100.0)
        )


class FeatureVectorTests(unittest.TestCase):
    def test_dominant_bitvector_width_uses_mode(self) -> None:
        content = """\
(declare-fun x () (_ BitVec 32))
(declare-fun y () (_ BitVec 32))
(declare-fun z () (_ BitVec 32))
(declare-fun unused64 () (_ BitVec 64))
(assert (= x y))
(assert (= y z))
"""
        raw, names = extract_features(content)
        self.assertEqual(raw[2], 32)
        self.assertEqual(names["main_bv_width"], 32.0)

    def test_let_expansion_counts_each_reference(self) -> None:
        content = """\
(declare-fun arg_0_0_32 () (_ BitVec 32))
(assert
  (let ((t (bvadd arg_0_0_32 (_ bv1 32))))
    (and (= t (_ bv0 32))
         (bvslt t (_ bv10 32)))))
"""
        record = extract_feature_record(content)
        self.assertEqual(record.values["assert_count"], 1)
        self.assertEqual(record.values["variable_count"], 1)
        self.assertEqual(record.values["main_bv_width"], 32)
        self.assertEqual(record.values["operator_type_count"], 4)
        self.assertAlmostEqual(record.values["comparison_ratio"], 2 / 5)
        self.assertEqual(record.details["operator_counts"]["bvadd"], 2)
        self.assertEqual(record.details["operator_counts"]["and"], 1)

    def test_shared_let_stats_are_memoized_by_ast_node(self) -> None:
        depth = 10
        bindings = []
        previous = "arg_0_0_32"
        for index in range(depth + 1):
            bindings.append(
                f"(let ((t{index} (bvadd {previous} {previous}))) "
            )
            previous = f"t{index}"
        body = (
            "".join(bindings)
            + f"(= t{depth} (_ bv0 32))"
            + (")" * (depth + 1))
        )
        content = (
            "(declare-fun arg_0_0_32 () (_ BitVec 32))\n"
            f"(assert {body})\n"
        )
        formulas = path_features.parse_constraints(content)
        cache: dict[tuple[int, bool], object] = {}
        stats = path_features._collect_stats(formulas[0], _cache=cache)
        self.assertEqual(stats.operator_counts["bvadd"], 2 ** (depth + 1) - 1)
        self.assertLessEqual(len(cache), 2 * (depth + 3))

    def test_signed_input_span_is_200(self) -> None:
        content = """\
(declare-fun arg_0_0_32 () (_ BitVec 32))
(assert (bvsge arg_0_0_32 (_ bv4294967196 32)))
(assert (bvsle arg_0_0_32 (_ bv100 32)))
"""
        record = extract_feature_record(content)
        self.assertTrue(record.valid["variable_range_span"])
        self.assertEqual(record.values["variable_range_span"], 200)

    def test_input_span_is_missing_when_one_bound_is_absent(self) -> None:
        content = """\
(declare-fun arg_0_0_32 () (_ BitVec 32))
(assert (bvsge arg_0_0_32 (_ bv0 32)))
"""
        record = extract_feature_record(content)
        self.assertFalse(record.valid["variable_range_span"])
        self.assertIn("incomplete bounds", record.missing["variable_range_span"])

    def test_shift_and_extract_features_are_hand_checkable(self) -> None:
        content = """\
(declare-fun x () (_ BitVec 32))
(declare-fun y () (_ BitVec 32))
(assert (= ((_ extract 7 0) (bvshl x (_ bv3 32)))
           ((_ extract 7 0) y)))
"""
        record = extract_feature_record(content)
        self.assertEqual(record.values["shift_coefficient"], 3)
        self.assertEqual(record.values["extract_count"], 2)
        self.assertEqual(record.values["dominant_constant_type"], 1)
        self.assertEqual(record.details["operator_counts"]["bvshl"], 1)

    def test_invalid_smt_is_not_silently_zero(self) -> None:
        with self.assertRaises(FeatureExtractionError):
            extract_feature_record("(declare-fun x () (_ BitVec 32)) (assert")

    def test_cosine_masks_missing_dimensions_on_both_sides(self) -> None:
        left = [1.0] * len(FEATURE_NAMES)
        right = [1.0] * len(FEATURE_NAMES)
        left[len(FEATURE_NAMES) - 1] = 100.0
        right_valid = [True] * len(FEATURE_NAMES)
        right_valid[len(FEATURE_NAMES) - 1] = False
        self.assertAlmostEqual(
            cosine_with_validity(left, right, None, right_valid),
            1.0,
        )


class TraceSimilarityTests(unittest.TestCase):
    def test_multiset_dice_uses_visit_counts(self) -> None:
        score = bindiff_path_similarity([10, 10, 10], [20, 20], {10: 20})
        self.assertAlmostEqual(score, 0.8)

    def test_multiset_dice_is_symmetric_with_inverse_map(self) -> None:
        forward = bindiff_path_similarity(
            [10, 10, 11], [20, 20, 21], {10: 20, 11: 21}
        )
        reverse = bindiff_path_similarity(
            [20, 20, 21], [10, 10, 11], {20: 10, 21: 11}
        )
        self.assertAlmostEqual(forward, reverse)
        self.assertGreaterEqual(forward, 0.0)
        self.assertLessEqual(forward, 1.0)

    def test_conflicting_or_empty_mapping_is_zero(self) -> None:
        self.assertEqual(bindiff_path_similarity([1, 2], [3, 4], {1: 3, 2: 3}), 0.0)
        self.assertEqual(bindiff_path_similarity([], [3], {1: 3}), 0.0)


class SymbolicExecutionCacheTests(unittest.TestCase):
    def test_cross_case_failure_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            binary = root / "binary"
            binary.write_bytes(b"elf-test")
            paths_out = root / "paths"
            paths_out.mkdir()
            args = SimpleNamespace(
                optimization="O3",
                timeout=1,
                max_paths=1,
                int_min=None,
                int_max=None,
                float_min=None,
                float_max=None,
                force_symbolic_exec=False,
                python="python",
            )
            cache_key = (
                hashlib.sha256(binary.read_bytes()).hexdigest(),
                "O3",
                1,
                1,
                None,
                None,
                None,
                None,
                None,
            )
            benchmark_builder._SYMBOLIC_EXEC_CACHE.clear()
            benchmark_builder._SYMBOLIC_EXEC_CACHE[cache_key] = {
                "status": "failure",
                "failure": {"error": "failure from another case"},
            }
            process = mock.Mock()
            process.poll.return_value = 1
            process.returncode = 1
            try:
                with mock.patch.object(
                    benchmark_builder.subprocess,
                    "Popen",
                    return_value=process,
                ) as popen:
                    with self.assertRaises(RuntimeError):
                        benchmark_builder.maybe_run_symbolic_exec(
                            binary,
                            paths_out,
                            "symbolic_oldV",
                            args,
                        )
                    popen.assert_called_once()
            finally:
                benchmark_builder._SYMBOLIC_EXEC_CACHE.clear()


class PathTruthTests(unittest.TestCase):
    def test_truth_uses_sat_overlap_not_path_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            header = "(declare-fun arg_0 () (_ BitVec 32))\n"
            old_negative = directory / "symbolic_oldV_path_2.txt"
            old_nonnegative = directory / "symbolic_oldV_path_1.txt"
            new_wide = directory / "symbolic_newV_path_9.txt"
            new_far = directory / "symbolic_newV_path_3.txt"
            old_negative.write_text(
                header + "(assert (bvslt arg_0 (_ bv0 32)))\n",
                encoding="utf-8",
            )
            old_nonnegative.write_text(
                header + "(assert (bvsge arg_0 (_ bv0 32)))\n",
                encoding="utf-8",
            )
            new_wide.write_text(
                header + "(assert (bvslt arg_0 (_ bv10 32)))\n",
                encoding="utf-8",
            )
            new_far.write_text(
                header + "(assert (bvsge arg_0 (_ bv100 32)))\n",
                encoding="utf-8",
            )
            related, payload = compute_pair_truth(
                [old_negative, old_nonnegative],
                [new_far, new_wide],
                2_000,
            )
            self.assertEqual(related["symbolic_oldV_path_2"], {"symbolic_newV_path_9"})
            self.assertEqual(
                related["symbolic_oldV_path_1"],
                {"symbolic_newV_path_3", "symbolic_newV_path_9"},
            )
            self.assertEqual(payload["semantics"], "sat_input_overlap")


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
        smt = """(declare-fun x () (_ BitVec 32))
(declare-fun y () (_ BitVec 32))
(declare-fun __return_value_1 () (_ BitVec 32))
(assert (= __return_value_1 (bvadd x y)))
"""
        summary = {
            "available": True,
            "bits": 32,
            "repr": "same-display-text",
            "smt": smt,
        }
        equivalent, elapsed, calls = verifier.verify_return_smt_equivalence(
            summary, dict(summary), 60_000
        )
        self.assertTrue(equivalent)
        self.assertEqual(elapsed, 0.0)
        self.assertEqual(calls, 0)

    def test_same_return_repr_with_different_smt_is_not_proof(self) -> None:
        left = {
            "available": True,
            "bits": 32,
            "repr": "same-display-text",
            "smt": """(declare-fun x () (_ BitVec 32))
(declare-fun y () (_ BitVec 32))
(declare-fun __return_value_1 () (_ BitVec 32))
(assert (= __return_value_1 (bvadd x y)))
""",
        }
        right = {
            "available": True,
            "bits": 32,
            "repr": "same-display-text",
            "smt": """(declare-fun x () (_ BitVec 32))
(declare-fun y () (_ BitVec 32))
(declare-fun __return_value_2 () (_ BitVec 32))
(assert (= __return_value_2 (bvsub x y)))
""",
        }
        self.assertFalse(verifier.return_expressions_identical(left, right))
        equivalent, _elapsed, _calls = verifier.verify_return_smt_equivalence(
            left, right, 1_000
        )
        self.assertFalse(equivalent)

    def test_missing_return_smt_is_unknown(self) -> None:
        summary = {"available": True, "bits": 32, "repr": "x"}
        equivalent, _elapsed = verifier.verify_return_equivalence(
            summary, dict(summary), 1_000
        )
        self.assertIsNone(equivalent)

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

    def test_nan_model_value_is_converted_without_crashing(self) -> None:
        context = Context()
        concrete = verifier.z3_value_to_concrete(
            None,
            FPVal(float("nan"), ctx=context),
        )
        self.assertEqual(concrete["kind"], "float")
        self.assertEqual(concrete["bits"], 64)
        self.assertNotEqual(concrete["value"], concrete["value"])

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
    def test_backend_mangled_output_variable_is_resolved(self) -> None:
        smt = """(set-info :status unknown)
(declare-fun __output_0_0_10_8 () (_ BitVec 32))
(assert (= (_ bv7 32) __output_0_0_10_8))
"""
        summary = {
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
                                "repr": "7",
                                "smt": smt,
                            }
                        ],
                    }
                ],
            }
        }
        self.assertEqual(
            verifier.summary_variable_name(smt, "__output_0_0"),
            "__output_0_0_10_8",
        )
        self.assertTrue(
            verifier.output_segments_identical(summary, summary)
        )

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

    def test_same_output_repr_with_different_smt_is_not_proof(self) -> None:
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
                                "repr": "same-display-text",
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
                                "repr": "same-display-text",
                                "smt": header
                                + "(declare-fun __output_0_0 () (_ BitVec 32))\n"
                                + "(assert (= __output_0_0 "
                                + "(bvadd arg_0 (_ bv1 32))))\n",
                            }
                        ],
                    }
                ],
            }
        }
        equivalent, _elapsed, calls = verifier.verify_output_equivalence(
            left, right, 1_000
        )
        self.assertFalse(equivalent)
        self.assertEqual(calls, 1)

    def test_malformed_output_smt_cannot_use_identity_shortcut(self) -> None:
        summary = {
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
                                "repr": "same-display-text",
                                "smt": "(declare-fun __output_0_0 () (_ BitVec 32)) (assert",
                            }
                        ],
                    }
                ],
            }
        }
        self.assertFalse(
            verifier.output_segments_identical(summary, summary)
        )

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
                    "smt": header
                    + "(declare-fun __return_value () (_ BitVec 32))\n"
                    + "(assert (= __return_value (_ bv0 32)))\n",
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

    def test_global_regions_use_historical_sorted_position_fallback(self) -> None:
        left = {
            "global": {
                "bits": 32,
                "variable": "__global_0",
                "smt": SMT_HEADER
                + "(declare-fun __global_0 () (_ BitVec 32))\n"
                + "(assert (= __global_0 (_ bv1 32)))\n",
            }
        }
        right = {
            "global": dict(left["global"]),
        }
        canonical_pairs, canonical_method = verifier.map_global_regions_with_mode(
            left,
            right,
        )
        fallback_pairs, fallback_method = verifier.map_global_regions_with_mode(
            left,
            {"other_global": dict(left["global"])},
        )
        self.assertEqual(canonical_method, "canonical_key")
        self.assertEqual(len(canonical_pairs or []), 1)
        self.assertEqual(fallback_method, "sorted_position_fallback")
        self.assertEqual(len(fallback_pairs or []), 1)

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
            self.assertGreaterEqual(elapsed, 0.0)
            evidence = verifier.check_union_coverage_evidence(
                [old],
                [new],
                5_000,
                direction="old_domain_subset_new_domain",
            )
            self.assertEqual(
                evidence["method"],
                "canonical_path_ast_identity",
            )
            self.assertNotEqual(
                verifier.exact_path_condition_text(old),
                verifier.exact_path_condition_text(new),
            )

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
                    "smt": SMT_HEADER
                    + "(declare-fun __return_value_1 () (_ BitVec 32))\n"
                    + "(assert (= __return_value_1 x))\n",
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

    def test_single_target_ablation_allows_target_reuse_and_subset(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old_1 = self._path(directory, "symbolic_oldV_path_1.txt", "(= x (_ bv1 32))")
            old_2 = self._path(directory, "symbolic_oldV_path_2.txt", "(= x (_ bv1 32))")
            new_1 = self._path(directory, "symbolic_newV_path_1.txt", "(= x (_ bv1 32))")
            ranking = {
                "symbolic_oldV_path_1": ["symbolic_newV_path_1"],
                "symbolic_oldV_path_2": ["symbolic_newV_path_1"],
            }
            semantic = (
                True,
                0.0,
                0,
                {
                    "input_overlap": "sat",
                    "semantic_mode": "test",
                },
            )
            equality = (
                False,
                0.0,
                {
                    "source_subset_targets": True,
                    "targets_subset_source": False,
                },
            )
            with mock.patch.object(
                verifier,
                "verify_semantic_path_relation",
                return_value=semantic,
            ), mock.patch.object(
                verifier,
                "check_path_union_equal",
                return_value=equality,
            ):
                strict = verifier.verify_directional_cover(
                    [old_1, old_2],
                    [new_1],
                    ranking,
                    1_000,
                    allow_one_to_many=False,
                )
                full = verifier.verify_directional_cover(
                    [old_1, old_2],
                    [new_1],
                    ranking,
                    1_000,
                    allow_one_to_many=True,
                )
            self.assertTrue(strict["success"])
            self.assertEqual(len(strict["matched_targets"]), 1)
            self.assertEqual(strict["matched_source_count"], 2)
            self.assertTrue(all(record["matched"] for record in strict["records"]))
            self.assertEqual(
                {record["match_type"] for record in strict["records"]},
                {"one_to_one_source_subset_target"},
            )
            self.assertTrue(full["success"])
            self.assertEqual(
                strict["matching_policy"],
                "single_target_reusable_source_subset",
            )
            self.assertEqual(full["matching_policy"], "multi_target_union")
            self.assertTrue(strict["target_reuse_allowed"])
            self.assertTrue(full["target_reuse_allowed"])
            self.assertTrue(strict["source_subset_allowed"])
            self.assertTrue(full["source_subset_allowed"])

    def test_single_target_ablation_does_not_accumulate_union(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(
                directory,
                "symbolic_oldV_path_1.txt",
                "(bvsge x (_ bv0 32))",
            )
            new_zero = self._path(
                directory,
                "symbolic_newV_path_1.txt",
                "(= x (_ bv0 32))",
            )
            new_positive = self._path(
                directory,
                "symbolic_newV_path_2.txt",
                "(bvsgt x (_ bv0 32))",
            )
            ranking = {
                "symbolic_oldV_path_1": [
                    "symbolic_newV_path_1",
                    "symbolic_newV_path_2",
                ]
            }
            semantic = (
                True,
                0.0,
                0,
                {
                    "input_overlap": "sat",
                    "semantic_mode": "test",
                },
            )

            def union_equal(
                _source: Path,
                targets: list[Path],
                _timeout_ms: int,
            ) -> tuple[bool, float, dict[str, bool]]:
                equal = len(targets) > 1
                return (
                    equal,
                    0.0,
                    {
                        "source_subset_targets": equal,
                        "targets_subset_source": equal,
                    },
                )

            with mock.patch.object(
                verifier,
                "verify_semantic_path_relation",
                return_value=semantic,
            ), mock.patch.object(
                verifier,
                "check_path_union_equal",
                side_effect=union_equal,
            ):
                strict = verifier.verify_directional_cover(
                    [old],
                    [new_zero, new_positive],
                    ranking,
                    1_000,
                    allow_one_to_many=False,
                )
                full = verifier.verify_directional_cover(
                    [old],
                    [new_zero, new_positive],
                    ranking,
                    1_000,
                    allow_one_to_many=True,
                )

            self.assertFalse(strict["success"])
            self.assertEqual(strict["records"][0]["match_type"], "unmatched")
            self.assertTrue(full["success"])
            self.assertEqual(
                full["records"][0]["match_type"],
                "one_to_many_exact_cover",
            )
            self.assertEqual(
                strict["matching_policy"],
                "single_target_reusable_source_subset",
            )
            self.assertEqual(full["matching_policy"], "multi_target_union")

    def test_exploration_count_mismatch_is_unk(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            paths_dir = Path(raw_dir)
            (paths_dir / "symbolic_oldV_path_1.txt").write_text(
                SMT_HEADER + "(assert (= x (_ bv1 32)))\n",
                encoding="utf-8",
            )
            (paths_dir / "symbolic_newV_path_1.txt").write_text(
                SMT_HEADER + "(assert (= x (_ bv1 32)))\n",
                encoding="utf-8",
            )
            for prefix in ("symbolic_oldV", "symbolic_newV"):
                (paths_dir / f"{prefix}_exploration.json").write_text(
                    verifier.json.dumps(
                        {
                            "complete": True,
                            "proof_eligible": True,
                            "incomplete_reasons": [],
                            "terminating_path_count": 2,
                            "active_count": 0,
                            "timeout_count": 0,
                            "loop_bound_event_count": 0,
                            "errored_count": 0,
                            "max_paths": 128,
                        }
                    ),
                    encoding="utf-8",
                )
            result = verifier.verify_ranked_queue(
                paths_dir,
                None,
                timeout_ms=1_000,
                naive=True,
                truth_pairs=None,
                program_ground_truth=True,
            )
            self.assertEqual(result["verdict"], "UNK")
            self.assertEqual(
                result["failure_reason"],
                "missing_or_incomplete_exploration_manifest",
            )

    def test_incomplete_artifact_can_only_confirm_neq_by_replay(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            paths_dir = Path(raw_dir)
            (paths_dir / "symbolic_oldV_path_1.txt").write_text(
                SMT_HEADER + "(assert (= x (_ bv1 32)))\n",
                encoding="utf-8",
            )
            (paths_dir / "symbolic_newV_path_1.txt").write_text(
                SMT_HEADER + "(assert (= x (_ bv1 32)))\n",
                encoding="utf-8",
            )
            for prefix in ("symbolic_oldV", "symbolic_newV"):
                (paths_dir / f"{prefix}_exploration.json").write_text(
                    verifier.json.dumps(
                        {
                            "complete": False,
                            "proof_eligible": False,
                            "incomplete_reasons": [
                                "lossy_address_concretization"
                            ],
                            "terminating_path_count": 1,
                            "active_count": 0,
                            "timeout_count": 0,
                            "loop_bound_event_count": 0,
                            "errored_count": 0,
                            "max_paths": 128,
                        }
                    ),
                    encoding="utf-8",
                )
            mismatch = {
                "query": "symbolic_oldV_path_1",
                "target": "symbolic_newV_path_1",
                "rank": 1,
                "prescan": True,
                "evidence_path": "confirmed.jsonl",
            }
            no_mismatch = {
                "mismatch": None,
                "records": [],
                "smt_calls": 0,
                "t_smt": 0.0,
                "semantic_modes": {},
            }
            with mock.patch.object(
                verifier,
                "program_domain_counterexample",
                return_value={"counterexample": None},
            ), mock.patch.object(
                verifier,
                "prescan_replayable_counterexample",
                side_effect=[
                    {
                        **no_mismatch,
                        "mismatch": mismatch,
                    },
                ],
            ):
                result = verifier.verify_ranked_queue(
                    paths_dir,
                    None,
                    timeout_ms=1_000,
                    naive=True,
                    truth_pairs=None,
                    program_ground_truth=True,
                )

        self.assertEqual(result["verdict"], "NEQ")
        self.assertEqual(result["fast_path_branch"], "ranked_prescan_NEQ")
        self.assertTrue(result["exploration_coverage_blocked"])

    def test_domain_mismatch_is_neq_without_feasibility_prefilter(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            (directory / "symbolic_oldV_path_1.txt").write_text(
                SMT_HEADER + "(assert (bvsge x (_ bv0 32)))\n",
                encoding="utf-8",
            )
            (directory / "symbolic_newV_path_1.txt").write_text(
                SMT_HEADER + "(assert (bvsle x (_ bv0 32)))\n",
                encoding="utf-8",
            )
            for prefix in ("symbolic_oldV", "symbolic_newV"):
                (directory / f"{prefix}_exploration.json").write_text(
                    verifier.json.dumps(
                        {
                            "complete": True,
                            "proof_eligible": True,
                            "incomplete_reasons": [],
                            "terminating_path_count": 1,
                            "active_count": 0,
                            "timeout_count": 0,
                            "loop_bound_event_count": 0,
                            "errored_count": 0,
                            "max_paths": 128,
                            "input_ranges": {
                                "integer": "full_representable_input_space",
                                "floating_point": "full_representable_input_space",
                            },
                        }
                    ),
                    encoding="utf-8",
                )
            old_mismatch = {
                "direction": "old_domain_subset_new_domain",
                "status": "sat",
                "subset": False,
                "method": "smt_union_exclusion",
                "elapsed_seconds": 0.01,
                "query_path": "old.smt2",
                "query_sha256": "old-hash",
                "witness_inputs": [
                    {
                        "name": "x",
                        "kind": "bitvec",
                        "bits": 32,
                        "value": 1,
                        "unsigned": 1,
                    }
                ],
                "witness_schema_complete": True,
            }
            new_unknown = {
                "direction": "new_domain_subset_old_domain",
                "status": "unknown",
                "subset": None,
                "method": "smt_union_exclusion",
                "elapsed_seconds": 0.02,
                "query_path": "new.smt2",
                "query_sha256": "new-hash",
                "reason_unknown": "timeout",
                "witness_schema_complete": False,
            }
            with mock.patch.object(
                verifier,
                "filter_definitely_unsat_paths",
            ) as feasibility_filter, mock.patch.object(
                verifier,
                "program_domain_counterexample",
                return_value={"counterexample": None, "reason": "not_found"},
            ), mock.patch.object(
                verifier,
                "prescan_replayable_counterexample",
                return_value={
                    "mismatch": None,
                    "records": [],
                    "smt_calls": 0,
                    "t_smt": 0.0,
                    "semantic_modes": {},
                },
            ), mock.patch.object(
                verifier,
                "check_union_coverage_evidence",
                side_effect=[old_mismatch, new_unknown],
            ), mock.patch.object(
                verifier,
                "audit_domain_witness",
                return_value={
                    "direction": "old_domain_subset_new_domain",
                    "classification": "definedness_mismatch",
                    "reason": "one_side_defined_success_other_defined_rejection",
                    "definedness_confirmed": True,
                    "supports_neq": True,
                    "witness_schema_complete": True,
                    "witness_inputs": old_mismatch["witness_inputs"],
                    "replay": {
                        "confirmed": False,
                        "reason": "program_exit_nonzero",
                        "left": {
                            "completed": True,
                            "returncode": 3,
                            "stdout": "",
                            "stderr": "",
                        },
                        "right": {
                            "completed": True,
                            "returncode": 0,
                            "stdout": "ok\n",
                            "stderr": "",
                        },
                    },
                },
            ):
                result = verifier.verify_ranked_queue(
                    directory,
                    None,
                    timeout_ms=1_000,
                    naive=True,
                    truth_pairs=None,
                    program_ground_truth=True,
                )

        feasibility_filter.assert_not_called()
        self.assertEqual(result["verdict"], "NEQ")
        self.assertEqual(result["domain_mismatch_count"], 1)
        self.assertEqual(result["fast_path_branch"], "confirmed_domain_NEQ")
        self.assertEqual(result["feasibility_complete"], "not_applicable")
        self.assertIsNone(result["new_input_subset_old"])
        self.assertFalse(result["old_input_subset_new"])

    def test_domain_artifact_coverage_defect_blocks_eq(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            for side, condition in (
                ("old", "(assert (bvsge x (_ bv0 32)))\n"),
                ("new", "(assert (bvsle x (_ bv0 32)))\n"),
            ):
                (directory / f"symbolic_{side}V_path_1.txt").write_text(
                    SMT_HEADER + condition,
                    encoding="utf-8",
                )
                (directory / f"symbolic_{side}V_exploration.json").write_text(
                    verifier.json.dumps(
                        {
                            "complete": True,
                            "proof_eligible": True,
                            "incomplete_reasons": [],
                            "terminating_path_count": 1,
                            "active_count": 0,
                            "timeout_count": 0,
                            "loop_bound_event_count": 0,
                            "errored_count": 0,
                            "max_paths": 128,
                        }
                    ),
                    encoding="utf-8",
                )
            mismatch = {
                "direction": "old_domain_subset_new_domain",
                "status": "sat",
                "subset": False,
                "method": "smt_union_exclusion",
                "elapsed_seconds": 0.01,
                "witness_inputs": [
                    {
                        "name": "x",
                        "kind": "bitvec",
                        "bits": 32,
                        "value": 1,
                        "unsigned": 1,
                    }
                ],
                "witness_schema_complete": True,
            }
            no_mismatch = {
                "direction": "new_domain_subset_old_domain",
                "status": "unsat",
                "subset": True,
                "method": "smt_union_exclusion",
                "elapsed_seconds": 0.01,
                "witness_schema_complete": False,
            }
            audit = {
                "direction": "old_domain_subset_new_domain",
                "classification": "artifact_coverage_defect",
                "reason": "both_defined_with_identical_observables",
                "supports_neq": False,
                "definedness_confirmed": True,
                "witness_schema_complete": True,
                "witness_inputs": mismatch["witness_inputs"],
            }
            directional = {
                "success": True,
                "matching_complete": True,
                "semantic_checks_complete": True,
                "source_count": 1,
                "processed_source_count": 1,
                "coverage_status_counts": {"covered_exact": 1},
                "semantic_status_counts": {"all_equivalent": 1},
                "matched_targets": {"symbolic_newV_path_1"},
                "records": [],
                "smt_calls": 0,
                "t_smt": 0.0,
                "unknowns": 0,
                "matched_source_count": 1,
                "semantic_modes": {},
                "confirmed_mismatches": [],
            }
            with mock.patch.object(
                verifier,
                "program_domain_counterexample",
                return_value={"counterexample": None},
            ), mock.patch.object(
                verifier,
                "prescan_replayable_counterexample",
                return_value={
                    "mismatch": None,
                    "records": [],
                    "smt_calls": 0,
                    "t_smt": 0.0,
                    "semantic_modes": {},
                },
            ), mock.patch.object(
                verifier,
                "check_union_coverage_evidence",
                side_effect=[mismatch, no_mismatch],
            ), mock.patch.object(
                verifier,
                "audit_domain_witness",
                return_value=audit,
            ), mock.patch.object(
                verifier,
                "verify_directional_cover",
                return_value=directional,
            ):
                result = verifier.verify_ranked_queue(
                    directory,
                    None,
                    timeout_ms=1_000,
                    naive=True,
                    truth_pairs=None,
                    program_ground_truth=None,
                )

        self.assertEqual(result["verdict"], "UNK")
        self.assertEqual(
            result["failure_stage"],
            "domain_artifact_coverage_defect",
        )
        self.assertEqual(
            result["domain_artifact_coverage_defect_count"],
            1,
        )
        self.assertEqual(result["fast_path_branch"], "domain_witness_UNK")

    def test_domain_witness_replay_classifies_defined_and_signal_outcomes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = directory / "symbolic_oldV_path_1.txt"
            new = directory / "symbolic_newV_path_1.txt"
            old.write_text(SMT_HEADER, encoding="utf-8")
            new.write_text(SMT_HEADER, encoding="utf-8")
            evidence = {
                "direction": "old_domain_subset_new_domain",
                "witness_inputs": [
                    {
                        "name": "x",
                        "kind": "bitvec",
                        "bits": 32,
                        "value": 1,
                        "unsigned": 1,
                    }
                ],
                "witness_schema_complete": True,
            }
            cases = [
                (
                    {
                        "confirmed": True,
                        "reason": "observable_output_diff",
                        "left": {
                            "completed": True,
                            "returncode": 0,
                            "stdout": "1\n",
                            "stderr": "",
                        },
                        "right": {
                            "completed": True,
                            "returncode": 0,
                            "stdout": "2\n",
                            "stderr": "",
                        },
                    },
                    "observable_mismatch",
                    True,
                ),
                (
                    {
                        "confirmed": False,
                        "reason": "program_exit_nonzero",
                        "left": {
                            "completed": True,
                            "returncode": -11,
                            "stdout": "",
                            "stderr": "",
                        },
                        "right": {
                            "completed": True,
                            "returncode": 0,
                            "stdout": "ok\n",
                            "stderr": "",
                        },
                    },
                    "one_sided_ub_candidate",
                    False,
                ),
                (
                    {
                        "confirmed": False,
                        "reason": "no_observable_output_diff",
                        "left": {
                            "completed": True,
                            "returncode": 0,
                            "stdout": "ok\n",
                            "stderr": "",
                        },
                        "right": {
                            "completed": True,
                            "returncode": 0,
                            "stdout": "ok\n",
                            "stderr": "",
                        },
                    },
                    "artifact_coverage_defect",
                    False,
                ),
            ]
            for replay, classification, supports_neq in cases:
                with self.subTest(classification=classification):
                    with mock.patch.object(
                        verifier,
                        "replay_counterexample",
                        return_value=replay,
                    ):
                        audit = verifier.audit_domain_witness(
                            [old],
                            [new],
                            evidence,
                        )
                    self.assertEqual(
                        audit["classification"],
                        classification,
                    )
                    self.assertEqual(audit["supports_neq"], supports_neq)

    def test_exact_identity_requires_new_proof_eligibility_marker(self) -> None:
        record = {
            "complete": True,
            "incomplete_reasons": [],
            "terminating_path_count": 1,
            "active_count": 0,
            "timeout_count": 0,
            "loop_bound_event_count": 0,
            "errored_count": 0,
            "max_paths": 128,
        }
        self.assertFalse(
            verifier.exploration_is_complete(record, path_count=1)
        )
        record["proof_eligible"] = False
        self.assertFalse(
            verifier.exploration_is_complete(record, path_count=1)
        )
        record["proof_eligible"] = True
        self.assertTrue(
            verifier.exploration_is_complete(record, path_count=1)
        )

    def test_domain_mismatch_without_complete_schema_stays_unk(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            (directory / "symbolic_oldV_path_1.txt").write_text(
                SMT_HEADER + "(assert (bvsge x (_ bv0 32)))\n",
                encoding="utf-8",
            )
            (directory / "symbolic_newV_path_1.txt").write_text(
                SMT_HEADER + "(assert (bvsle x (_ bv0 32)))\n",
                encoding="utf-8",
            )
            for prefix in ("symbolic_oldV", "symbolic_newV"):
                (directory / f"{prefix}_exploration.json").write_text(
                    verifier.json.dumps(
                        {
                            "complete": True,
                            "proof_eligible": True,
                            "incomplete_reasons": [],
                            "terminating_path_count": 1,
                            "active_count": 0,
                            "timeout_count": 0,
                            "loop_bound_event_count": 0,
                            "errored_count": 0,
                            "max_paths": 128,
                        }
                    ),
                    encoding="utf-8",
                )
            mismatch_without_schema = {
                "direction": "old_domain_subset_new_domain",
                "status": "sat",
                "subset": False,
                "method": "smt_union_exclusion",
                "elapsed_seconds": 0.01,
                "witness_schema_complete": False,
                "witness_inputs": [],
            }
            unknown = {
                "direction": "new_domain_subset_old_domain",
                "status": "unknown",
                "subset": None,
                "method": "smt_union_exclusion",
                "elapsed_seconds": 0.01,
                "witness_schema_complete": False,
            }
            with mock.patch.object(
                verifier,
                "program_domain_counterexample",
                return_value={"counterexample": None, "reason": "not_found"},
            ), mock.patch.object(
                verifier,
                "prescan_replayable_counterexample",
                return_value={
                    "mismatch": None,
                    "records": [],
                    "smt_calls": 0,
                    "t_smt": 0.0,
                    "semantic_modes": {},
                },
            ), mock.patch.object(
                verifier,
                "check_union_coverage_evidence",
                side_effect=[mismatch_without_schema, unknown],
            ):
                result = verifier.verify_ranked_queue(
                    directory,
                    None,
                    timeout_ms=1_000,
                    naive=True,
                    truth_pairs=None,
                    program_ground_truth=True,
                )

        self.assertEqual(result["verdict"], "UNK")
        self.assertEqual(result["failure_stage"], "domain_witness_unconfirmed")

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

    def test_exact_path_bijection_rejects_different_global_smt(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(
                directory, "symbolic_oldV_path_1.txt", "(= x (_ bv1 32))"
            )
            new = self._path(
                directory, "symbolic_newV_path_1.txt", "(= x (_ bv1 32))"
            )
            common = {
                "return_value": {
                    "available": True,
                    "bits": 32,
                    "repr": "x",
                    "smt": SMT_HEADER
                    + "(declare-fun __return_value_1 () (_ BitVec 32))\n"
                    + "(assert (= __return_value_1 x))\n",
                },
                "program_output": {"available": True, "events": []},
            }
            old_summary = {
                **common,
                "global_state": {
                    "available": True,
                    "unresolved": [],
                    "regions": {
                        "global": {
                            "bits": 32,
                            "repr": "same-display-text",
                            "variable": "__global_0",
                            "smt": SMT_HEADER
                            + "(declare-fun __global_0 () (_ BitVec 32))\n"
                            + "(assert (= __global_0 (bvadd x (_ bv1 32))))\n",
                        }
                    },
                },
            }
            new_summary = {
                **common,
                "global_state": {
                    "available": True,
                    "unresolved": [],
                    "regions": {
                        "global": {
                            "bits": 32,
                            "repr": "same-display-text",
                            "variable": "__global_0",
                            "smt": SMT_HEADER
                            + "(declare-fun __global_0 () (_ BitVec 32))\n"
                            + "(assert (= __global_0 (bvsub x (_ bv1 32))))\n",
                        }
                    },
                },
            }
            for path, summary in ((old, old_summary), (new, new_summary)):
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(
                        "; Semantic summary JSON: "
                        + verifier.json.dumps(summary)
                        + "\n"
                    )
            self.assertIsNone(
                verifier.exact_path_bijection_proves_equivalence([old], [new])
            )

    def test_exact_path_bijection_accepts_canonical_formula_ast(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = directory / "symbolic_oldV_path_1.txt"
            new = directory / "symbolic_newV_path_1.txt"
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
            summary = {
                "return_value": {
                    "available": True,
                    "bits": 32,
                    "repr": "x",
                    "smt": SMT_HEADER
                    + "(declare-fun __return_value_1 () (_ BitVec 32))\n"
                    + "(assert (= __return_value_1 x))\n",
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
                    stream.write(
                        "; Semantic summary JSON: "
                        + verifier.json.dumps(summary)
                        + "\n"
                    )
            records = verifier.exact_path_bijection_proves_equivalence(
                [old],
                [new],
            )
            self.assertIsNotNone(records)
            self.assertEqual(
                records[0]["path_condition_identity"],
                "canonical_path_ast",
            )

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
            self.assertEqual(removed, [unsat_path.stem])
            self.assertEqual(unknown, [])

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

    def test_complete_matching_keeps_coverage_after_confirmed_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old_1 = self._path(directory, "symbolic_oldV_path_1.txt", "(= x (_ bv1 32))")
            old_2 = self._path(directory, "symbolic_oldV_path_2.txt", "(= x (_ bv2 32))")
            new_1 = self._path(directory, "symbolic_newV_path_1.txt", "(= x (_ bv1 32))")
            new_2 = self._path(directory, "symbolic_newV_path_2.txt", "(= x (_ bv2 32))")
            ranking = {
                "symbolic_oldV_path_1": ["symbolic_newV_path_1"],
                "symbolic_oldV_path_2": ["symbolic_newV_path_2"],
            }
            coverage = (True, 0.0, {
                "source_subset_targets": True,
                "targets_subset_source": True,
            })
            mismatch = (
                False,
                0.0,
                1,
                {
                    "input_overlap": "sat",
                    "semantic_mode": "test",
                    "replay": {"confirmed": True, "reason": "observable_output_diff"},
                },
            )
            equivalent = (
                True,
                0.0,
                1,
                {
                    "input_overlap": "sat",
                    "semantic_mode": "test",
                    "replay": {"confirmed": False, "reason": "no_observable_output_diff"},
                },
            )
            with mock.patch.object(
                verifier,
                "verify_path_overlap",
                return_value=(verifier.sat, 0.0),
            ), mock.patch.object(
                verifier,
                "check_path_union_equal",
                return_value=coverage,
            ), mock.patch.object(
                verifier,
                "verify_semantic_path_relation",
                side_effect=[mismatch, equivalent],
            ):
                result = verifier.verify_complete_directional_cover(
                    [old_1, old_2],
                    [new_1, new_2],
                    ranking,
                    1_000,
                    allow_one_to_many=True,
                )

            self.assertEqual(result["processed_source_count"], 2)
            self.assertEqual(len(result["records"]), 2)
            self.assertTrue(all(record["coverage_success"] for record in result["records"]))
            self.assertEqual(
                result["records"][0]["match_type"],
                "one_to_one_exact",
            )
            self.assertEqual(result["records"][0]["semantic_status"], "confirmed_mismatch")
            self.assertEqual(result["records"][1]["semantic_status"], "all_equivalent")
            self.assertEqual(len(result["confirmed_mismatches"]), 1)
            self.assertTrue(result["matching_complete"])
            self.assertTrue(result["semantic_checks_complete"])
            self.assertFalse(result["success"])

    def test_complete_mode_disables_program_level_fast_exits(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            paths_dir = Path(raw_dir)
            for prefix in ("symbolic_oldV", "symbolic_newV"):
                (paths_dir / f"{prefix}_path_1.txt").write_text(
                    SMT_HEADER + "(assert (= x (_ bv1 32)))\n",
                    encoding="utf-8",
                )
                (paths_dir / f"{prefix}_exploration.json").write_text(
                    verifier.json.dumps(
                        {
                            "complete": True,
                            "proof_eligible": True,
                            "incomplete_reasons": [],
                            "terminating_path_count": 1,
                            "active_count": 0,
                            "timeout_count": 0,
                            "loop_bound_event_count": 0,
                            "errored_count": 0,
                            "max_paths": 128,
                        }
                    ),
                    encoding="utf-8",
                )
            directional = {
                "success": True,
                "covered": True,
                "matching_complete": True,
                "semantic_checks_complete": True,
                "semantic_all_equivalent": True,
                "source_count": 1,
                "processed_source_count": 1,
                "coverage_status_counts": {"covered_exact": 1},
                "semantic_status_counts": {"all_equivalent": 1},
                "matched_targets": {"symbolic_newV_path_1"},
                "records": [
                    {
                        "query": "symbolic_oldV_path_1",
                        "match": "symbolic_newV_path_1",
                        "matched": True,
                        "coverage_success": True,
                        "matching_complete": True,
                        "match_type": "one_to_one_exact",
                        "semantic_status": "all_equivalent",
                        "semantic_checks_complete": True,
                        "source_subset_targets": True,
                        "semantic_checks": [{"target": "symbolic_newV_path_1", "equivalent": True}],
                    }
                ],
                "smt_calls": 1,
                "t_smt": 0.0,
                "unknowns": 0,
                "matched_source_count": 1,
                "semantic_modes": {},
                "confirmed_mismatches": [],
            }
            reverse_directional = verifier.json.loads(verifier.json.dumps(
                {key: value for key, value in directional.items() if key != "matched_targets"}
            ))
            reverse_directional["matched_targets"] = {"symbolic_oldV_path_1"}
            reverse_record = reverse_directional["records"][0]
            reverse_record.update(query="symbolic_newV_path_1", match="symbolic_oldV_path_1")
            reverse_record["semantic_checks"][0]["target"] = "symbolic_oldV_path_1"
            with mock.patch.object(
                verifier,
                "exact_path_bijection_proves_equivalence",
                wraps=verifier.exact_path_bijection_proves_equivalence,
            ) as exact_fast_path, mock.patch.object(
                verifier,
                "prescan_replayable_counterexample",
            ) as prescan, mock.patch.object(
                verifier,
                "program_domain_counterexample",
            ) as domain_prescan, mock.patch.object(
                verifier,
                "verify_complete_directional_cover",
                side_effect=[directional, reverse_directional],
            ), mock.patch.object(
                verifier,
                "check_union_coverage",
                return_value=(True, 0.0),
            ), mock.patch.object(
                verifier,
                "filter_definitely_unsat_paths",
            ) as feasibility_filter:
                result = verifier.verify_ranked_queue(
                    paths_dir,
                    None,
                    timeout_ms=1_000,
                    naive=True,
                    truth_pairs=None,
                    program_ground_truth=True,
                    complete_matching=True,
                )

            exact_fast_path.assert_not_called()
            prescan.assert_not_called()
            domain_prescan.assert_not_called()
            feasibility_filter.assert_not_called()
            self.assertEqual(result["verdict"], "EQ")
            self.assertEqual(result["analysis_mode"], "complete_path_matching")
            self.assertFalse(result["exact_fast_path_enabled"])
            self.assertFalse(result["domain_counterexample_prescan_enabled"])
            self.assertEqual(result["exact_fast_path_synthetic_records"], 0)
            self.assertEqual(result["prescan_invocations"], 0)
            self.assertEqual(result["forward_processed_source_count"], 1)
            self.assertEqual(result["reverse_processed_source_count"], 1)

    def test_normal_mode_uses_stable_domain_replay_before_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(
                directory,
                "symbolic_oldV_path_1.txt",
                "(bvsge x (_ bv0 32))",
            )
            new = self._path(
                directory,
                "symbolic_newV_path_1.txt",
                "(bvsle x (_ bv0 32))",
            )
            for side in ("old", "new"):
                (directory / f"symbolic_{side}V_exploration.json").write_text(
                    verifier.json.dumps(
                        {
                            "complete": True,
                            "proof_eligible": True,
                            "incomplete_reasons": [],
                            "terminating_path_count": 1,
                            "active_count": 0,
                            "timeout_count": 0,
                            "loop_bound_event_count": 0,
                            "errored_count": 0,
                            "max_paths": 128,
                        }
                    ),
                    encoding="utf-8",
                )
            mismatch = {
                "source": old.stem,
                "target": new.stem,
                "rank": 1,
                "counterexample": {
                    "inputs": [
                        {
                            "name": "x",
                            "kind": "bitvec",
                            "bits": 32,
                            "value": 0,
                        }
                    ]
                },
                "replay": {
                    "confirmed": True,
                    "reason": "observable_output_diff",
                },
                "counterexample_source": "standard_domain_seed_replay",
                "seeds_tested": 1,
                "seeds_available": 8,
                "observations": [],
            }
            with mock.patch.object(
                verifier,
                "program_domain_counterexample",
                return_value=mismatch,
            ), mock.patch.object(
                verifier,
                "check_union_coverage",
            ) as coverage:
                result = verifier.verify_ranked_queue(
                    directory,
                    None,
                    timeout_ms=1_000,
                    naive=True,
                    truth_pairs=None,
                    program_ground_truth=True,
                )

            coverage.assert_not_called()
            self.assertEqual(result["verdict"], "NEQ")
            self.assertEqual(result["fast_path_branch"], "standard_domain_seed_replay")
            self.assertEqual(result["domain_prescan_invocations"], 1)
            self.assertEqual(result["confirmed_counterexample_count"], 1)
            self.assertEqual(result["t_align"], 0.0)

    def test_program_domain_counterexample_tries_standard_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = directory / "symbolic_oldV_path_1.txt"
            new = directory / "symbolic_newV_path_1.txt"
            formula = (
                "(set-info :status unknown)\n"
                "(declare-fun arg_0 () (_ BitVec 32))\n"
                "(assert (bvsge arg_0 (_ bv0 32)))\n"
            )
            old.write_text(formula, encoding="utf-8")
            new.write_text(formula, encoding="utf-8")
            replay_results = [
                {
                    "confirmed": False,
                    "reason": "no_observable_output_diff",
                },
                {
                    "confirmed": True,
                    "reason": "observable_output_diff",
                },
            ]
            with mock.patch.object(
                verifier,
                "replay_counterexample",
                side_effect=replay_results,
            ):
                result = verifier.program_domain_counterexample([old], [new])

            self.assertIsNotNone(result["counterexample"])
            self.assertEqual(result["seeds_tested"], 2)
            self.assertGreaterEqual(result["seeds_available"], 2)
            self.assertTrue(result["replay"]["confirmed"])

    def test_complete_matching_marks_unknown_coverage_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(
                directory,
                "symbolic_oldV_path_1.txt",
                "(bvsge x (_ bv0 32))",
            )
            new = self._path(
                directory,
                "symbolic_newV_path_1.txt",
                "(bvsle x (_ bv0 32))",
            )
            with mock.patch.object(
                verifier,
                "verify_path_overlap",
                return_value=(verifier.sat, 0.0),
            ), mock.patch.object(
                verifier,
                "check_path_union_equal",
                return_value=(
                    None,
                    0.0,
                    {
                        "source_subset_targets": None,
                        "targets_subset_source": None,
                    },
                ),
            ), mock.patch.object(
                verifier,
                "verify_semantic_path_relation",
            ) as semantic:
                result = verifier.verify_complete_directional_cover(
                    [old],
                    [new],
                    {"symbolic_oldV_path_1": ["symbolic_newV_path_1"]},
                    1_000,
                )

            semantic.assert_not_called()
            self.assertFalse(result["matching_complete"])
            self.assertEqual(
                result["coverage_status_counts"].get("coverage_unknown"),
                1,
            )
            self.assertEqual(result["records"][0]["coverage_status"], "coverage_unknown")
            self.assertGreater(result["unknowns"], 0)

    def test_global_fallback_uses_zero_sign_insensitive_comparison(self) -> None:
        left = {
            "global_state": {
                "available": True,
                "unresolved": [],
                "objects": {
                    "alpha": {
                        "available": True,
                        "bits": 64,
                        "variable": "__global_0",
                        "repr": "<BV64 fpToIEEEBV(FPV(0, DOUBLE))>",
                        "smt": "(declare-fun __global_0 () (_ BitVec 64))\n"
                        "(assert (= __global_0 (_ bv0 64)))\n",
                    }
                },
            }
        }
        right = {
            "global_state": {
                "available": True,
                "unresolved": [],
                "objects": {
                    "beta": {
                        "available": True,
                        "bits": 64,
                        "variable": "__global_1",
                        "repr": "<BV64 fpToIEEEBV(FPV(0, DOUBLE))>",
                        "smt": "(declare-fun __global_1 () (_ BitVec 64))\n"
                        "(assert (= __global_1 (_ bv9223372036854775808 64)))\n",
                    }
                },
            }
        }

        equivalent, _elapsed, _calls, mapping = verifier.verify_global_state_equivalence(
            left,
            right,
            2_000,
        )

        self.assertTrue(equivalent)
        self.assertEqual(mapping["method"], "sorted_position_fallback")
        self.assertTrue(mapping["fallback_used"])

    def test_return_float_zero_is_equal_but_nonzero_is_not(self) -> None:
        smt_header = "(declare-fun __return_value () (_ BitVec 64))\n"
        positive_zero = {
            "available": True,
            "bits": 64,
            "repr": "<BV64 fpToIEEEBV(FPV(0, DOUBLE))>",
            "smt": smt_header + "(assert (= __return_value (_ bv0 64)))\n",
        }
        negative_zero = {
            "available": True,
            "bits": 64,
            "repr": "<BV64 fpToIEEEBV(FPV(0, DOUBLE))>",
            "smt": smt_header
            + "(assert (= __return_value (_ bv9223372036854775808 64)))\n",
        }
        positive_one = {
            "available": True,
            "bits": 64,
            "repr": "<BV64 fpToIEEEBV(FPV(1, DOUBLE))>",
            "smt": smt_header + "(assert (= __return_value (_ bv4607182418800017408 64)))\n",
        }

        zero_equal, _elapsed, _calls = verifier.verify_return_smt_equivalence(
            positive_zero,
            negative_zero,
            2_000,
        )
        nonzero_equal, _elapsed, _calls = verifier.verify_return_smt_equivalence(
            positive_zero,
            positive_one,
            2_000,
        )

        self.assertTrue(zero_equal)
        self.assertFalse(nonzero_equal)

    def test_expression_signature_keeps_internal_zero_sign(self) -> None:
        ctx = Context()
        sort = FPSort(11, 53, ctx=ctx)
        positive_zero = FPVal(0.0, sort, ctx=ctx)
        negative_zero = FPVal(-0.0, sort, ctx=ctx)
        self.assertNotEqual(
            verifier._canonical_expr_signature(
                positive_zero,
                definition_variable="unused",
            ),
            verifier._canonical_expr_signature(
                negative_zero,
                definition_variable="unused",
            ),
        )

    def test_replay_ignores_zero_sign_only_for_known_float_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = directory / "symbolic_oldV_path_1.txt"
            new = directory / "symbolic_newV_path_1.txt"
            summary = {
                "program_output": {
                    "available": True,
                    "unresolved": [],
                    "events": [
                        {
                            "sink": "stdout",
                            "segments": [
                                {"kind": "text", "value": "Result: "},
                                {
                                    "kind": "formatted_value",
                                    "available": True,
                                    "specifier": "%a",
                                    "bits": 64,
                                    "variable": "__output_0",
                                    "repr": "<BV64 fpToIEEEBV(FPS(arg_0, DOUBLE))>",
                                    "smt": "(declare-fun __output_0 () (_ BitVec 64))\n"
                                    "(assert (= __output_0 (_ bv0 64)))\n",
                                },
                                {"kind": "text", "value": "\n"},
                            ],
                        }
                    ],
                }
            }
            for path in (old, new):
                path.write_text(
                    SMT_HEADER
                    + "; Semantic summary JSON: "
                    + verifier.json.dumps(summary)
                    + "\n",
                    encoding="utf-8",
                )
            negative = {
                "completed": True,
                "returncode": 0,
                "stdout": "Result: -0x0p+0\n",
                "stderr": "",
            }
            positive = {
                "completed": True,
                "returncode": 0,
                "stdout": "Result: 0x0p+0\n",
                "stderr": "",
            }
            with mock.patch.object(
                verifier,
                "binary_for_path",
                side_effect=[Path("old"), Path("new")],
            ), mock.patch.object(
                verifier,
                "run_binary",
                side_effect=[negative, negative, positive, positive],
            ):
                replay = verifier.replay_counterexample(
                    old,
                    new,
                    {
                        "inputs": [
                            {
                                "name": "FP_arg_0",
                                "kind": "float",
                                "bits": 64,
                                "value": 0.0,
                            }
                        ]
                    },
                )

            self.assertFalse(replay["confirmed"])
            self.assertTrue(
                replay["comparison"]["float_zero_sign_insensitive"]
            )

    def test_replay_without_output_metadata_normalizes_signed_zero(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = directory / "symbolic_oldV_path_1.txt"
            new = directory / "symbolic_newV_path_1.txt"
            for path in (old, new):
                path.write_text(
                    SMT_HEADER + "(assert (= x (_ bv0 32)))\n",
                    encoding="utf-8",
                )
            negative = {
                "completed": True,
                "returncode": 0,
                "stdout": "Result: -0x0p+0\n",
                "stderr": "",
            }
            positive = {
                "completed": True,
                "returncode": 0,
                "stdout": "Result: 0x0p+0\n",
                "stderr": "",
            }
            with mock.patch.object(
                verifier,
                "binary_for_path",
                side_effect=[Path("old"), Path("new")],
            ), mock.patch.object(
                verifier,
                "run_binary",
                side_effect=[negative, negative, positive, positive],
            ):
                replay = verifier.replay_counterexample(
                    old,
                    new,
                    {
                        "inputs": [
                            {
                                "name": "x",
                                "kind": "bitvec",
                                "bits": 32,
                                "value": 0,
                                "unsigned": 0,
                            }
                        ]
                    },
                )

        self.assertFalse(replay["confirmed"])
        self.assertEqual(
            replay["comparison"]["stdout"]["method"],
            "text_numeric_zero_normalization",
        )
        self.assertTrue(
            replay["comparison"]["float_zero_sign_insensitive"]
        )

    def test_replay_still_detects_positive_vs_negative_infinity(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = directory / "symbolic_oldV_path_1.txt"
            new = directory / "symbolic_newV_path_1.txt"
            summary = {
                "program_output": {
                    "available": True,
                    "unresolved": [],
                    "events": [
                        {
                            "sink": "stdout",
                            "segments": [
                                {
                                    "kind": "formatted_value",
                                    "available": True,
                                    "specifier": "%a",
                                    "bits": 64,
                                    "variable": "__output_0",
                                    "repr": "<BV64 fpToIEEEBV(FPS(arg_0, DOUBLE))>",
                                    "smt": "(declare-fun __output_0 () (_ BitVec 64))\n",
                                },
                                {"kind": "text", "value": "\n"},
                            ],
                        }
                    ],
                }
            }
            for path in (old, new):
                path.write_text(
                    SMT_HEADER
                    + "; Semantic summary JSON: "
                    + verifier.json.dumps(summary)
                    + "\n",
                    encoding="utf-8",
                )
            positive_inf = {
                "completed": True,
                "returncode": 0,
                "stdout": "inf\n",
                "stderr": "",
            }
            negative_inf = {
                "completed": True,
                "returncode": 0,
                "stdout": "-inf\n",
                "stderr": "",
            }
            with mock.patch.object(
                verifier,
                "binary_for_path",
                side_effect=[Path("old"), Path("new")],
            ), mock.patch.object(
                verifier,
                "run_binary",
                side_effect=[
                    positive_inf,
                    positive_inf,
                    negative_inf,
                    negative_inf,
                ],
            ):
                replay = verifier.replay_counterexample(
                    old,
                    new,
                    {
                        "inputs": [
                            {
                                "name": "FP_arg_0",
                                "kind": "float",
                                "bits": 64,
                                "value": 1.0,
                            }
                        ]
                    },
                )

            self.assertTrue(replay["confirmed"])
            self.assertEqual(replay["reason"], "observable_output_diff")


class SignedZeroStructuredOutputTests(unittest.TestCase):
    def test_structured_layout_with_missing_float_type_normalizes_zero_sign(
        self,
    ) -> None:
        summary = {
            "program_output": {
                "events": [
                    {
                        "segments": [
                            {"kind": "text", "value": "Result: ", "sink": "stdout"},
                            {
                                "kind": "formatted_value",
                                "specifier": "",
                                "bits": 0,
                                "sink": "stdout",
                            },
                        ]
                    }
                ]
            }
        }
        equal, comparison = verifier.replay_streams_equivalent(
            summary,
            summary,
            "Result: -0x0.0p+0\n",
            "Result: 0x0.0p+0\n",
            sink="stdout",
        )
        self.assertTrue(equal)
        self.assertTrue(comparison["zero_sign_normalization"])

    def test_empty_output_layout_still_normalizes_signed_zero(self) -> None:
        summary = {
            "program_output": {
                "events": [
                    {
                        "segments": [],
                    }
                ]
            }
        }
        equal, comparison = verifier.replay_streams_equivalent(
            summary,
            summary,
            "Result: -0x0p+0\n",
            "Result: 0x0p+0\n",
            sink="stdout",
        )
        self.assertTrue(equal)
        self.assertEqual(
            comparison["method"],
            "text_numeric_zero_normalization",
        )
        self.assertTrue(comparison["zero_sign_normalization"])


class FailureClassificationTests(unittest.TestCase):
    def test_unknown_without_existing_reason_gets_a_primary_reason(self) -> None:
        result = verifier.attach_failure_classification(
            {
                "verdict": "UNK",
                "failure_stage": "matching_incomplete",
                "artifact_status": "incomplete_or_lossy",
                "eq_proof_eligible": False,
                "semantic_model_neq_eligible": False,
            }
        )
        self.assertEqual(result["failure_reason"], "matching_incomplete")
        classification = result["failure_classification"]
        self.assertEqual(classification["semantic_verdict"], "UNK")
        self.assertEqual(
            classification["artifact_completeness"],
            "incomplete_or_lossy",
        )
        self.assertEqual(
            classification["primary_reason"],
            "matching_incomplete",
        )

    def test_completed_candidate_inputs_revalidate_original_query(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            query = Path(raw) / "query.smt2"
            query.write_text(
                "(set-logic QF_BV)\n"
                "(declare-const arg_0 (_ BitVec 32))\n"
                "(assert (= arg_0 #x00000001))\n"
                "(check-sat)\n",
                encoding="utf-8",
            )
            counterexample = {
                "_candidate_checkpoint": {"query_path": str(query)}
            }
            matching = verifier.revalidate_completed_counterexample_query(
                counterexample,
                [
                    {
                        "name": "arg_0",
                        "kind": "bitvec",
                        "bits": 32,
                        "unsigned": 1,
                    }
                ],
            )
            mismatching = verifier.revalidate_completed_counterexample_query(
                counterexample,
                [
                    {
                        "name": "arg_0",
                        "kind": "bitvec",
                        "bits": 32,
                        "unsigned": 2,
                    }
                ],
            )
        self.assertEqual(matching["status"], "sat")
        self.assertEqual(mismatching["status"], "unsat")


if __name__ == "__main__":
    unittest.main()

