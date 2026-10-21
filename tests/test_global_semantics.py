from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import se_script_improved
import verify_ranked_path_equivalence as verifier


@unittest.skipUnless(shutil.which("gcc"), "gcc is required")
class GlobalSemanticsTests(unittest.TestCase):
    def _run_version(self, root: Path, name: str, assignment: str):
        source = root / f"{name}.c"
        binary = root / name
        source.write_text(
            "int g;\n"
            "int h = 7;\n"
            f"int snippet(int x) {{ if (x > 0) {{ {assignment} }} return 0; }}\n"
            "int main(void) { return snippet(0); }\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                "gcc",
                "-O0",
                "-g",
                "-fno-pie",
                "-no-pie",
                "-o",
                str(binary),
                str(source),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        paths_dir = root / f"{name}_paths"
        analyzer = se_script_improved.BenchmarkSymbolicExecution(
            str(binary),
            str(paths_dir / f"symbolic_{name}V"),
            timeout=15,
            snippet_signature="int(int)",
            loop_bound=30,
            max_paths=10,
            int_min=0,
            int_max=1,
        )
        paths = analyzer.run_symbolic_execution()
        return paths_dir, paths

    def test_global_snapshot_includes_unwritten_objects_and_declared_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            paths_dir, paths = self._run_version(root, "old", "g = 1;")
            self.assertEqual(len(paths), 2)
            for path in paths:
                state = path["semantic_summary"]["global_state"]
                self.assertTrue(state["available"], state.get("unresolved"))
                self.assertIn("g", {item["object"] for item in state["regions"].values()})
                self.assertIn("h", {item["object"] for item in state["regions"].values()})
                for cell in state["regions"].values():
                    self.assertIn("size_bytes", cell)
                memory = path["semantic_summary"]["memory_state"]
                for write in memory["writes"]:
                    self.assertIsInstance(write["size_bits"], int)
                    self.assertIsInstance(write["size_bytes"], int)
            manifest = (paths_dir / "symbolic_oldV_exploration.json").read_text(
                encoding="utf-8"
            )
            self.assertIn('"schema": "symbolicana.exploration.v3"', manifest)

    def test_global_difference_without_replay_stays_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            old_dir, old_paths = self._run_version(root, "old", "g = 1;")
            new_dir, new_paths = self._run_version(
                root,
                "new",
                "volatile int dummy = 1; (void)dummy;",
            )
            self.assertEqual(len(old_paths), 2)
            self.assertEqual(len(new_paths), 2)
            old_positive = old_paths[1]["semantic_summary"]
            new_positive = new_paths[1]["semantic_summary"]
            equivalent, _elapsed, _calls, mapping = (
                verifier.verify_global_state_equivalence(
                    old_positive, new_positive, 2_000
                )
            )
            self.assertFalse(equivalent)
            self.assertEqual(mapping["method"], "exact_canonical_key")

            result = verifier.verify_ranked_queue(
                old_dir,
                None,
                timeout_ms=2_000,
                naive=True,
                truth_pairs=None,
                program_ground_truth=False,
                allow_legacy_artifacts=False,
            )
            self.assertEqual(result["verdict"], "UNK")
            self.assertEqual(result.get("confirmed_mismatches", []), [])

    def test_global_mapping_has_traceable_width_compatible_fallback(self) -> None:
        left = {
            "left_name@0x0:4": {
                "object": "left_name",
                "offset": 0,
                "size_bytes": 4,
                "bits": 32,
                "smt": "",
            }
        }
        right = {
            "right_name@0x0:4": {
                "object": "right_name",
                "offset": 0,
                "size_bytes": 4,
                "bits": 32,
                "smt": "",
            }
        }
        pairs, evidence = verifier.map_global_regions_with_evidence(left, right)
        self.assertIsNotNone(pairs)
        self.assertIn("sorted_width_compatible_fallback", evidence["methods"])
        self.assertIn("identity_not_proved_by_fallback", evidence["assumptions"])


if __name__ == "__main__":
    unittest.main()
