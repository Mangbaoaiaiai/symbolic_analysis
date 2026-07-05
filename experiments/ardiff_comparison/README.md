# ARDiff Comparison Benchmarks

This directory contains old/new program pairs for equivalence-checking
experiments. Each case provides `symbolic_oldV.c` and `symbolic_newV.c`; the
pipeline compiles them, runs symbolic execution, and compares their path
constraints and semantic outputs.

## Single-Case Workflow

From a benchmark case directory, for example
`experiments/ardiff_comparison/benchmarks/Airy/MAX/Eq`:

```bash
gcc -o symbolic_oldV symbolic_oldV.c -lm
gcc -o symbolic_newV symbolic_newV.c -lm
python ../../../../../../scripts/se_script_improved.py --binary ./symbolic_oldV
python ../../../../../../scripts/se_script_improved.py --binary ./symbolic_newV
python ../../../../../../scripts/ardiff_comparison/semantic_equivalence_analyzer_enhanced.py \
  symbolic_oldV_path symbolic_newV_path \
  --output enhanced_equivalence_report.txt
```

The symbolic-execution step writes `symbolic_oldV_path_*.txt` and
`symbolic_newV_path_*.txt`. The equivalence step writes
`enhanced_equivalence_report.txt`.

## One-Command Helper

From the repository root:

```bash
./experiments/ardiff_comparison/run_one_benchmark.sh experiments/ardiff_comparison/benchmarks/Airy/MAX/Eq
```

Short benchmark-relative paths are also accepted:

```bash
./experiments/ardiff_comparison/run_one_benchmark.sh Airy/MAX/Eq
```

## Directory Layout

- `benchmarks/<Suite>/<Program>/<Eq|NEq>/`: original ARDiff cases.
- `benchmarks_typed/<Suite>/<Program>/<Eq|NEq>/`: typed C translation used by
  the maintained artifact pipeline.
- Each case contains `symbolic_oldV.c` and `symbolic_newV.c`.
- Generated files include compiled binaries, path files, timing reports, and
  equivalence reports.

## Requirements

- GCC for compiling C sources.
- Python with angr and z3-solver.
- The repository root on `PYTHONPATH`, or execution through the scripts shown
  above.
