"""Evidence-bound math-call abstraction for one initialized ELF entry call.

This is deliberately not a numerical approximation of libm. Equal *complete*
argument expressions share arbitrary bit-vector results; unequal expressions
remain independent (a conservative loss of precision). The trusted boundary is
the explicitly frozen, default-environment, deterministic libm contract.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

SCHEMA = "symbolicana.fixed_math_runtime.v1"
SCALARS = {name: bits for name in ("sin", "cos", "tan", "atan", "exp", "log", "sqrt")
           for name, bits in ((name, 64), (name + "f", 32))}
MULTI = {"sincos": 64, "sincosf": 32}
SUPPORTED = {**SCALARS, **MULTI}
ENV_SYMBOLS = {"__errno_location", "fegetround", "fesetround", "feclearexcept",
               "fetestexcept", "fegetenv", "fesetenv", "feholdexcept", "feupdateenv",
               "feraiseexcept", "feenableexcept", "fedisableexcept", "setcontext",
               "swapcontext", "dlopen", "dlsym", "dlvsym"}
ENV_INSTRUCTIONS = {"ldmxcsr", "vldmxcsr", "stmxcsr", "vstmxcsr", "fldcw",
                    "fnstcw", "fstcw", "fnstsw", "fstsw", "fldenv", "fnstenv",
                    "fxrstor", "fxrstor64", "xrstor", "xrstor64", "syscall", "sysenter"}


def digest(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def file_hash(path):
    return digest(Path(path).read_bytes())


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=30)


def entry_call_graph(binary, entry="snippet"):
    """Overapproximate all direct transfers in every entry-reachable function.

    Unknown indirect transfers, undecodable edges, and environment instructions
    block qualification. No observed execution is used as non-reachability proof.
    """
    disasm = command("objdump", "-d", "-w", "-M", "intel", str(binary))
    functions = {}
    current = None
    for line in disasm.splitlines():
        match = re.match(r"^([0-9a-f]+) <(.+)>:$", line)
        if match:
            current = match[2]
            functions[current] = []
        elif current:
            match = re.match(r"\s*[0-9a-f]+:\s+(?:[0-9a-f]{2}\s+)+\s*([a-z][a-z0-9]*)\s*(.*)", line)
            if match:
                functions[current].append((match[1], match[2], line.strip()))
    reached, imports, blockers, todo = set(), set(), [], [entry]
    while todo:
        name = todo.pop()
        if name in reached:
            continue
        reached.add(name)
        if "@plt" in name:
            imports.add(name.split("@")[0])
            continue
        if name not in functions:
            blockers.append("unresolved_function:" + name)
            continue
        for mnemonic, operand, line in functions[name]:
            if mnemonic in ENV_INSTRUCTIONS or mnemonic.startswith(("xrstor", "fxrstor")):
                blockers.append("environment_instruction:" + line)
            if mnemonic.startswith("call") or mnemonic.startswith("j") or mnemonic.startswith("loop"):
                target = re.search(r"\b[0-9a-f]+\s+<([^>]+)>", operand)
                if not target or "PTR" in operand:
                    blockers.append("unresolved_transfer:" + line)
                    continue
                base = target[1].split("+")[0].split("-")[0]
                if base != name:
                    todo.append(base)
    blockers.extend("environment_import:" + name for name in sorted(imports & ENV_SYMBOLS))
    return {"entry": entry, "reachable_functions": sorted(reached),
            "reachable_imports": sorted(imports), "blockers": sorted(set(blockers)),
            "disassembly_sha256": digest(disasm), "disassembly": disasm}


class DlInfo(ctypes.Structure):
    _fields_ = [("fname", ctypes.c_char_p), ("base", ctypes.c_void_p),
                ("sname", ctypes.c_char_p), ("saddr", ctypes.c_void_p)]


def runtime_binding(symbol, version):
    lib = ctypes.CDLL("libm.so.6")
    loader = ctypes.CDLL(None)
    loader.dlvsym.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    loader.dlvsym.restype = ctypes.c_void_p
    address = loader.dlvsym(lib._handle, symbol.encode(), version.encode())
    if not address:
        raise ValueError("versioned_binding_missing:" + symbol + ":" + version)
    info = DlInfo()
    loader.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(DlInfo)]
    if not loader.dladdr(address, ctypes.byref(info)):
        raise ValueError("binding_object_unknown:" + symbol)
    path = str(Path(os.fsdecode(info.fname)).resolve())
    lib.fegetround.restype = ctypes.c_int
    if lib.fegetround() != 0:
        raise ValueError("nondefault_rounding_environment")
    return {"symbol": symbol, "version": version, "library_path": path,
            "library_sha256": file_hash(path), "resolved_offset": address - info.base,
            "abi": ("void " + symbol + "(double,double*,double*)" if symbol == "sincos"
                    else "void sincosf(float,float*,float*)" if symbol == "sincosf"
                    else ("double" if SUPPORTED[symbol] == 64 else "float") + " " + symbol
                    + "(" + ("double" if SUPPORTED[symbol] == 64 else "float") + ")")}


def build_certificate(binary, out_dir):
    from elftools.elf.elffile import ELFFile
    binary, out_dir = Path(binary).resolve(), Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    graph = entry_call_graph(binary)
    disasm = graph.pop("disassembly")
    (out_dir / "disassembly.txt").write_text(disasm)
    blockers = list(graph["blockers"])
    for name in os.environ:
        if (name.startswith("LD_") or name == "GLIBC_TUNABLES") and os.environ[name]:
            blockers.append("loader_override:" + name)
    with binary.open("rb") as stream:
        elf = ELFFile(stream)
        if elf.header["e_machine"] != "EM_X86_64" or elf.elfclass != 64:
            blockers.append("unsupported_ABI")
        dynamic_section = elf.get_section_by_name(".dynamic")
        needed = []
        for tag in dynamic_section.iter_tags() if dynamic_section else []:
            kind = tag.entry.d_tag
            if kind == "DT_NEEDED":
                needed.append(tag.needed)
            elif kind in {"DT_RPATH", "DT_RUNPATH", "DT_AUDIT", "DT_DEPAUDIT", "DT_FILTER", "DT_AUXILIARY"}:
                blockers.append("unsupported_loader_configuration:" + kind)
        if set(needed) - {"libm.so.6", "libc.so.6", "ld-linux-x86-64.so.2"}:
            blockers.append("unqualified_dependency:" + ",".join(sorted(set(needed) - {"libm.so.6", "libc.so.6", "ld-linux-x86-64.so.2"})))
        interpreter = next((s.get_interp_name() for s in elf.iter_segments()
                            if s.header.p_type == "PT_INTERP"), None)
        if not interpreter or not Path(interpreter).is_file():
            blockers.append("dynamic_loader_missing")
        # Only toolchain frame_dummy startup is covered by initialized-entry mode.
        symtab = elf.get_section_by_name(".symtab")
        symbols = list(symtab.iter_symbols()) if symtab else []
        frame = {s["st_value"] for s in symbols if s.name == "frame_dummy"}
        init = elf.get_section_by_name(".init_array")
        if init:
            data = init.data()
            values = [int.from_bytes(data[i:i+8], "little") for i in range(0, len(data), 8)]
            if any(v not in frame | {0} for v in values):
                blockers.append("unmodeled_entry_initialization")
    dynamic = command("objdump", "-T", str(binary))
    bindings = {}
    for symbol in graph["reachable_imports"]:
        if symbol not in SUPPORTED:
            continue
        rows = [line for line in dynamic.splitlines() if line.split() and line.split()[-1] == symbol and "*UND*" in line]
        versions = {m[1] for line in rows if (m := re.search(r"\(([^)]+)\)", line))}
        if len(versions) != 1:
            blockers.append("missing_symbol_version:" + symbol)
            continue
        try:
            bindings[symbol] = runtime_binding(symbol, next(iter(versions)))
        except Exception as exc:
            blockers.append(str(exc))
    loaders = sorted({line.split()[-1] for line in Path("/proc/self/maps").read_text().splitlines()
                      if "ld-linux" in line and line.split()[-1].startswith("/")})
    loader_hashes = {path: file_hash(path) for path in loaders}
    cpu_flags = sorted({line for line in Path("/proc/cpuinfo").read_text().splitlines()
                        if line.startswith(("flags", "model name", "vendor_id"))})
    assumptions = {"entry_state": "initialized_single_call", "rounding": "nearest_even",
                   "ftz_daz": "disabled", "library_contract": "deterministic_scalar_or_sincos",
                   "errno_fenv": "unobserved_and_not_modified_by_target",
                   "binding": "frozen_environment_no_interposition"}
    data = {"schema": SCHEMA, "binary": str(binary), "binary_sha256": file_hash(binary),
            "module_sha256": file_hash(__file__), "graph": graph, "bindings": bindings,
            "dependencies": sorted(needed), "interpreter": interpreter,
            "loader_hashes": loader_hashes, "cpu_sha256": digest(canonical(cpu_flags)),
            "assumptions": assumptions, "blockers": sorted(set(blockers))}
    # Excludes per-target symbols/addresses: both sides share this environment.
    data["environment_id"] = digest(canonical({"loader": loader_hashes,
        "cpu": data["cpu_sha256"], "assumptions": assumptions,
        "libm": file_hash("/lib/x86_64-linux-gnu/libm.so.6")}))
    data["certificate_id"] = digest(canonical(data))
    data["certificate_path"] = str(out_dir / "runtime.json")
    write_json(data["certificate_path"], data)
    return data


def validate_certificate(cert):
    errors = []
    if not isinstance(cert, dict) or cert.get("schema") != SCHEMA:
        return ["fixed_runtime_certificate_missing"]
    basis = {k: v for k, v in cert.items() if k not in {"certificate_id", "certificate_path"}}
    if digest(canonical(basis)) != cert.get("certificate_id"):
        errors.append("fixed_runtime_certificate_hash_mismatch")
    for path, expected in [(cert.get("binary"), cert.get("binary_sha256")),
                           (__file__, cert.get("module_sha256")),
                           *cert.get("loader_hashes", {}).items(),
                           *((b["library_path"], b["library_sha256"]) for b in cert.get("bindings", {}).values())]:
        try:
            if file_hash(path) != expected:
                errors.append("fixed_runtime_identity_changed:" + str(path))
        except (OSError, TypeError):
            errors.append("fixed_runtime_identity_missing:" + str(path))
    return errors + list(cert.get("blockers", []))


class CallEvidence:
    def __init__(self, certificate, directory, timeout_ms=2000):
        self.certificate = certificate
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.timeout_ms = timeout_ms
        self.queries = {}

    def query(self, constraints, extra=(), *, defer=False):
        import claripy
        import z3
        terms = [claripy.backends.z3.convert(x) for x in [*constraints, *extra]]
        solver = z3.Solver(ctx=terms[0].ctx if terms else None)
        solver.set(timeout=self.timeout_ms)
        solver.add(*terms)
        smt = ("; feasibility deferred: relation remains an overapproximation\n" if defer else "") + solver.to_smt2()
        key = digest(smt)
        if key in self.queries:
            return self.queries[key]
        path = self.directory / (key + ".smt2")
        path.write_text(smt)
        started = time.monotonic()
        try:
            status = "unknown" if defer else str(solver.check())
            reason = "not_required_for_universal_call_relation" if defer else solver.reason_unknown() if status == "unknown" else ""
        except Exception as exc:
            status, reason = "unknown", repr(exc)
        result = {"status": status, "reason": reason, "query_path": str(path),
                  "query_sha256": key, "timeout_ms": self.timeout_ms,
                  "elapsed_seconds": time.monotonic() - started, "solver": z3.get_version_string()}
        write_json(path.with_suffix(".json"), result)
        self.queries[key] = result
        return result

    def record(self, state, function, value, *, sqrt=False):
        import claripy
        expression = value.raw_to_bv() if getattr(value, "sort", None) is not None else value
        # No truncated repr, no variable renaming, no zero/NaN normalization.
        term = claripy.backends.z3.convert(expression).sexpr()
        arg_hash = digest(term)
        arg_file = self.directory / (arg_hash + ".argument.sexpr")
        if not arg_file.exists():
            arg_file.write_text(term)
        record = {"function": function, "precision": SUPPORTED[function],
                  "call_address": int(state.addr), "callsite": int(state.callstack.call_site_addr),
                  "argument_expr_sha256": arg_hash, "argument_path": str(arg_file),
                  "certificate_id": self.certificate["certificate_id"],
                  "feasibility": self.query(state.solver.constraints, defer=not sqrt),
                  "kind": "fixed_runtime_relation", "argument_nonnegative": False}
        if record["feasibility"]["status"] == "unsat":
            record["kind"] = "unreachable_call"
        elif sqrt:
            fp = value if getattr(value, "sort", None) is not None else value.raw_to_fp()
            record["nonnegative_query"] = self.query(state.solver.constraints,
                [claripy.Not(fp >= claripy.FPV(0., fp.sort))])
            record["argument_nonnegative"] = record["nonnegative_query"]["status"] == "unsat"
            if record["argument_nonnegative"]:
                record["kind"] = "ieee754_sqrt"
        binding = self.certificate["bindings"].get(function)
        record["abi_prototype"] = binding["abi"] if binding else ""
        record["binding_id"] = digest(canonical(binding))
        record["relation_key"] = digest(canonical({"binding": binding,
            "environment": self.certificate["environment_id"], "argument": term}))
        uses = list(state.globals.get("symbolicana_external_model_uses", []))
        uses.append(record)
        state.globals["symbolicana_external_model_uses"] = uses
        return record


def validate_use(use, certificate):
    errors = []
    if use.get("unsupported_pointer_outputs"):
        errors.append("symbolic_sincos_output_pointer")
    if use.get("certificate_id") != certificate.get("certificate_id"):
        errors.append("call_certificate_mismatch")
    try:
        term = Path(use["argument_path"]).read_text()
        if digest(term) != use["argument_expr_sha256"]:
            errors.append("call_argument_hash_mismatch")
        binding = certificate["bindings"].get(use["function"])
        if not binding or use.get("abi_prototype") != binding["abi"] or use.get("precision") != SUPPORTED[use["function"]]:
            errors.append("call_ABI_binding_mismatch")
        expected = digest(canonical({"binding": binding, "environment": certificate["environment_id"], "argument": term}))
        if use.get("relation_key") != expected:
            errors.append("call_relation_key_mismatch")
        for key in ("feasibility", "nonnegative_query"):
            query = use.get(key)
            if query is None and key == "nonnegative_query":
                continue
            if file_hash(query["query_path"]) != query["query_sha256"]:
                errors.append("call_query_hash_mismatch")
            stored = json.loads(Path(query["query_path"]).with_suffix(".json").read_text())
            if stored != query or query["status"] not in {"sat", "unsat", "unknown"}:
                errors.append("call_query_record_mismatch")
    except (OSError, KeyError, TypeError, ValueError):
        errors.append("call_evidence_missing_or_invalid")
    if use.get("kind") == "ieee754_sqrt" and (use.get("nonnegative_query") or {}).get("status") != "unsat":
        errors.append("sqrt_nonnegative_not_proved")
    if use.get("kind") == "unreachable_call" and (use.get("feasibility") or {}).get("status") != "unsat":
        errors.append("call_unreachability_not_proved")
    if use.get("kind") not in {"fixed_runtime_relation", "ieee754_sqrt", "unreachable_call"}:
        errors.append("call_model_kind_unknown")
    return errors


def finalize_audit(base, uses, certificate):
    result = json.loads(canonical(base))
    errors = validate_certificate(certificate)
    reachable = set(certificate.get("graph", {}).get("reachable_imports", []))
    qualified = set(certificate.get("bindings", {})) if not errors else set()
    blockers, excluded = [], []
    for reason in result.get("eq_blockers", []):
        if reason.startswith("unqualified_external_model:"):
            name = reason.split(":", 1)[1]
            if not errors and name not in reachable:
                excluded.append(name)
                continue
            if name in qualified:
                continue
        blockers.append(reason)
    unique = {canonical(u): u for u in uses}
    for use in unique.values():
        errors.extend(validate_use(use, certificate))
        if use.get("function") not in qualified:
            blockers.append("unqualified_runtime_model_use:" + use.get("function", ""))
    result.update(runtime_uses=list(unique.values()), runtime_evidence_complete=True,
                  fixed_runtime=certificate, excluded_unreachable_imports=sorted(excluded),
                  eq_blockers=sorted(set(blockers + errors)))
    result["eq_eligible"] = not result["eq_blockers"]
    result["audit_hash"] = digest(canonical({k: v for k, v in result.items() if k != "audit_hash"}))
    return result
