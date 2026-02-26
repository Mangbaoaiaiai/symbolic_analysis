## Overview

Symbolic-analysis framework for the TSVC benchmark suite and ARDiff-style comparison. Core library lives under `src/symbolic_analysis/`; scripts under `scripts/` (and `scripts/ardiff_comparison/` for ARDiff-only).

---

## Key Scripts

| Script | Purpose |
|--------|--------|
| `scripts/quick_start_demo.py` | Smoke test: dependencies, path generation, symbolic analysis, mini TSVC run. |
| `scripts/se_script_improved.py` | Standalone symbolic-execution driver for TSVC-style programs. |
| `scripts/simple_angr_test.py` | Quick check that angr is installed and usable. |
| `scripts/run_benchmark_analysis.py` | Run a batch of TSVC benchmark analyses. |
| `scripts/create_all_benchmarks.py` | Generate / materialize all TSVC benchmarks. |
| `src/symbolic_analysis/integration/tsvc_symbolic_integration.py` | Full TSVC pipeline: extract, compile (O1/O2/O3), generate paths, run equivalence analysis, write results. |
| `src/symbolic_analysis/equivalence/semantic_equivalence_analyzer.py` | Compare two sets of path files for equivalence (three-step: constraints + array initial/final state). |
| `scripts/ardiff_comparison/analyze_airy_max_eq.py` | ARDiff comparison: analyze Airy MAX equivalence. |
| `scripts/ardiff_comparison/enhanced_equivalence_analyzer.py` | ARDiff: enhanced equivalence analysis. |
| `scripts/ardiff_comparison/verify_java_equivalence.py` | ARDiff: verify Java program equivalence. |
| `scripts/ardiff_comparison/semantic_equivalence_analyzer_enhanced.py` | ARDiff: enhanced semantic equivalence. |
| `scripts/ardiff_comparison/convert_and_compile.sh` | ARDiff: convert and compile benchmark programs. |

---

## How to Run

- **Working directory:** always the project root (the `symbolic_analysis/` directory).
- **Imports:** scripts that use `src/symbolic_analysis` need it on `PYTHONPATH`. From the project root, run:

  ```bash
  export PYTHONPATH=src
  ```

  or prefix each command with `PYTHONPATH=src`.

**Suggested order:**

1. **Sanity check (optional)**  
   ```bash
   cd symbolic_analysis
   PYTHONPATH=src python3 scripts/quick_start_demo.py
   ```

2. **Full TSVC pipeline**  
   ```bash
   PYTHONPATH=src python3 src/symbolic_analysis/integration/tsvc_symbolic_integration.py
   ```  
   Writes to `data/tsvc/tsvc_analysis_results/` and a comparison report.

3. **Standalone symbolic execution**  
   ```bash
   PYTHONPATH=src python3 scripts/se_script_improved.py
   ```

4. **Path equivalence (two path prefixes)**  
   ```bash
   PYTHONPATH=src python3 src/symbolic_analysis/equivalence/semantic_equivalence_analyzer.py \
     <prefix1> <prefix2> --output report.txt
   ```  
   Example: `paths_prog1/path_` and `paths_prog2/path_`.

5. **ARDiff scripts**  
   Run from project root with `PYTHONPATH=src`; ARDiff benchmarks live under `experiments/ardiff_comparison/benchmarks/`, e.g.:

   ```bash
   PYTHONPATH=src python3 scripts/ardiff_comparison/analyze_airy_max_eq.py
   ```

**Requirements:** Python 3, Z3, angr (for full functionality).
