[Evaluation](#evaluation)

# Symbolicana

Source repository for the binary equivalence-checking method, its pinned
benchmark inputs, benchmark archive, and audited run outputs.

## Requirements

The base image contains the symbolic-execution and solver toolchain. The
optional graph-reranking image adds the exact BinDiff/Ghidra stack used for the
recorded paper-benchmark run. The host needs Docker with Linux-container support
on an x86-64 machine.

| Component | Pinned version |
|---|---|
| Docker CLI / Engine | 29.6.1 |
| Docker Buildx | 0.35.0 |
| Base image | `docker.1ms.run/python:3.12-slim-bookworm` |
| Python | 3.12.15 |
| GCC | 12.2.0-14+deb12u1 (`-O3`) |
| angr / claripy | 9.2.192 |
| Z3 | 4.12.2 |
| BinDiff | 8 (`@568181968`, 2023-09-25) |
| Ghidra | 9.2.3 PUBLIC |
| BinExport | 12-20210517-rc4 |
| Java | Eclipse Temurin 11.0.32.1+1 |
| Platform | x86-64 Linux containers |

The exact image-level versions are also recorded in
[`environment.lock`](environment.lock). No host Python packages are needed when
using the Docker entry point.

## One-command runs

Build the image once and run all 130 unit tests:

```bash
python run_experiment.py --suite tests --rebuild
```

Run the fixed 62-case benchmark profile:

```bash
python run_experiment.py --suite paper --bindiff
```

Run all 272 OSF entries with automatic staging and retry:

```bash
python run_experiment.py --suite osf
```

Run both suites:

```bash
python run_experiment.py --suite all --bindiff
```

Useful options:

```bash
python run_experiment.py --suite paper --fresh --run-name paper-fresh
python run_experiment.py --suite paper --max-cases 1
python run_experiment.py --suite paper --image symbolicana-paper:latest
python run_experiment.py --suite paper --bindiff --rebuild
```

- `--fresh` discards cached path artifacts for the selected paper run.
- `--max-cases N` performs a short paper smoke run; full summaries and audits
  are emitted only when all 62 cases are requested.
- `--run-name NAME` selects `work/NAME/` and `results/rerun/NAME/` for a
  single suite.
- `--rebuild` rebuilds `symbolicana-paper:latest` from the supplied Dockerfile.
- `--bindiff` builds or uses `symbolicana-bindiff:latest` from
  `Dockerfile.bindiff` and enables real BinDiff graph mapping.
- `--image IMAGE` selects an existing compatible analysis image.

Without `--bindiff`, the base image uses the explicit structural graph fallback
and records the fallback in the path manifest. The optional BinDiff image pins
the official release assets by URL and can add roughly 450 MB of downloads to
the first build.

A full OSF run is intentionally sequential. Stage 1 uses 2048 paths, loop bound
30, and a 600-second symbolic-execution timeout per binary. Cases without
complete evidence are retried at 8192 paths, loop bound 128, and a 1200-second
timeout. Graph reranking is disabled for this coverage profile because the
primary failures are harness selection, path completion, and resource limits.
The fixed 62-case run uses BinDiff graph mapping when `--bindiff` is selected.
Resource failures remain visible in the audit.

With `--suite all`, the paper and OSF runs use separate directories. Their
defaults are `paper/` and `osf/`; an explicit `--run-name NAME` produces
`NAME_paper/` and `NAME_osf/` so one suite cannot overwrite the other.

Generated binaries, path constraints, rankings, replay logs, and caches are
written below `work/` and are excluded from version control. Full-run summaries
are written below `results/rerun/<run-name>/`. A full paper run also writes its
definedness audit to `results/rerun/<run-name>/ub_audit/`.

## Input domains

The paper benchmark profile uses integer and floating-point ranges
`[-100,100]`, except for the configured Ell overlay `[0,10]` and `[-1,1]`.
These settings are stored in
[`configs/paper_62_domains.csv`](configs/paper_62_domains.csv).

The OSF profile does not impose a numeric interval. Integer arguments cover the
complete signed 32-bit SMT bit-vector space, and floating-point arguments cover
the complete representable 32-bit SMT bit-vector space. Loop exploration still
has the explicit bounds above; the input-domain setting is not a hidden loop
heuristic.

## Benchmark inputs

The repository ships benchmark sources and manifests, but not generated paths:

```text
benchmark/
  osf_benchmarks.zip           all 272 official OSF C/Java entries
  ardiff/RunningBenchmarksOnLinux.sh
  LICENSE.md

configs/
  paper_62.csv                 62-case benchmark profile
  paper_62_domains.csv         per-family paper input domains
  paper_source_manifest.csv    source and artifact provenance
  osf_manifest.csv             all 272 OSF entries and support status
  osf_label_audit.csv          source-level label audit and UB overrides
```

Benchmark archive SHA-256:

```text
e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005
```

The archive is extracted to `work/benchmark_sources/` by the runner.

## Analysis pipeline

```text
OSF archive or 62-case profile
  -> select and wrap a supported entry point
  -> compile x86-64 ELF binaries with GCC -O3
  -> run angr symbolic execution and emit path summaries
  -> extract 11-dimensional path features
  -> rank, align, and bidirectionally cover candidate path pairs
  -> discharge input and observable-equivalence queries with Z3
  -> replay concrete NEQ witnesses on the original ELF binaries
  -> apply the source-free definedness heuristic
  -> emit final EQ / NEQ / UNK plus a per-candidate audit
```

The EQ contract includes the input space, function return value,
ordered program output, and final observable global memory. A NEQ verdict
requires a satisfying observable difference and successful replay on both
binaries. Symbolic output expressions are compared by SMT; canonical text is
not treated as a proof.

The source-free definedness stage does not require a sanitizer build. A witness
is classified as `asymmetric_ub_like` when one side has a clearly out-of-range
or undefined-derived execution while the other does not. That classification
can confirm a replayed NEQ. If both sides show the same undefined-like behavior,
the witness cannot establish a trustworthy difference. An undecidable UB status
is treated as NEQ by the explicit policy and is recorded in the audit.

## Evaluation

The tables below are pinned to the shipped result files. They are not
performance claims; cases exceeding a resource or exploration budget remain
UNK or failed.

### Fixed 62-case benchmark

| Metric | Result |
|---|---:|
| Correct | **58/62** |
| Correct EQ | **29/33** |
| Correct NEQ | **29/29** |
| Wrong | **0** |
| UNK | **4** |

The four UNK cases are `bess/bessi_Eq`, `bess/bessj_Eq`, `bess/bessk_Eq`, and
`bess/bessy_Eq`. In the fresh fixed-domain run, `gam/factrl_Eq` has no
definedness event and is a regular EQ result. In the complete-domain OSF audit
the same case remains UNK.

Machine-readable files:

- [Per-case results](results/paper/cases.csv)
- [Summary JSON](results/paper/summary.json)
- [Detailed audit](results/paper/summary.md)

### Complete OSF audit

All 272 official entries are accounted for. Of these, 244 can be staged by the
harness, 176 enter symbolic execution, and 150 have complete evidence on both
sides. The run obtains 129 correct determinate outcomes with zero wrong EQ and
zero wrong NEQ outcomes.

| Outcome | Cases |
|---|---:|
| Correct EQ | 64 |
| Correct NEQ | 65 |
| **Correct determinate** | **129** |
| Wrong EQ | 0 |
| Wrong NEQ | 0 |
| Label inconsistent | 5 |
| Undefined behavior excluded | 3 |
| UNK | 39 |
| Failed | 68 |
| Not attempted / unsupported | 28 |

Coverage and failure accounting:

| Metric | Cases |
|---|---:|
| Supported / staged | 244 |
| Entered symbolic execution | 176 |
| Both-side path artifacts | 165 |
| Both-side complete exploration | 150 |
| `unsupported_harness` | 28 |
| `sigkill_or_oom` | 44 |
| `symbolic_timeout` | 23 |
| `incomplete_symbolic_exploration` | 26 |
| `no_complete_paths` | 1 |
| `verifier_or_semantic_unknown` | 13 |

Per-family results:

| Family | Cases | Supported | Complete | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | UB | UNK | Failed | Not attempted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CLEVER | 50 | 50 | 50 | 27 | 20 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| REVE | 32 | 31 | 9 | 5 | 2 | 0 | 0 | 0 | 1 | 17 | 6 | 1 |
| airy | 12 | 10 | 10 | 4 | 5 | 0 | 0 | 1 | 0 | 0 | 0 | 2 |
| bess | 36 | 35 | 26 | 9 | 13 | 0 | 0 | 1 | 0 | 8 | 4 | 1 |
| caldat | 10 | 8 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 6 | 2 |
| dart | 2 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| ej_hash | 12 | 8 | 8 | 4 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| ell | 26 | 26 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 24 | 0 |
| frenel | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 5 | 0 |
| gam | 24 | 22 | 12 | 4 | 6 | 0 | 0 | 0 | 0 | 3 | 9 | 2 |
| optimization | 6 | 4 | 4 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 2 |
| pow | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ran | 22 | 22 | 5 | 3 | 2 | 0 | 0 | 0 | 0 | 3 | 14 | 0 |
| raytrace | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 |
| sine | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| statcalc | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| tcas | 8 | 6 | 6 | 0 | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 2 |
| tsafe | 8 | 8 | 8 | 2 | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 |

### Upstream ARDiff 142-case subset

| Cases | Supported | Entered SE | Complete | Correct EQ | Correct NEQ | Wrong | Label inconsistent | UB | UNK | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 142 | 142 | 99 | 93 | 38 | 43 | 0 | 2 | 1 | 15 | 43 |

### Comparison with the previous audited run

| Metric | Previous | Current | Change |
|---|---:|---:|---:|
| Supported | 232 | 244 | +12 |
| Entered symbolic execution | 146 | 176 | +30 |
| Both-side complete | 128 | 150 | +22 |
| Correct determinate | 110 | 129 | +19 |
| Wrong EQ / NEQ | 0 | 0 | 0 |

The improvement comes from broader harness support and staged path generation,
not from changing labels or converting resource failures into successes.

### Ordered-output witness

`gam/factln_Neq` is a correct NEQ under the output-inclusive contract. For
`n=-100`, both binaries return `0.0`, while the old binary prints
`Negative factorial in routine factln` and the new binary prints no such
message. The symbolic ordered-output check and native replay are recorded in
[`factln_neq_evidence.json`](results/osf/factln_neq_evidence.json).

### Label audit

The five entries below remain separate from correct counts because their
released C behavior conflicts with the official label:

| Case | Official label | Evidence |
|---|---|---|
| `CLEVER/fib_Eq` | EQ | Replay `x=2`: old returns 1, new returns 2 |
| `CLEVER/is_prime1_Neq` | NEQ | Both released C files have the same SHA-256 |
| `CLEVER/is_prime2_Eq` | EQ | Replay `x=19`: old returns 0, new returns 1 |
| `airy/Sign_Eq` | EQ | Special-value replay changes the sign of the smallest subnormal |
| `bess/SIGN_Eq` | EQ | Same source-level special-value defect |

The three final UB exclusions are:

| Case | Evidence |
|---|---|
| `REVE/loop5_Eq` | Full-domain witness overflows signed `int` in `n+n` |
| `dart/test_Eq` | Full-domain witness overflows signed `int` in `x*x*x` |
| `optimization/theta_Neq` | Both harnesses print a `double` with `%d`, producing unstable output |

Detailed OSF data:

- [Per-case OSF results](results/osf/cases.csv)
- [OSF summary JSON](results/osf/summary.json)
- [OSF summary Markdown](results/osf/summary.md)
- [Family summary](results/osf/family_summary.csv)
- [Failure categories](results/osf/failure_summary.csv)
- [Failure cases](results/osf/failure_cases.csv)
- [Upstream 142 summary](results/osf/upstream_142_summary.csv)
- [Previous/current changes](results/osf/baseline_changes.csv)
- [Definedness audit](results/osf/ub_cases.csv)
- [Label audit](results/osf/label_audit.csv)
- [Ordered-output NEQ witness](results/osf/factln_neq_evidence.json)
- [Full methodology and run audit](RESULTS_AUDIT.md)

Validate the shipped tables without regenerating paths:

```bash
python scripts/validate_delivery_results.py
```

## Repository layout

```text
src/symbolic_analysis/          feature extraction and path matching
scripts/run_suite.py            one-command suite driver
build_ardiff_path_benchmarks.py path generation and orchestration
run_experiment.py               host-side Docker entry point
run_evaluation.py               Hybrid verification driver
configs/                        benchmark inputs and audited labels
benchmark/                      source archive and upstream license
results/                        curated, path-free result tables
tests/                           unit and integration checks
```

## Limitations

The full OSF run is not complete for every entry. In particular, 44 cases were
terminated by the kernel, 23 hit the symbolic timeout, and 26 had incomplete
exploration. An isolated one-container retry of `REVE/ackermann_Eq` still drove
the Docker/WSL VM to roughly 14 GB and caused the daemon to terminate, so the
failure is not merely four-way contention. These cases are reported as failed
or UNK rather than silently dropped. The source-free UB heuristic is a triage
rule for replayed witnesses, not a proof of general program definedness.

## License

The source code is provided under the [MIT License](LICENSE). The bundled OSF
and ARDiff benchmark material retains the upstream terms in
[`benchmark/LICENSE.md`](benchmark/LICENSE.md).
