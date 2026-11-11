"""Counterexamples to unsafe external-call authorization, using real ELF fixtures."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import angr
import claripy
import fixed_math_runtime as runtime
import round017_semantic_models as gate
from se_script_improved import BenchmarkSymbolicExecution, FixedSinCosHook


class FixedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.binary = cls.compile("normal", """
          #include <math.h>
          double total=7.0;
          double unused(double x) { return tan(x); }
          double snippet(double x) { return sin(x)+sqrt(x)+total; }
          int main(void) { return 0; }
        """)
        cls.cert = runtime.build_certificate(cls.binary, cls.root / "evidence")
        cls.project = angr.Project(str(cls.binary), auto_load_libs=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def compile(cls, name, source):
        src = cls.root / (name + ".c")
        src.write_text(source)
        binary = cls.root / name
        subprocess.run(["gcc", "-O1", "-g", str(src), "-o", str(binary), "-lm"], check=True, capture_output=True)
        return binary

    def state(self):
        s = self.project.factory.blank_state()
        s.globals["symbolicana_external_model_uses"] = []
        return s

    def collector(self):
        return runtime.CallEvidence(self.cert, self.root / self._testMethodName, 300)

    def test_real_binding_and_unreachable_import(self):
        self.assertEqual(runtime.validate_certificate(self.cert), [])
        self.assertIn("sin", self.cert["bindings"])
        self.assertNotIn("tan", self.cert["graph"]["reachable_imports"])
        final = runtime.finalize_audit(gate.audit_binary_imports(["sin", "sqrt", "tan"]), [], self.cert)
        self.assertIn("tan", final["excluded_unreachable_imports"])
        self.assertTrue(final["eq_eligible"])

    def test_changed_argument_and_signed_zero_do_not_share_return(self):
        c, s = self.collector(), self.state()
        x = claripy.FPS("input", claripy.FSORT_DOUBLE, explicit_name=True)
        same1 = c.record(s, "sin", x)
        same2 = c.record(s, "sin", x)
        different = c.record(s, "sin", x + claripy.FPV(1., claripy.FSORT_DOUBLE))
        pos = c.record(s, "sin", claripy.FPV(0., claripy.FSORT_DOUBLE))
        neg = c.record(s, "sin", claripy.FPV(-0., claripy.FSORT_DOUBLE))
        self.assertEqual(same1["relation_key"], same2["relation_key"])
        self.assertNotEqual(same1["relation_key"], different["relation_key"])
        self.assertNotEqual(pos["relation_key"], neg["relation_key"])

    def test_infeasible_call_has_explicit_unsat_formula(self):
        s, c = self.state(), self.collector()
        x = claripy.BVS("x", 8, explicit_name=True)
        s.solver.add(x == 1, x != 1)
        u = c.record(s, "sqrt", claripy.FPV(-1., claripy.FSORT_DOUBLE), sqrt=True)
        self.assertEqual(u["feasibility"]["status"], "unsat")
        self.assertTrue(Path(u["feasibility"]["query_path"]).is_file())
        self.assertEqual(runtime.validate_use(u, self.cert), [])

    def test_negative_and_nan_are_not_nonnegative_certificates(self):
        for value in [-1., float("nan")]:
            u = self.collector().record(self.state(), "sqrt", claripy.FPV(value, claripy.FSORT_DOUBLE), sqrt=True)
            self.assertFalse(u["argument_nonnegative"])
            self.assertEqual(u["kind"], "fixed_runtime_relation")
            self.assertEqual(u["nonnegative_query"]["status"], "sat")

    def test_exception_never_means_unsat(self):
        import z3
        with patch.object(z3.Solver, "check", side_effect=RuntimeError("test failure")):
            q = self.collector().query([claripy.BoolV(True)])
        self.assertEqual(q["status"], "unknown")

    def test_tampered_precision_argument_or_missing_query_blocks(self):
        u = self.collector().record(self.state(), "sin", claripy.FPV(1., claripy.FSORT_DOUBLE))
        bad = copy.deepcopy(u)
        bad["precision"] = 32
        self.assertIn("call_ABI_binding_mismatch", runtime.validate_use(bad, self.cert))
        bad = copy.deepcopy(u)
        bad["argument_expr_sha256"] = "0" * 64
        self.assertIn("call_argument_hash_mismatch", runtime.validate_use(bad, self.cert))
        bad = copy.deepcopy(u)
        bad["feasibility"]["query_path"] += ".missing"
        self.assertIn("call_evidence_missing_or_invalid", runtime.validate_use(bad, self.cert))

    def test_binary_tamper_invalidates_certificate(self):
        cert = copy.deepcopy(self.cert)
        cert["binary_sha256"] = "0" * 64
        self.assertTrue(runtime.validate_certificate(cert))

    def test_custom_library_search_path_is_not_silently_trusted(self):
        source = self.root / "rpath.c"
        source.write_text('#include <math.h>\ndouble snippet(double x){return sin(x);}\nint main(void){return 0;}\n')
        binary = self.root / "rpath"
        subprocess.run(["gcc", str(source), "-o", str(binary), "-lm", "-Wl,-rpath,/tmp/untrusted"], check=True)
        cert = runtime.build_certificate(binary, self.root / "rpath_evidence")
        self.assertTrue(any("unsupported_loader_configuration" in s for s in cert["blockers"]))

    def test_deferred_feasibility_does_not_claim_unreachability(self):
        u = self.collector().record(self.state(), "sin", claripy.FPV(1., claripy.FSORT_DOUBLE))
        self.assertEqual(u["feasibility"]["status"], "unknown")
        self.assertEqual(u["kind"], "fixed_runtime_relation")

    def test_mixed_contract_cannot_authorize_eq(self):
        a = runtime.finalize_audit(gate.audit_binary_imports(["sin"]), [], self.cert)
        b = gate.finalize_runtime_audit(gate.audit_binary_imports([]), [])
        merged = gate.combined_eq_audit([a, b])
        self.assertFalse(merged["eq_eligible"])
        self.assertIn("fixed_runtime_mixed_or_missing_contract", merged["validation_errors"])

    def test_initialized_entry_preserves_nonzero_data(self):
        engine = BenchmarkSymbolicExecution(str(self.binary), str(self.root / "initial"),
            snippet_signature="double(double)", initialized_entry=True)
        engine.setup_project()
        state = engine.create_symbolic_state()
        address = engine.project.loader.find_symbol("total").rebased_addr
        value = state.memory.load(address, 8, endness=state.arch.memory_endness)
        self.assertFalse(value.symbolic)
        self.assertEqual(state.solver.eval(value), 0x401c000000000000)

    def test_rounding_modification_and_indirect_calls_are_rejected(self):
        binary = self.compile("rounding", """
          #include <fenv.h>
          #include <math.h>
          double snippet(double x) { fesetround(FE_DOWNWARD); return sin(x); }
          int main(void) { return 0; }
        """)
        cert = runtime.build_certificate(binary, self.root / "rounding_evidence")
        self.assertIn("environment_import:fesetround", cert["blockers"])
        binary = self.compile("indirect", """
          double snippet(double (*p)(double), double x) { return p(x); }
          int main(void) { return 0; }
        """)
        graph = runtime.entry_call_graph(binary)
        self.assertTrue(any(x.startswith("unresolved_transfer:") for x in graph["blockers"]))

    def test_sincos_alias_and_swap_preserve_actual_write_order(self):
        binary = self.compile("sincos", """
          #define _GNU_SOURCE
          #include <math.h>
          double snippet(double x) { double s,c; sincos(x,&s,&c); return s+c; }
          int main(void) { return 0; }
        """)
        cert = runtime.build_certificate(binary, self.root / "sincos_evidence")
        collector = runtime.CallEvidence(cert, self.root / "sincos_queries", 100)
        state = self.state()
        hook = FixedSinCosHook(function_name="sincos", call_evidence=collector,
                              prototype="void sincos(double,double*,double*)")
        v = claripy.FPV(1., claripy.FSORT_DOUBLE)
        ptr = claripy.BVV(0x100000, 64)
        hook.execute(state, arguments=[v, ptr, ptr])
        final = state.memory.load(ptr, 8, endness=state.arch.memory_endness)
        self.assertTrue(any(name.endswith("_cos") for name in final.variables))
        self.assertFalse(any(name.endswith("_sin") for name in final.variables))
        other = claripy.BVV(0x100008, 64)
        swapped = self.state()
        hook.execute(swapped, arguments=[v, other, ptr])
        first = swapped.memory.load(ptr, 8, endness=swapped.arch.memory_endness)
        second = swapped.memory.load(other, 8, endness=swapped.arch.memory_endness)
        self.assertTrue(any(name.endswith("_cos") for name in first.variables))
        self.assertTrue(any(name.endswith("_sin") for name in second.variables))


if __name__ == "__main__":
    unittest.main()
