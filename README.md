# Symbolicana

[Evaluation](#evaluation)

Symbolicana implements the binary equivalence-checking method described in
the accompanying paper. It symbolically executes two program versions,
extracts 11-dimensional path features, ranks old/new path pairs, and checks
input-space, return-value, ordered program-output, and global-state
equivalence with Z3.

## Requirements

- Docker with Linux container support, x86-64.
- Tested Docker CLI/Engine 29.6.1 and Buildx 0.35.0.
- Base image: `python:3.12-slim-bookworm` (pulled from
  `docker.1ms.run/python:3.12-slim-bookworm`).
- Python 3.12.15 inside the supplied image.
- GCC 12.2.0-14+deb12u1 with `-O3`.
- angr 9.2.192 and claripy 9.2.192.
- Z3 4.12.2.
- Loop bound `30`.
- Symbolic-execution timeout `600` seconds per binary.
- SMT timeout `60` seconds per path-pair query.

The Dockerfile installs the Python, GCC, angr/claripy, and Z3 versions above.
No host Python packages are required when using the Docker entry point.

## One-Command Run

Run the paper benchmark:

```bash
python run_experiment.py --suite paper
```

The entry point builds `symbolicana-paper:latest` when needed, runs the test
suite, prepares the benchmark, generates paths, runs Hybrid verification, and
writes the evaluation tables under `results/rerun/paper/`.

The current image passes all 53 unit tests.

Other entry points:

```bash
python run_experiment.py --suite tests
python run_experiment.py --suite osf
python run_experiment.py --suite all
python run_experiment.py --suite paper --max-cases 3
python run_experiment.py --suite paper --fresh
```

- `--suite paper` runs the paper benchmark.
- `--suite osf` runs all supported OSF cases plus the documented Ell and
  full-bit-vector TCAS profiles.
- `--suite all` runs both suites.
- `--max-cases` limits each profile for a smoke run.
- `--fresh` regenerates path artifacts instead of resuming from `work/`.
- `--rebuild` rebuilds the Docker image.

Generated paths, binaries, rankings, and logs are written under `work/` and
are intentionally excluded from version control.

## Docker Equivalents

The one-command script performs the following equivalent operations:

```bash
docker build -t symbolicana-paper .

docker run --rm --network none \
  -v "$PWD:/workspace/symbolicana" \
  -w /workspace/symbolicana \
  symbolicana-paper \
  python scripts/run_suite.py --suite paper
```

For an interactive shell:

```bash
docker run --rm -it \
  -v "$PWD:/workspace/symbolicana" \
  -w /workspace/symbolicana \
  symbolicana-paper bash
```

## Benchmark Inputs

The repository ships benchmark sources and result tables, but not generated
path files.

```text
benchmark/
  osf_benchmarks.zip           official 272-case C/Java archive
  ardiff/RunningBenchmarksOnLinux.sh
  LICENSE.md

configs/
  paper_candidates.csv         72 paper candidates
  paper_62_exclude_erfcc.csv   62-case evaluation set
  ell_cases.csv                bounded-domain Ell cases
  tcas_cases.csv               full-bit-vector TCAS cases
  osf_manifest.csv             all 272 OSF entries and support status
  osf_label_audit.csv          audited label classifications
```

The main OSF profile uses integer and floating-point ranges `[-100,100]`.
The Ell overlay uses integer `[0,10]` and floating-point `[-10,10]`. TCAS
cases use the complete signed 32-bit integer domain. These profiles are
explicit inputs to the runner, not hidden defaults.

The benchmark archive SHA-256 is
`e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005`.
The runner extracts it to `work/benchmark_sources/`.

## Pipeline

```text
C/Java benchmark
  -> prepare C entry harnesses
  -> compile x86-64 ELF binaries with GCC -O3
  -> angr symbolic execution and path summaries
  -> 11-dimensional feature extraction
  -> cosine ranking plus basic-block trace reranking
  -> bidirectional path coverage
  -> Z3 checks for return, ordered output, and global-state equivalence
  -> native ELF replay for NEQ witnesses
  -> per-case CSV and Markdown summaries
```

The equivalence contract used for EQ is:

```text
input-space equivalence
and function-return equivalence
and ordered program-output equivalence
and final globally observable memory-state equivalence
```

NEQ requires a satisfying observable difference and successful replay on both
ELF binaries. Replayed stdout and stderr are both compared. Path summaries
record ordered output from `printf`, `fprintf`, `puts`, `fputs`, `putchar`,
`fputc`, and `putc`; `fflush` is intercepted to avoid host I/O.

## Repository Layout

```text
src/symbolic_analysis/
  analysis/                 path features and hybrid path matching
  cli.py                    standalone CLI
scripts/
  se_script_improved.py     symbolic execution
  verify_ranked_path_equivalence.py
  prepare_osf_all.py
  summarize_osf_all.py
  run_suite.py              one-command suite driver
run_experiment.py           host-side Docker entry point
run_evaluation.py           method evaluator
build_ardiff_path_benchmarks.py
results/                    delivered experiment tables
tests/                      unit and integration tests
```

## Evaluation

### Paper Benchmark

The 62-case Hybrid evaluation contains 58 correct determinate verdicts,
0 incorrect determinate verdicts, and 4 UNK results.

| Method | Cases | Correct | Wrong | UNK | Verifier failures | Hit@1 | Hit@3 | MRR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Hybrid | 62 | 58 | 0 | 4 | 0 | 75.95% | 80.06% | 0.7894 |

Per-case paper results:
[results/paper/hybrid_cases.csv](results/paper/hybrid_cases.csv)

### Complete OSF Results

All 272 source cases are accounted for. Three rows are classified as
`label_inconsistent` after source-level audit: one OSF `Neq` pair has
byte-identical C inputs and two `Eq` labels have concrete differing return
values in the released C code. The raw official labels and predictions remain
in `results/osf/cases.csv`. There are zero algorithmic false-positive
(`wrong_eq`) results and zero algorithmic false-negative (`wrong_neq`) results
after this audit.

Audited cases: `CLEVER/fib_Eq`, `CLEVER/is_prime1_Neq`,
and `CLEVER/is_prime2_Eq`.

`gam/factln_Neq` is a correct NEQ under the output-inclusive contract. For
`n=-100`, both binaries return `0.0`, but the old binary prints
`Negative factorial in routine factln` and the new binary prints no such
message. The path-level output comparison and native replay are recorded in
[results/osf/factln_neq_evidence.json](results/osf/factln_neq_evidence.json).
A source-level scan of the 151 cases with complete path evidence found four
pairs whose active output-call lines differ: `airy/chebev_c1d_NEq` (already
NEQ), `gam/factln_Eq` (comment-only difference), `gam/factln_Neq` (this
re-evaluation), and `statcalc/addValue_NEq` (UNK). No other completed
correct-EQ case has an output-only difference.

| Outcome | All 272 OSF cases | Upstream ARDiff 142 |
|---|---:|---:|
| Correct EQ | 67 | 40 |
| Correct NEQ | 52 | 36 |
| Wrong EQ | 0 | 0 |
| Wrong NEQ | 0 | 0 |
| Label inconsistent | 3 | 0 |
| UNK | 29 | 11 |
| Verifier process failure | 0 | 0 |
| Not run: path failure or unsupported entry | 121 | 55 |

Per-family results:

| Family | Cases | Supported | Complete paths | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | UNK | Not run |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| airy | 12 | 8 | 8 | 2 | 3 | 0 | 0 | 0 | 3 | 4 |
| bess | 36 | 35 | 24 | 10 | 10 | 0 | 0 | 0 | 4 | 12 |
| caldat | 10 | 8 | 4 | 1 | 1 | 0 | 0 | 0 | 2 | 6 |
| CLEVER | 50 | 50 | 50 | 27 | 20 | 0 | 0 | 3 | 0 | 0 |
| dart | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| ej_hash | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| ell | 26 | 26 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 24 |
| frenel | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |
| gam | 24 | 22 | 10 | 3 | 4 | 0 | 0 | 0 | 3 | 14 |
| optimization | 6 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 4 |
| pow | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| ran | 22 | 22 | 7 | 2 | 2 | 0 | 0 | 0 | 3 | 15 |
| raytrace | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| REVE | 32 | 31 | 26 | 13 | 4 | 0 | 0 | 0 | 9 | 6 |
| sine | 2 | 2 | 2 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| statcalc | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |
| tcas | 8 | 6 | 6 | 2 | 3 | 0 | 0 | 0 | 1 | 2 |
| tsafe | 8 | 8 | 4 | 2 | 1 | 0 | 0 | 0 | 1 | 4 |

Machine-readable results:

- [Per-case OSF results](results/osf/cases.csv)
- [Upstream 142-case results](results/osf/upstream_142_cases.csv)
- [Family summary](results/osf/family_summary.csv)
- [Overall summary](results/osf/summary.csv)
- [Label audit](results/osf/label_audit.csv)

The recorded runs include two UNK/timeout closes for
`sine/mysin_Neq` and `tsafe/conflict_Neq`. They are counted as UNK, not as
correct or incorrect.

## Result Table Check

The delivered result tables can be checked without regenerating paths:

```bash
python - <<'PY'
import csv
from pathlib import Path

root = Path("results")
paper = list(csv.DictReader((root / "paper/hybrid_cases.csv").open()))
osf = list(csv.DictReader((root / "osf/cases.csv").open()))

assert len(osf) == 272
assert len(paper) == 62
assert sum(r["osf_outcome"] == "wrong_eq" for r in osf) == 0
assert sum(r["osf_outcome"] == "label_inconsistent" for r in osf) == 3
assert sum(r["osf_outcome"] == "unk" for r in osf) == 29
print("paper and OSF result tables validated")
PY
```

## License

The OSF benchmark sources are distributed under the license in
[benchmark/LICENSE.md](benchmark/LICENSE.md).

Packaging checks are listed in
[DELIVERY_CHECKLIST.md](DELIVERY_CHECKLIST.md).
