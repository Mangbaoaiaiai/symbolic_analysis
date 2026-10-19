import json
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_paper_eval import load_generated_and_failures


class SummarizePaperEvalTests(unittest.TestCase):
    def test_supplement_only_fills_missing_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            primary = root / "primary"
            supplemental = root / "supplemental"
            primary.mkdir()
            supplemental.mkdir()
            (primary / "manifest.json").write_text(
                json.dumps(
                    {
                        "pairs": [
                            {
                                "pair_id": "Fam/Shared_Eq",
                                "subset": "fam",
                                "program": "Shared_Eq",
                                "ground_truth": True,
                            }
                        ],
                        "failures": [
                            {"case": "ell/plgndr/Eq", "error": "timeout"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (supplemental / "manifest.json").write_text(
                json.dumps(
                    {
                        "pairs": [
                            {
                                "pair_id": "Fam/Shared_Eq",
                                "subset": "replacement",
                                "program": "Wrong",
                                "ground_truth": True,
                            },
                            {
                                "pair_id": "ell/plgndr_Eq",
                                "subset": "ell",
                                "program": "plgndr_Eq",
                                "ground_truth": True,
                            },
                        ],
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )
            generated, failures = load_generated_and_failures([primary, supplemental])
            self.assertEqual(generated["fam/shared_eq"]["subset"], "fam")
            self.assertEqual(generated["ell/plgndr_eq"]["subset"], "ell")
            self.assertEqual(failures["ell/plgndr_eq"], "timeout")


if __name__ == "__main__":
    unittest.main()
