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


@unittest.skipUnless(shutil.which("gcc"), "gcc is required")
class LoopBoundaryTests(unittest.TestCase):
    def _compile(self, directory: Path, name: str, body: str, optimization: str) -> Path:
        source = directory / f"{name}.c"
        binary = directory / f"{name}_{optimization}"
        source.write_text(
            "#include <stdio.h>\n"
            f"int snippet(int ignored) {{\n{body}\n}}\n"
            "int main(void) { return snippet(0); }\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                "gcc",
                f"-{optimization}",
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
        return binary

    def _analyze(self, binary: Path, prefix: Path):
        analyzer = se_script_improved.BenchmarkSymbolicExecution(
            str(binary),
            str(prefix),
            timeout=20,
            snippet_signature="int(int)",
            loop_bound=30,
            max_paths=10,
            int_min=0,
            int_max=1,
        )
        return analyzer.run_symbolic_execution(), analyzer.exploration_manifest

    def test_loop_bound_reports_incompleteness_at_o0_and_o3(self) -> None:
        for optimization in ("O0", "O3"):
            for count in (0, 1, 29, 30, 31, 32):
                with self.subTest(optimization=optimization, count=count):
                    with tempfile.TemporaryDirectory() as raw_dir:
                        directory = Path(raw_dir)
                        body = (
                            f"  volatile int limit = {count};\n"
                            "  int sum = 0;\n"
                            "  for (int i = 0; i < limit; ++i) sum += i;\n"
                            "  return sum;\n"
                        )
                        binary = self._compile(
                            directory, f"count_{count}", body, optimization
                        )
                        paths, manifest = self._analyze(
                            binary, directory / f"count_{count}_{optimization}"
                        )
                        if count <= 30:
                            self.assertTrue(manifest["complete"])
                            self.assertEqual(manifest["loop_bound_event_count"], 0)
                            self.assertEqual(len(paths), 1)
                        elif count >= 32 or not manifest["complete"]:
                            self.assertFalse(manifest["complete"])
                            self.assertIn(
                                "loop_bound_reached",
                                manifest["incomplete_reasons"],
                            )
                            self.assertGreaterEqual(
                                manifest["loop_bound_event_count"], 1
                            )
                            self.assertFalse(manifest["proof_eligible"])
                        else:
                            # This snapshot bounds binary back-edge trips.
                            self.assertEqual(count, 31)
                            self.assertEqual(manifest["loop_bound_event_count"], 0)
                            self.assertEqual(len(paths), 1)

    def test_break_continue_and_nested_loops_complete(self) -> None:
        probes = {
            "break": (
                "  int sum = 0;\n"
                "  for (int i = 0; i < 30; ++i) {\n"
                "    if (i == 15) break;\n"
                "    sum += i;\n"
                "  }\n"
                "  return sum;\n"
            ),
            "continue": (
                "  int sum = 0;\n"
                "  for (int i = 0; i < 30; ++i) {\n"
                "    if (i % 2) continue;\n"
                "    sum += i;\n"
                "  }\n"
                "  return sum;\n"
            ),
            "nested": (
                "  int sum = 0;\n"
                "  for (int i = 0; i < 3; ++i)\n"
                "    for (int j = 0; j < 4; ++j)\n"
                "      sum += i + j;\n"
                "  return sum;\n"
            ),
        }
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            for name, body in probes.items():
                with self.subTest(name=name):
                    binary = self._compile(directory, name, body, "O0")
                    paths, manifest = self._analyze(binary, directory / name)
                    self.assertTrue(manifest["complete"], manifest)
                    self.assertEqual(manifest["loop_bound_event_count"], 0)
                    self.assertEqual(len(paths), 1)


if __name__ == "__main__":
    unittest.main()
