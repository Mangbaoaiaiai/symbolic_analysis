from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_suite import resolve_run_names


class RunNameTests(unittest.TestCase):
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
