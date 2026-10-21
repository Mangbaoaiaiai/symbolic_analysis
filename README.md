[Evaluation](#evaluation)

# Symbolicana

Source repository for the binary equivalence-checking implementation, its
pinned benchmark inputs, the 272-entry OSF manifest, and path-free audited
result tables.

## Requirements

The host needs an x86-64 machine with Docker and Linux-container support. The
container supplies the symbolic executor, SMT solver, and pinned C toolchain.

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

The machine-readable version lock is
[`environment.lock`](environment.lock). The numeric OSF experiment uses
complete 32-bit SMT input spaces; the fixed 62-case profile uses the domains in
[`configs/paper_62_domains.csv`](configs/paper_62_domains.csv).

## One-command runs

Build the analysis image and run all 158 unit/integration tests:

```bash
python run_experiment.py --suite tests --rebuild
```

Run the fixed 62-case benchmark with the pinned BinDiff graph backend:

```bash
python run_experiment.py --suite paper --bindiff
```

Run all 272 OSF entries with automatic staging and retry:

```bash
python run_experiment.py --suite osf
```

Run the fixed benchmark and OSF suites sequentially:

```bash
python run_experiment.py --suite all --bindiff
```

Useful controls:

```bash
python run_experiment.py --suite paper --fresh --run-name paper_fresh
python run_experiment.py --suite paper --max-cases 1
python run_experiment.py --suite paper --image symbolicana-paper:latest
python run_experiment.py --suite paper --bindiff --rebuild
```

- `--fresh` removes cached path artifacts for the selected run.
- `--run-name NAME` writes generated data to `work/NAME/` and curated results
  to `results/rerun/NAME/`.
- `--max-cases N` runs a smoke subset; complete suite summaries are emitted
  only for the full case count.
- `--rebuild` rebuilds the base analysis image.
- `--bindiff` builds or reuses the optional BinDiff image.
- `--image IMAGE` selects an existing compatible analysis image.

Without `--bindiff`, the fixed benchmark uses the explicit structural graph
fallback and records that choice in the path manifest. The optional BinDiff
image pins the upstream release assets and adds roughly 450 MB to the first
build.

The OSF suite is sequential. Its first stage uses 2048 paths, loop bound 30,
and a 600-second timeout per binary. Cases without complete evidence are
retried with 8192 paths, loop bound 128, and a 1200-second timeout per binary.
OSF path generation enables the loaded ELF constant and initializer tables.
Graph reranking is disabled for this coverage profile because the dominant
residual failures are entry extraction, path growth, and resource limits.

With `--suite all`, the two suites use separate directories. Defaults are
`paper/` and `osf/`; a shared `--run-name NAME` produces `NAME_paper/` and
`NAME_osf/`.

Generated binaries, path constraints, rankings, replay logs, and caches are
written below `work/` and are ignored by Git. Full-run artifacts are written
below `results/rerun/<run-name>/`. The curated release tables under `results/`
contain no generated path files, binaries, or local workspace paths.

## Input domains

The fixed 62-case profile uses integer and floating-point ranges `[-100,100]`,
with Ell overrides `[0,10]` and `[-1,1]`. These are benchmark assumptions in
[`configs/paper_62_domains.csv`](configs/paper_62_domains.csv).

The OSF profile imposes no numeric interval: integer arguments cover the full
signed 32-bit SMT bit-vector space and floating-point arguments cover the full
representable 32-bit SMT bit-vector space. Loop bounds remain explicit
exploration limits and are reported separately in the audit.

## Benchmark inputs

The repository distributes the benchmark sources and manifests, but not
generated paths:

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
  osf_entry_overrides.json     explicit entry, aggregate, and type layouts
  osf_label_audit.csv          source-level label and behavior audit
```

Benchmark archive SHA-256:

```text
e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005
```

The runner extracts the archive into `work/benchmark_sources/`.

## Analysis pipeline

```text
OSF archive or fixed 62-case manifest
  -> select and wrap supported entry points or declared target aggregates
  -> flatten configured structs and arrays into explicit scalar inputs
  -> compile x86-64 ELF binaries with GCC -O3
  -> run angr symbolic execution and stream path summaries to disk
  -> extract 11-dimensional path features
  -> rank, align, and bidirectionally cover candidate path pairs
  -> discharge input and observable-equivalence queries with Z3
  -> replay concrete NEQ witnesses on the original binaries
  -> apply the source-free definedness heuristic
  -> emit EQ / NEQ / UNK and a per-candidate audit
```

The equality contract includes the input space, function return value,
ordered program output, and final observable global memory. A NEQ verdict
requires a satisfying observable difference and successful replay on both
binaries. Path conditions and return/output summaries are proved by SMT;
canonical text matching is not accepted as an equivalence proof.

The source-free definedness stage does not require a sanitizer build. A
replayed witness is classified as `asymmetric_ub_like` when one side has a
clearly out-of-range or undefined-derived execution while the other does not.
That classification can confirm NEQ. If both sides show the same undefined-like
behavior, the witness cannot establish a trustworthy difference. An
undecidable UB status follows the explicit policy `unknown_as_neq` and remains
visible in the audit.

## Evaluation

All tables below are generated from the shipped result files. Resource and
exploration failures remain UNK or failed; they are never counted as correct.

### Fixed 62-case benchmark

| Metric | Result |
|---|---:|
| Correct | **58/62** |
| Correct EQ | **29/33** |
| Correct NEQ | **29/29** |
| Wrong | **0** |
| UNK | **4** |

The four UNK cases are `bess/bessi_Eq`, `bess/bessj_Eq`, `bess/bessk_Eq`, and
`bess/bessy_Eq`. Under the fixed benchmark domains, `gam/factrl_Eq` is a
regular EQ result. Its complete-input-space OSF counterpart remains UNK.

Machine-readable files:

- [Per-case results](results/paper/cases.csv)
- [Summary JSON](results/paper/summary.json)
- [Detailed audit](results/paper/summary.md)

### Provisional complete OSF audit

> **Provisional merged audit.** This table combines the previous 272-entry
> full audit with targeted results from the newest OSF entry/type adaptation.
> The 27 replaced cases are 21 formerly unsupported aggregate/multi-target
> entries and 6 complex struct/return cases. This is not yet a single
> end-to-end run of the latest revision. The summary JSON records
> `provisional: true` and `full_osf_rerun_complete: false`.

All 272 official entries are accounted for:

| Outcome | Cases |
|---|---:|
| Correct EQ | **72** |
| Correct NEQ | **75** |
| **Correct determinate** | **147** |
| Wrong EQ | 0 |
| Wrong NEQ | 0 |
| Label inconsistent | 5 |
| Undefined behavior excluded | 3 |
| UNK | 43 |
| Failed | 73 |
| Not attempted / unsupported | 1 |

Coverage and failure accounting:

| Metric | Cases |
|---|---:|
| Supported / staged | 271 |
| Entered symbolic execution | 198 |
| Both-side path artifacts | 185 |
| Both-side complete exploration | 170 |
| Incomplete exploration | 28 |
| No path artifact | 73 |
| `symbolic_timeout` | 28 |
| `sigkill_or_oom` | 46 |
| `incomplete_symbolic_exploration` | 26 |
| `verifier_or_semantic_unknown` | 15 |
| `no_complete_paths` | 1 |
| `unsupported_harness` | 1 |

The only unsupported entry is `REVE/average_Eq`: its source declares
`int a[]` without an array extent, so the harness does not substitute an
arbitrary fixed length for the complete input space.

Per-family results:

| Family | Cases | Supported | Complete | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | UB | UNK | Failed | Not attempted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CLEVER | 50 | 50 | 50 | 27 | 20 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| REVE | 32 | 31 | 9 | 5 | 2 | 0 | 0 | 0 | 1 | 17 | 6 | 1 |
| airy | 12 | 12 | 12 | 4 | 6 | 0 | 0 | 1 | 0 | 1 | 0 | 0 |
| bess | 36 | 36 | 26 | 9 | 13 | 0 | 0 | 1 | 0 | 8 | 5 | 0 |
| caldat | 10 | 10 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 8 | 0 |
| dart | 2 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| ej_hash | 12 | 12 | 12 | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ell | 26 | 26 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 24 | 0 |
| frenel | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 5 | 0 |
| gam | 24 | 24 | 12 | 4 | 6 | 0 | 0 | 0 | 0 | 3 | 11 | 0 |
| optimization | 6 | 6 | 6 | 2 | 2 | 0 | 0 | 0 | 1 | 1 | 0 | 0 |
| pow | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ran | 22 | 22 | 5 | 3 | 2 | 0 | 0 | 0 | 0 | 3 | 14 | 0 |
| raytrace | 12 | 12 | 12 | 5 | 6 | 0 | 0 | 0 | 0 | 1 | 0 | 0 |
| sine | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| statcalc | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| tcas | 8 | 8 | 6 | 0 | 3 | 0 | 0 | 0 | 0 | 5 | 0 | 0 |
| tsafe | 8 | 8 | 8 | 2 | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 |

The upstream ARDiff subset is reported separately so its denominator is not
mixed with the complete OSF set:

| Cases | Supported | Entered SE | Complete | Correct EQ | Correct NEQ | Wrong | Label inconsistent | UB | UNK | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 142 | 142 | 99 | 93 | 38 | 43 | 0 | 2 | 1 | 15 | 43 |

Comparison with the previous full audit before the 27 targeted replacements:

| Metric | Previous | Provisional | Change |
|---|---:|---:|---:|
| Supported | 244 | 271 | +27 |
| Entered symbolic execution | 176 | 198 | +22 |
| Both-side complete | 150 | 170 | +20 |
| Correct determinate | 129 | 147 | +18 |
| Wrong EQ / NEQ | 0 / 0 | 0 / 0 | 0 |

The increase is attributable to explicit multi-target wrappers, configured
struct/array inputs, aggregate returns, concrete ELF initializers, streamed
path artifacts, and complete input recovery for unconstrained paths. It does
not come from relabeling incorrect verdicts or counting resource failures as
successes.

Detailed OSF data:

- [Per-case OSF results](results/osf/cases.csv)
- [OSF summary JSON](results/osf/summary.json)
- [OSF summary Markdown](results/osf/summary.md)
- [Family summary](results/osf/family_summary.csv)
- [Failure categories](results/osf/failure_summary.csv)
- [Failure cases](results/osf/failure_cases.csv)
- [Upstream 142 cases](results/osf/upstream_142_cases.csv)
- [Previous/provisional changes](results/osf/baseline_changes.csv)
- [Definedness audit](results/osf/ub_cases.csv)
- [Label audit](results/osf/label_audit.csv)
- [Ordered-output NEQ evidence](results/osf/factln_neq_evidence.json)
- [Full methodology and run audit](RESULTS_AUDIT.md)

### Label and definedness audit

Five official labels disagree with the released source behavior and remain
outside correct/wrong counts:

| Case | Official label | Evidence |
|---|---|---|
| `CLEVER/fib_Eq` | EQ | Replay `x=2`: old returns 1, new returns 2 |
| `CLEVER/is_prime1_Neq` | NEQ | Both released C files have the same SHA-256 |
| `CLEVER/is_prime2_Eq` | EQ | Replay `x=19`: old returns 0, new returns 1 |
| `airy/Sign_Eq` | EQ | Special-value replay changes the smallest-subnormal sign |
| `bess/SIGN_Eq` | EQ | Same source-level special-value defect |

Three final UB exclusions are retained:

| Case | Evidence |
|---|---|
| `REVE/loop5_Eq` | Full-domain witness overflows signed `int` in `n+n` |
| `dart/test_Eq` | Full-domain witness overflows signed `int` in `x*x*x` |
| `optimization/theta_Neq` | Both harnesses print a `double` with `%d` |

Validate the shipped tables without regenerating paths:

```bash
python scripts/validate_delivery_results.py
```

## Repository layout

```text
src/symbolic_analysis/          feature extraction and path matching
scripts/run_suite.py            suite driver
scripts/prepare_osf_all.py      OSF entry, type, and harness preparation
scripts/audit_osf_full.py       strict evidence audit
build_ardiff_path_benchmarks.py path generation and orchestration
run_experiment.py               host-side Docker entry point
run_evaluation.py               hybrid verification driver
configs/                        benchmark inputs and label audit
benchmark/                      source archive and upstream license
results/                        curated, path-free result tables
tests/                          unit and integration checks
```

## Limitations

The complete OSF table in this revision is explicitly provisional. The final
fresh 272-entry run with the latest entry/type code has not completed. The
residual OSF failures include 28 symbolic timeouts, 46 SIGKILL/OOM cases, 26
incomplete explorations, 15 verifier/semantic unknowns, and one unsupported
unbounded array entry. Resource failures are reported rather than silently
dropped.

The source-free UB heuristic is a triage rule for concrete replayed witnesses,
not a proof of definedness over every input. EQ evidence containing rejected
UB-like witnesses is marked conditional and retained in the audit.

## License

The source code is provided under the [MIT License](LICENSE). The bundled OSF
and ARDiff benchmark material retains the upstream terms in
[`benchmark/LICENSE.md`](benchmark/LICENSE.md).
