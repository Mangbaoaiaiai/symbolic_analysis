import unittest

from scripts.summarize_paper_subset import canonical_case_id
from scripts.summarize_paper_eval import classify, failure_case_id


class PaperSubsetTests(unittest.TestCase):
    def test_moddiff_and_osf_clever_names_share_a_key(self) -> None:
        self.assertEqual(
            canonical_case_id("ModDiff/Add_Eq"),
            canonical_case_id("CLEVER/Add_Eq"),
        )

    def test_negative_labels_are_case_insensitive(self) -> None:
        self.assertEqual(
            canonical_case_id("Ran/gammln_NEq"),
            canonical_case_id("ran/gammln_Neq"),
        )

    def test_pow_and_power_names_share_a_key(self) -> None:
        self.assertEqual(
            canonical_case_id("power/test_Eq"),
            canonical_case_id("pow/test_Eq"),
        )

    def test_classify_detects_false_verdicts(self) -> None:
        self.assertEqual(classify("EQ", True), "correct_eq")
        self.assertEqual(classify("EQ", False), "wrong_eq")
        self.assertEqual(classify("NEQ", True), "wrong_neq")
        self.assertEqual(classify("UNK", False), "unk")

    def test_path_failure_maps_to_candidate_id(self) -> None:
        self.assertEqual(failure_case_id("ell/rc/Eq"), "ell/rc_eq")


if __name__ == "__main__":
    unittest.main()
