# ardiff_comparison Benchmarks

This directory contains program pairs (oldV vs newV) for equivalence checking. Each case has C sources `symbolic_oldV.c` and `symbolic_newV.c`; the enhanced analyzer compares their path constraints and program output.

## How to run a single benchmark

### 1. Compile both programs

From the **benchmark case directory** (e.g. `benchmarks/Airy/MAX/Eq`):

```bash
cd experiments/ardiff_comparison/benchmarks/Airy/MAX/Eq
gcc -o symbolic_oldV symbolic_oldV.c
gcc -o symbolic_newV symbolic_newV.c
```

### 2. Run symbolic execution (generate path constraint files)

Run from the **same directory** so that `*_path_*.txt` files are written there. Adjust the path to `scripts` if your repo root is different (from `Eq` go up 6 levels to repo root).

```bash
# From symbolic_analysis repo root
cd experiments/ardiff_comparison/benchmarks/Airy/MAX/Eq

python3 ../../../../../../scripts/se_script_improved.py --binary ./symbolic_oldV
python3 ../../../../../../scripts/se_script_improved.py --binary ./symbolic_newV
```

This produces `symbolic_oldV_path_1.txt`, `symbolic_oldV_path_2.txt`, ... and `symbolic_newV_path_1.txt`, ...

### 3. Run equivalence analysis

Still in the same directory:

```bash
python3 ../../../../../../scripts/ardiff_comparison/semantic_equivalence_analyzer_enhanced.py \
  symbolic_oldV_path symbolic_newV_path \
  --output enhanced_equivalence_report.txt
```

The report is written to `enhanced_equivalence_report.txt` in that directory.

## One-command helper (from repo root)

Use the provided script to do all steps for one case:

```bash
# From symbolic_analysis repo root
./experiments/ardiff_comparison/run_one_benchmark.sh experiments/ardiff_comparison/benchmarks/Airy/MAX/Eq
```

Short form (case path under `ardiff_comparison/benchmarks/`):

```bash
./experiments/ardiff_comparison/run_one_benchmark.sh Airy/MAX/Eq
```

Or with an absolute path:

```bash
./experiments/ardiff_comparison/run_one_benchmark.sh ./experiments/ardiff_comparison/benchmarks/Airy/MAX/Eq
```

## Directory layout

- `benchmarks/<Suite>/<Prog>/<Eq|NEq>/` — one case per directory.
- Each case contains:
  - `symbolic_oldV.c`, `symbolic_newV.c` — C sources (with `scanf` for symbolic input).
  - After running: `symbolic_oldV`, `symbolic_newV` (binaries), `*_path_*.txt` (path constraints), `enhanced_equivalence_report.txt` (report).

## Requirements

- **gcc** to compile the C files.
- **Python 3** with **angr** and **z3** (and project on `PYTHONPATH` or run scripts by path as above).
- Scripts are under `scripts/` and `scripts/ardiff_comparison/` from this project root.
