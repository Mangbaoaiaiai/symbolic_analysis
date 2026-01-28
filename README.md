## Overview

This repository contains a symbolic-analysis framework for the TSVC benchmark
suite, plus experiments that compare the framework against the PLDI'19
equivalence checker and against ARDiff-style program-difference analyses.

The project is organized as a **library-style core** under `src/`, a set of
**user-facing scripts** under `scripts/`, and **experiment and result data**
under `data/` and `experiments/`. It is designed so that you can either:

- run ready-made end-to-end analyses on TSVC benchmarks, or  
- reuse the individual components (symbolic execution, SMT-based equivalence,
  benchmark orchestration) in your own workflows.

---

## Project Structure

- **`scripts/`** – Entry-point scripts and small demos.
  - `quick_start_demo.py` – End-to-end smoke test for dependencies, path
    generation, symbolic analysis, and a mini TSVC benchmark run.
  - `se_script.py` / `se_script_improved.py` – Standalone symbolic-execution
    drivers for TSVC-style programs.
  - `simple_demo_tsvc.py` – Minimal TSVC benchmark demo.
  - `simple_angr_test.py` – Simple angr-based test to verify the environment.
  - `run_benchmark_analysis.py` – Convenience script to run a batch of analyses.
  - `create_all_benchmarks.py` – Generate / materialize all TSVC benchmarks.

- **`src/symbolic_analysis/`** – Core reusable library code.
  - **`benchmarks/`**
    - `tsvc_benchmark_runner.py` – Extract and compile TSVC benchmark functions,
      manage optimization-level variants (O1/O2/O3).
    - `real_tsvc_analyzer.py`, `improved_real_tsvc_analyzer.py`,
      `enhanced_mock_tsvc_analyzer.py` – Higher-level benchmark analyzers
      that coordinate compilation and analysis.
  - **`integration/`**
    - `tsvc_symbolic_integration.py` – Main integrator that runs the TSVC
      pipeline end to end and produces comparison reports versus PLDI'19.
    - `batch_symbolic_execution.py` – Batch driver for symbolic execution.
    - `batch_equivalence_analyzer.py` – Batch driver for equivalence checking.
    - `integrated_analysis.py` – Glue code for combined workflows.
  - **`symbolic_execution/`**
    - `enhanced_symbolic_execution.py` – Core symbolic-execution engine for the
      TSVC-style programs.
    - `path_analyzer_fixed.py` – Robust path-file processing and analysis.
    - `angr_memory_analysis.py` – angr-based memory and state inspection.
    - `memory_optimized_analysis.py` – Memory-optimized analysis flows for
      large benchmarks.
    - `debug_path_generation.py` – Utilities to debug path generation.
  - **`equivalence/`**
    - `semantic_equivalence_analyzer.py` – Enhanced three-step equivalence
      analyzer (constraint equivalence + array initial/final states).
    - `path_constraint_equivalence_verifier.py` – Path-constraint equivalence
      checker over SMT encodings.
    - `smt_equivalence_checker.py` – Low-level Z3-based equivalence routines.
    - `equivalence_summary.py` – Helpers for aggregating and summarizing
      equivalence results.
    - `constraint_analysis.py` – Additional analyses over generated constraints.
  - **`analysis/`**
    - `program_semantic_analysis.py` – Higher-level semantic analysis passes.
    - `smt_performance_analysis.py` – Measure and analyze SMT solver behavior.
    - `benchmark_timing_analysis.py`,
      `benchmark_timing_summary_table.py`,
      `corrected_analysis.py` – Timing and quality-of-result analyses.
  - **`tooling/`**
    - `clang_improved.py` – Utilities around Clang / compilation for TSVC.
    - `benchmark_source_fixer.py` – Fix-ups and normalization for benchmark
      source code.

- **`data/`** – Machine-readable analysis results.
  - `data/tsvc/tsvc_analysis_results/` – Per-benchmark JSON summaries.
  - `data/tsvc/paths/` – Raw path constraint files (`*_path_*.txt`) generated
    during symbolic execution.
  - `data/tsvc/reports/` – Timing and equivalence reports for TSVC benchmarks.
  - `data/batch/` – Batch-level summary JSON (`batch_*_data.json`).
  - `data/benchmark_timing/` – Overall timing summary JSON files.

- **`experiments/`** – Experiment-specific scripts and results.
  - `experiments/tsvc_experiments/` – TSVC-focused experiments and reports
    (e.g., various `vtv*`, `vpv*` timing and equivalence studies).
  - `experiments/ardiff_comparison/` – Symbolic-analysis experiments comparing
    against ARDiff-style Java-based equivalence checking, including
    `symbolic_analysis/benchmarks/` and `symbolic_analysis/equivalence_results/`.

- **`docs/`** – Higher-level documentation (currently in Chinese; can be used
  as reference for methodology and design decisions).

- **`tests/`** – Python-based tests for core components such as the layered
  system and enhanced symbolic execution / equivalence.

---

## Key Workflows

- **Quick smoke test**

  ```bash
  cd symbolic_analysis
  python3 scripts/quick_start_demo.py
  ```

  This checks for required files, runs extraction/compilation of a small TSVC
  benchmark, generates example paths, and runs basic symbolic-analysis checks.

- **Run the full TSVC integration pipeline**

  ```bash
  cd symbolic_analysis
  python3 src/symbolic_analysis/integration/tsvc_symbolic_integration.py
  ```

  This:
  - extracts and compiles recommended TSVC benchmarks at multiple optimization
    levels,
  - generates path constraints,
  - runs symbolic equivalence analysis, and
  - writes JSON summaries under `data/tsvc/tsvc_analysis_results/` and a
    consolidated comparison report.

- **Symbolic execution and equivalence as standalone tools**

  - Run standalone symbolic execution:

    ```bash
    python3 scripts/se_script.py
    ```

  - Run enhanced path equivalence on two sets of path files:

    ```bash
    python3 src/symbolic_analysis/equivalence/semantic_equivalence_analyzer.py \
      paths_prog1/path_ paths_prog2/path_ \
      --output enhanced_equivalence_report.txt
    ```

---

## Notes

- The repository assumes a working Python 3 environment with Z3 and angr
  installed for the full feature set.
- Large result directories under `data/` and `experiments/` can be safely
  regenerated by re-running the appropriate scripts if needed. 