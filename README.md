# Symbolicana

Symbolicana is a standalone symbolic-analysis toolkit for binary path
generation, path-pair ranking, and path equivalence verification.

The main pipeline is:

1. Generate SMT path constraints from a binary with angr.
2. Rank candidate old/new paths with 11-dimensional constraint features plus
   optional BinDiff-style trace overlap reranking.
3. Verify ranked path candidates with Z3.

## Install

Use Python 3.10-3.13. Python 3.12 is recommended for angr compatibility.

```bash
cd symbolic_analysis
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

If you only want the dependency list:

```bash
pip install -r requirements.txt
```

Check the runtime environment:

```bash
symbolicana check-deps
```

If your environment is offline and cannot install build tools, run directly
from the source checkout:

```bash
cd symbolic_analysis
PYTHONPATH=src python -m symbolic_analysis.cli check-deps
```

## Command-Line Interface

After `pip install -e .`, the `symbolicana` command is available.
Without installation, replace `symbolicana` with:

```bash
PYTHONPATH=src python -m symbolic_analysis.cli
```

### 1. Symbolic Execution

Generate path files for one binary:

```bash
symbolicana symbolic-exec \
  --binary /path/to/binary \
  --output-prefix outputs/oldV \
  --timeout 120
```

For ARDiff-style `snippet` functions, pass the function signature so floating
point and integer arguments are placed in the correct ABI registers:

```bash
symbolicana symbolic-exec \
  --binary /path/to/symbolic_oldV \
  --output-prefix outputs/symbolic_oldV \
  --signature 'double(double,int)' \
  --timeout 120
```

This writes files named like:

```text
outputs/symbolic_oldV_path_1.txt
outputs/symbolic_oldV_path_2.txt
```

### 2. Feature Vectors

Generate the 11-dimensional path-constraint feature vectors:

```bash
symbolicana vectors \
  --paths-dir outputs \
  --normalize \
  --include-min-max \
  --out outputs/path_vectors.json
```

### 3. Path Ranking

Rank old paths against new paths:

```bash
symbolicana rank \
  --old-paths-dir outputs \
  --new-paths-dir outputs \
  --old-prefix symbolic_oldV \
  --new-prefix symbolic_newV \
  --out outputs/ranking.json
```

Optional graph evidence can be supplied as a JSON basic-block matching map:

```bash
symbolicana rank \
  --old-paths-dir outputs \
  --new-paths-dir outputs \
  --old-prefix symbolic_oldV \
  --new-prefix symbolic_newV \
  --matching-bb-map bindiff_basic_block_map.json \
  --out outputs/ranking.json
```

### 4. Ranked Equivalence Verification

Verify ranked path candidates:

```bash
symbolicana verify \
  --paths-dir outputs \
  --ranking outputs/ranking.json \
  --out outputs/verification_report.json \
  --program-ground-truth true
```

Run the all-vs-all baseline:

```bash
symbolicana verify \
  --paths-dir outputs \
  --naive \
  --out outputs/naive_report.json
```

## Python Package Layout

```text
src/symbolic_analysis/
  analysis/              Feature extraction and hybrid path matching
  equivalence/           Z3-based equivalence utilities
  symbolic_execution/    Symbolic-execution helpers
  tracing.py             JSONL timing / SMT-call tracing
  cli.py                 `symbolicana` command

scripts/
  se_script_improved.py              angr path generation driver
  verify_ranked_path_equivalence.py  ranked equivalence verifier
  *_path_similarity*.py              legacy ranking scripts
```

## Notes

- `results.json` and `results.csv` store timing values in seconds.
- Markdown summaries display timing in seconds.
- The current floating-point return equivalence mode compares numeric equality,
  treats `+0.0` and `-0.0` as equal, and treats NaN payload/sign differences as
  one abstract NaN result. To keep full benchmark runs practical, individual
  return-value SMT checks are capped at 5 seconds.
