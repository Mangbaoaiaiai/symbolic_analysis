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

    def test_one_to_one_requires_bidirectional_input_domain_equality(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old = self._path(
                directory,
                "symbolic_oldV_path_1.txt",
                "(= x (_ bv0 32))",
            )
            new = self._path(
                directory,
                "symbolic_newV_path_1.txt",
                "(and (bvsge x (_ bv0 32)) (bvsle x (_ bv1 32)))",
            )
            ranking = {"symbolic_oldV_path_1": ["symbolic_newV_path_1"]}
            semantic_match = (
                True,
                0.0,
                1,
                {"input_overlap": "sat"},
            )
            with mock.patch.object(
                verifier,
                "verify_semantic_path_relation",
                return_value=semantic_match,
            ):
                strict = verifier.verify_directional_cover(
                    [old],
                    [new],
                    ranking,
                    5_000,
                    allow_one_to_many=False,
                )
                union_allowed = verifier.verify_directional_cover(
                    [old],
                    [new],
                    ranking,
                    5_000,
                    allow_one_to_many=True,
                )

        self.assertFalse(strict["records"][0]["matched"])
        self.assertTrue(union_allowed["records"][0]["matched"])
        self.assertTrue(
            union_allowed["records"][0]["intersection_verified"]
        )

    def test_strict_one_to_one_rejects_target_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            old_a = self._path(
                directory,
                "symbolic_oldV_path_1.txt",
                "(= x (_ bv0 32))",
            )
            old_b = self._path(
                directory,
                "symbolic_oldV_path_2.txt",
                "(= x (_ bv0 32))",
            )
            new = self._path(
                directory,
                "symbolic_newV_path_1.txt",
                "(= x (_ bv0 32))",
            )
            ranking = {
                "symbolic_oldV_path_1": ["symbolic_newV_path_1"],
                "symbolic_oldV_path_2": ["symbolic_newV_path_1"],
            }
            semantic_match = (
                True,
                0.0,
                1,
                {"input_overlap": "sat"},
            )
            with mock.patch.object(
                verifier,
                "verify_semantic_path_relation",
                return_value=semantic_match,
            ):
                strict = verifier.verify_directional_cover(
                    [old_a, old_b],
                    [new],
                    ranking,
                    5_000,
                    allow_one_to_many=False,
                )

        self.assertEqual(
            [record["matched"] for record in strict["records"]],
            [True, False],
        )
        self.assertEqual(strict["records"][0]["match_type"], "one_to_one_exact")

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
                    + "(declare-fun __return_value () (_ BitVec 32))\n"
                    + "(assert (= __return_value x))\n",
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

    def test_exact_path_bijection_rejects_nonidentical_formula_text(self) -> None:
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
            self.assertIsNone(
                verifier.exact_path_bijection_proves_equivalence([old], [new])
            )

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

    def test_malformed_global_smt_cannot_use_identity_shortcut(self) -> None:
        state = {
            "available": True,
            "regions": {
                "g:0:32": {
                    "bits": 32,
                    "variable": "__global_0",
                    "smt": "(declare-fun __global_0 () (_ BitVec 32)) (assert",
                }
            },
        }
        self.assertFalse(
            verifier.global_regions_identical(state, state)
        )

    def test_global_mapping_records_layout_and_ast_candidates(self) -> None:
        content = {"sha256": "same-initial-content"}
        left = {
            "left@0x0:8": {
                "object": "left",
                "offset": 0,
                "size_bytes": 8,
                "bits": 64,
                "section": ".data",
                "initial_content_sha256": content,
                "variable": "__global_left",
                "smt": """(declare-fun __global_left_1_64 () (_ BitVec 64))
(assert (= (_ bv0 64) __global_left_1_64))
""",
            }
        }
        right = {
            "right@0x0:8": {
                "object": "right",
                "offset": 0,
                "size_bytes": 8,
                "bits": 64,
                "section": ".data",
                "initial_content_sha256": content,
                "variable": "__global_right",
                "smt": """(declare-fun __global_right_1_64 () (_ BitVec 64))
(assert (= (_ bv0 64) __global_right_1_64))
""",
            }
        }
        pairs, evidence = verifier.map_global_regions_with_evidence(
            left, right
        )
        self.assertIsNotNone(pairs)
        self.assertIn("layout_content", evidence["methods"])
        self.assertGreaterEqual(
            evidence["candidate_evidence"]["layout_content_candidates"], 1
        )
        self.assertGreaterEqual(
            evidence["candidate_evidence"]["ast_context_candidates"], 1
        )

    def test_ast_only_duplicate_candidates_remain_ambiguous(self) -> None:
        def cell(name: str, value: int, offset: int) -> dict[str, object]:
            variable = f"__global_{name}"
            return {
                "object": name,
                "offset": offset,
                "size_bytes": 8,
                "bits": 64,
                "section": ".data",
                "variable": variable,
                "smt": (
                    f"(declare-fun {variable}_1_64 () (_ BitVec 64))\n"
                    f"(assert (= (_ bv{value} 64) {variable}_1_64))\n"
                ),
            }

        left = {
            f"{name}@0x0:8": cell(name, 0, offset)
            for name, offset in (("a", 0), ("b", 8))
        }
        right = {
            f"{name}@0x0:8": cell(name, 0, offset)
            for name, offset in (("c", 0), ("d", 8))
        }
        _pairs, evidence = verifier.map_global_regions_with_evidence(
            left, right
        )
        self.assertGreaterEqual(
            evidence["candidate_evidence"]["ast_context_candidates"], 4
        )
        self.assertGreaterEqual(
            evidence["candidate_evidence"]["ambiguous_ast_candidates"], 2
        )

    def test_standard_seed_replay_detects_observable_neq(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            paths = root / "case" / "paths"
            binaries = root / "case" / "bin"
            paths.mkdir(parents=True)
            binaries.mkdir(parents=True)
            old = paths / "symbolic_oldV_path_1.txt"
            new = paths / "symbolic_newV_path_1.txt"
            old.write_text("(assert true)\n", encoding="utf-8")
            new.write_text("(assert true)\n", encoding="utf-8")
            for name, output in (
                ("symbolic_oldV", "old"),
                ("symbolic_newV", "new"),
            ):
                executable = binaries / name
                executable.write_text(
                    f"#!/bin/sh\ncat >/dev/null\necho {output}\n",
                    encoding="utf-8",
                )
                executable.chmod(0o755)
            verifier._STANDARD_SEED_REPLAY_CACHE.clear()
            result = verifier.replay_standard_inputs(
                old,
                new,
                (("arg_0", "bitvec", 32, 0),),
            )
            self.assertIsNotNone(result)
            self.assertTrue(result["replay"]["confirmed"])

    def test_backend_mangled_global_variable_is_equivalent(self) -> None:
        smt = """(set-info :status unknown)
(declare-fun __global_counter_0_0x0_1_10_8 () (_ BitVec 8))
(assert (= (_ bv0 8) __global_counter_0_0x0_1_10_8))
"""
        state = {
            "available": True,
            "regions": {
                "counter@0x0:1": {
                    "available": True,
                    "bits": 8,
                    "variable": "__global_counter_0_0x0_1",
                    "smt": smt,
                }
            },
        }
        self.assertTrue(
            verifier.global_regions_identical(state, state)
        )
        equivalent, _elapsed, _calls, _mapping = (
            verifier.verify_global_state_equivalence(
                {"global_state": state},
                {"global_state": state},
                1_000,
            )
        )
        self.assertTrue(equivalent)

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


class ReplayInputTests(unittest.TestCase):
    def test_partial_model_is_completed_from_path_signature(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            left = directory / "symbolic_oldV_path_1.txt"
            right = directory / "symbolic_newV_path_1.txt"
            signature = (
                "; Symbolic variable values: "
                "{'arg_0': 1, 'arg_1': 2, 'arg_2': 3, 'arg_3': 4}\n"
            )
            left.write_text(SMT_HEADER + signature, encoding="utf-8")
            right.write_text(SMT_HEADER + signature, encoding="utf-8")
            supplied = [
                {
                    "name": "arg_0_0_32",
                    "kind": "bitvec",
                    "bits": 32,
                    "value": 9,
                    "unsigned": 9,
                }
            ]

            completed = verifier.complete_replay_inputs(left, right, supplied)

            self.assertEqual([item["value"] for item in completed], [9, 2, 3, 4])
            self.assertEqual(completed[0], supplied[0])

    def test_signed_nan_stdout_is_an_abstract_observable_equal(self) -> None:
        self.assertTrue(
            verifier.replay_observables_equal(
                {"returncode": 0, "stdout": "Result: nan\n", "stderr": ""},
                {"returncode": 0, "stdout": "Result: -nan\n", "stderr": ""},
            )
        )
        self.assertFalse(
            verifier.replay_observables_equal(
                {"returncode": 0, "stdout": "Result: nan\n", "stderr": ""},
                {"returncode": 0, "stdout": "Result: 0x0p+0\n", "stderr": ""},
            )
        )

    def test_verifier_profile_uses_recorded_full_input_ranges(self) -> None:
        profile = verifier.profile_from_exploration(
            {
                "symbolic_oldV": {
                    "input_ranges": {
                        "integer": "unbounded",
                        "floating_point": "unbounded",
                    }
                }
            }
        )
        execution = profile["symbolic_execution"]
        self.assertEqual(
            execution["integer_domain"],
            "full_representable_input_space",
        )
        self.assertEqual(
            execution["floating_point_domain"],
            "full_representable_input_space",
        )


if __name__ == "__main__":
    unittest.main()

