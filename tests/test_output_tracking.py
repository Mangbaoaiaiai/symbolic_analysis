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


@unittest.skipUnless(shutil.which("gcc"), "gcc is required for the integration test")
class SymbolicOutputTrackingTests(unittest.TestCase):
    def test_each_path_records_its_ordered_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            source = directory / "output_probe.c"
            binary = directory / "output_probe"
            source.write_text(
                "#include <stdio.h>\n"
                "int snippet(int value) {\n"
                "  if (value < 0)\n"
                '    printf("%s\\n", "negative");\n'
                "  return value < 0 ? 0 : 1;\n"
                "}\n"
                "int main(void) { return snippet(0); }\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "gcc",
                    "-O0",
                    "-fno-pie",
                    "-no-pie",
                    "-o",
                    str(binary),
                    str(source),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            analyzer = se_script_improved.BenchmarkSymbolicExecution(
                str(binary),
                str(directory / "probe"),
                timeout=30,
                snippet_signature="int(int)",
                loop_bound=5,
                max_paths=10,
                int_min=-5,
                int_max=5,
            )
            paths = analyzer.run_symbolic_execution()
            self.assertEqual(len(paths), 2)
            flattened = [
                verifier.flatten_output_segments(path["semantic_summary"])
                for path in paths
            ]
            self.assertIn(
                [{"kind": "text", "value": "negative\n", "sink": "stdout"}],
                flattened,
            )
            self.assertIn([], flattened)
            for path in paths:
                output = path["semantic_summary"]["program_output"]
                self.assertTrue(output["available"])
                self.assertTrue({"printf", "puts"} & set(output["hooks"]))

    def test_printf_formatted_argument_is_recorded_symbolically(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            source = directory / "printf_probe.c"
            binary = directory / "printf_probe"
            source.write_text(
                "#include <stdio.h>\n"
                "int snippet(int value) {\n"
                '  printf("value=%d\\n", value);\n'
                "  return value;\n"
                "}\n"
                "int main(void) { return snippet(0); }\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "gcc",
                    "-O0",
                    "-fno-builtin",
                    "-fno-pie",
                    "-no-pie",
                    "-o",
                    str(binary),
                    str(source),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            analyzer = se_script_improved.BenchmarkSymbolicExecution(
                str(binary),
                str(directory / "printf_probe"),
                timeout=30,
                snippet_signature="int(int)",
                loop_bound=5,
                max_paths=10,
                int_min=0,
                int_max=3,
            )
            paths = analyzer.run_symbolic_execution()
            self.assertEqual(len(paths), 1)
            output = paths[0]["semantic_summary"]["program_output"]
            self.assertTrue(output["available"], output)
            segments = verifier.flatten_output_segments(paths[0]["semantic_summary"])
            self.assertIsNotNone(segments, output)
            self.assertEqual(segments[0], {"kind": "text", "value": "value=", "sink": "stdout"})
            self.assertEqual(segments[1]["kind"], "formatted_value")
            self.assertEqual(segments[1]["specifier"], "%d")
            self.assertTrue(segments[1]["repr"].startswith("<BV32 arg_0"))
            self.assertEqual(
                segments[2],
                {"kind": "text", "value": "\n", "sink": "stdout"},
            )


if __name__ == "__main__":
    unittest.main()
