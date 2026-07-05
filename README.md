# Symbolicana

Symbolicana is a symbolic-analysis artifact for binary equivalence-checking
experiments. Given two versions of a program, the pipeline symbolically executes
both binaries, ranks old/new path pairs, and verifies path-level equivalence with
Z3.

The maintained equivalence definition has three layers:

1. Equivalent input spaces.
2. Equivalent return values over compatible input regions.
3. Equivalent non-local state, including heap and global state.

A semantic region is treated as equivalent only when all three layers hold. The
verification reports record this contract in the `semantic_definition` field.

## Repository Layout

```text
symbolic_analysis/
  README.md
  Dockerfile
  requirements.txt
  pyproject.toml
  setup.py

  src/symbolic_analysis/
    analysis/              11-dimensional path features, cosine ranking, hybrid matching
    equivalence/           equivalence-analysis code
    symbolic_execution/    symbolic-execution wrappers
    tracing.py             timing and SMT-call tracing
    cli.py                 command-line entry point

  scripts/
    se_script_improved.py              angr symbolic-execution script
    verify_ranked_path_equivalence.py  three-layer semantic verifier
    generate_path_feature_vectors.py   path-feature extraction
    path_similarity_batch.py           batch cosine ranking
    hybrid_path_similarity_batch.py    hybrid ranking

  experiments/ardiff_comparison/
    benchmarks/            original ARDiff C benchmarks
    benchmarks_typed/      typed C translation that preserves Java source types where possible

  benchmarks/
    ardiff_paths/          generated ARDiff path benchmark
    ardiff_paths_typed/    generated typed ARDiff path benchmark
    tsvc_paths/            generated TSVC path benchmark
```

External comparison tools are expected outside this repository:

```text
../VeriBin
../pldi19-equivalence-checker
```

The project can run its own path-ranking and evaluation scripts without those
external tools. If a real VeriBin installation is unavailable, the evaluation
uses the VeriBin-style ranking files bundled in the benchmark artifacts.

## Docker Quick Start

Build the reproducibility image from the repository root:

```bash
docker build -t symbolicana-artifact .
```

Check that Python, angr, claripy, and Z3 are available:

```bash
docker run --rm symbolicana-artifact symbolicana check-deps
```

Run the typed ARDiff evaluation on the path benchmark already present in the
repository:

```bash
docker run --rm -v "$PWD/evaluation_results:/workspace/symbolic_analysis/evaluation_results" \
  symbolicana-artifact \
  python run_evaluation.py \
    --benchmarks benchmarks/ardiff_paths_typed \
    --ground-truth benchmarks/ardiff_paths_typed/groundtruth.json \
    --output-dir evaluation_results \
    --execute
```

Rebuild the typed ARDiff path benchmark from C sources, rerun symbolic execution,
and then run evaluation:

```bash
docker run --rm -v "$PWD/evaluation_results_ardiff_typed:/workspace/symbolic_analysis/evaluation_results_ardiff_typed" \
  symbolicana-artifact \
  python build_ardiff_path_benchmarks.py \
    --python python \
    --timeout 120 \
    --benchmarks experiments/ardiff_comparison/benchmarks_typed \
    --out-dir benchmarks/ardiff_paths_typed \
    --eval-output-dir evaluation_results_ardiff_typed \
    --force-symbolic-exec
```

The full rebuild may take a long time because every old/new binary pair is
compiled, symbolically executed, ranked, and verified.

## Local Installation

Python 3.12 is recommended. Python 3.10 through 3.13 is supported by the package
metadata.

```bash
python -m venv .venv312
source .venv312/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install -e .
symbolicana check-deps
```

On Windows, use:

```powershell
python -m venv .venv312
.\.venv312\Scripts\Activate.ps1
pip install -U pip
pip install -r requirements.txt
pip install -e .
symbolicana check-deps
```

## Fast Evaluation From Existing Paths

Use this when you want to test the evaluation pipeline without rerunning symbolic
execution:

```bash
python run_evaluation.py \
  --benchmarks benchmarks/ardiff_paths_typed \
  --ground-truth benchmarks/ardiff_paths_typed/groundtruth.json \
  --output-dir evaluation_results_ardiff_typed \
  --execute
```

