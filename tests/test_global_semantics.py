"""Integration checks for the deployed written-cell/initialized-entry model."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import se_script_improved

@unittest.skipUnless(shutil.which('gcc'), 'gcc is required')
class GlobalSemanticsTests(unittest.TestCase):
    def analyze(self, root, value, body):
        source = root / 'probe.c'
        binary = root / 'probe'
        source.write_text(f'int g = {value}; int snippet(void) {{ {body} }} '
                          'int main(void) { return snippet(); }')
        subprocess.run(['gcc', '-O0', '-fno-pie', '-no-pie', str(source), '-o', str(binary)],
                       check=True, capture_output=True)
        (root / 'paths').mkdir()
        analyzer = se_script_improved.BenchmarkSymbolicExecution(
            str(binary), str(root / 'paths/symbolic_oldV'),
            snippet_signature='int(void)', initialized_entry=True, timeout=15, max_paths=10)
        return analyzer.run_symbolic_execution()[0]['semantic_summary']

    def test_initialized_global_read_reaches_return_summary(self):
        for value in (0, 1, 7):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as raw:
                summary = self.analyze(Path(raw), value, 'return g;')
                self.assertEqual(summary['return_value']['repr'], f'<BV32 {value:#x}>')
                self.assertEqual(summary['global_state']['address_model'],
                                 'section_relative_written_cells')
                self.assertEqual(summary['global_state']['regions'], {})

    def test_global_write_is_retained(self):
        with tempfile.TemporaryDirectory() as raw:
            summary = self.analyze(Path(raw), 0, 'g = 7; return g;')
            self.assertTrue(summary['global_state']['available'])
            self.assertTrue(summary['global_state']['regions'])
            self.assertEqual(summary['return_value']['repr'], '<BV32 0x7>')
