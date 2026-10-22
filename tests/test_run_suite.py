from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_suite import (
    generated_pair_count,
    manifest_record_count,
    resolve_run_names,
)


class RunNameTests(unittest.TestCase):
    def test_generated_pair_count_handles_empty_shards(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            self.assertEqual(generated_pair_count(root), 0)
            (root / "manifest.json").write_text(
                json.dumps({"pairs": []}),
                encoding="utf-8",
            )
            self.assertEqual(generated_pair_count(root), 0)
            (root / "manifest.json").unlink()
            (root / "manifest.partial.json").write_text(
                json.dumps({"pairs": [{"pair_id": "a/b_Eq"}]}),
                encoding="utf-8",
            )
            self.assertEqual(generated_pair_count(root), 1)

    def test_manifest_record_count_handles_missing_subset_and_bom(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "cases.csv"
            self.assertEqual(manifest_record_count(path), 0)
            path.write_text(
                "\ufeffcase_id,label\na/b_Eq,EQ\na/c_NEq,NEQ\n",
                encoding="utf-8",
            )
            self.assertEqual(manifest_record_count(path), 2)

    def test_single_suites_default_to_their_own_names(self) -> None:
        self.assertEqual(resolve_run_names("paper", None), ("paper", "paper"))
        self.assertEqual(resolve_run_names("osf", None), ("osf", "osf"))

    def test_single_suite_uses_the_explicit_name_verbatim(self) -> None:
        self.assertEqual(resolve_run_names("paper", "audit"), ("audit", "audit"))
        self.assertEqual(resolve_run_names("osf", "audit"), ("audit", "audit"))

    def test_combined_suite_never_collides(self) -> None:
        self.assertEqual(resolve_run_names("all", None), ("paper", "osf"))
        self.assertEqual(
            resolve_run_names("all", "audit"),
            ("audit_paper", "audit_osf"),
        )


if __name__ == "__main__":
    unittest.main()