The output directory contains:

```text
results.csv
results.json
summary.md
subset_summary.md
final_summary.md
logs/
```

`results.json` is the most complete machine-readable result. `summary.md` and
`final_summary.md` are the human-readable tables used for quick inspection.

## Full Reproduction From Source

To compile the typed ARDiff C programs, rerun symbolic execution, regenerate
manifest/ranking files, and evaluate:

```bash
python build_ardiff_path_benchmarks.py \
  --python python \
  --timeout 120 \
  --benchmarks experiments/ardiff_comparison/benchmarks_typed \
  --out-dir benchmarks/ardiff_paths_typed \
  --eval-output-dir evaluation_results_ardiff_typed \
  --force-symbolic-exec
```

To regenerate benchmark files without evaluation:

```bash
python build_ardiff_path_benchmarks.py \
  --python python \
  --timeout 120 \
  --benchmarks experiments/ardiff_comparison/benchmarks_typed \
  --out-dir benchmarks/ardiff_paths_typed \
  --eval-output-dir evaluation_results_ardiff_typed \
  --skip-evaluation
```

To rebuild only the manifest, ground truth, and rankings from existing path
files:

```bash
python build_ardiff_path_benchmarks.py \
  --python python \
  --benchmarks experiments/ardiff_comparison/benchmarks_typed \
  --out-dir benchmarks/ardiff_paths_typed \
  --skip-symbolic-exec \
  --skip-evaluation
```

## Single-Binary Workflow

Generate path constraints:

```bash
python -m symbolic_analysis.cli symbolic-exec \
  --binary /path/to/symbolic_oldV \
  --output-prefix outputs/symbolic_oldV \
  --signature 'double(double,double)' \
  --timeout 120
```

Generate path-feature vectors:

```bash
python -m symbolic_analysis.cli vectors \
  --paths-dir outputs \
  --normalize \
  --include-min-max \
  --out outputs/path_vectors.json
```

Rank old/new paths:

```bash
python -m symbolic_analysis.cli rank \
  --old-paths-dir outputs \
  --new-paths-dir outputs \
  --old-prefix symbolic_oldV \
  --new-prefix symbolic_newV \
  --out outputs/ranking.json
```

Verify three-layer semantic equivalence:

```bash
python -m symbolic_analysis.cli verify \
  --paths-dir outputs \
  --ranking outputs/ranking.json \
  --out outputs/verification_report.json \
  --program-ground-truth true
```

## Evaluation Methods

`run_evaluation.py` compares three strategies:

```text
Naive    compare every old path with every new path
VERIBIN  use VeriBin/BinDiff-style ranking or bundled VeriBin-style rankings
Ours     11-dimensional path features plus cosine and hybrid graph evidence
```

Primary metrics:

```text
ACC %       final equivalent/non-equivalent accuracy against ground truth
Hit@1 %     whether the correct path is ranked first
Hit@3 %     whether the correct path is ranked in the top three
MRR         mean reciprocal rank
T_se        symbolic-execution time
T_align     path-ranking/alignment time
T_smt       Z3 solving time
Pruning %   SMT-call reduction relative to all-vs-all matching
```

Timing values in `summary.md` and `final_summary.md` are reported in seconds.

## Notes For Artifact Review

- Generated binaries, path files, logs, and evaluation outputs are intentionally
  ignored by `.gitignore` and `.dockerignore` where possible.
- The Docker image installs GCC and Python dependencies, then installs this
  package in editable mode.
- The symbolic executor supports both Windows x64 ABI conventions and Linux
  SysV AMD64 conventions, so the same benchmark sources can be rebuilt inside
  Docker on Linux.
- External tools such as VeriBin and the PLDI19 equivalence checker are not
  vendored into this artifact.

## Troubleshooting

If `angr`, `claripy`, or `z3` cannot be imported, confirm that the active Python
environment is the one used for installation:

```bash
python -m symbolic_analysis.cli check-deps
```

If evaluation produces only a dry-run result, add `--execute` to
`run_evaluation.py`.

If symbolic execution produces empty path files, rebuild the benchmark binaries
with the local GCC and rerun `build_ardiff_path_benchmarks.py` with
`--force-symbolic-exec`.
