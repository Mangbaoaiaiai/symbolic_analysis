[Evaluation](#evaluation)

# Symbolicana Experimental Results

This README reports the current measured outcomes for the fixed 62-case
benchmark and the complete 272-entry OSF accounting.

## Quick start

Build the pinned analysis image and run the test suite:

```bash
python run_experiment.py --suite tests --rebuild
```

Run the fixed 62-case experiment with a fresh path cache:

```bash
python run_experiment.py \
  --suite paper \
  --bindiff \
  --fresh \
  --run-name paper_latest
```

Run the complete 272-entry OSF experiment:

```bash
python run_experiment.py \
  --suite osf \
  --fresh \
  --run-name osf_latest
```

`--bindiff` selects the optional graph-reranking image. If it is unavailable,
the runner falls back to feature-only ranking and records that fallback.
Generated binaries and paths are written below `work/`; rerun summaries are
written below `results/rerun/<run-name>/`.

## Evaluation

### Experimental scope

| Item | Current setting |
|---|---|
| Fixed benchmark | 62 cases: 33 EQ and 29 NEQ |
| Fixed input domain | Integers and floats in `[-100,100]`; Ell uses `[0,10]` and `[-1,1]` |
| OSF input domain | Complete signed 32-bit and floating-point SMT bit-vector spaces |
| Compilation | GCC 12.2, x86-64, `-O3` |
| Symbolic execution | angr/claripy 9.2.192 |
| Solver | Z3 4.12.2 |
| SMT timeout | 60 seconds per query |
| Loop bound | 30 completed iterations |

### Difference from the paper

The current fixed-benchmark result is `58/62`, while the paper reports
`54/62`. This difference has three concrete causes.

First, the execution environment differs. The paper reports a 32-core Intel
Xeon 2.5 GHz machine with 64 GB RAM on Ubuntu 22.04. The recorded runs here use
Docker Linux containers on an x86-64 Docker Desktop/WSL2 host with 16 logical
CPUs and about 16 GB exposed to Docker. Symbolic-execution wall-clock limits
therefore admit a different set of complete paths.

Second, the paper does not state a fixed numeric interval for symbolic inputs.
The fixed 62-case profile uses the same integer and floating-point assumption
as the upstream ARDiff runner, `[-100,100]`, with Ell overrides `[0,10]` and
`[-1,1]`. The complete OSF profile instead uses the full representable 32-bit
SMT input spaces. These domains change path feasibility and path counts, so
the two result sets are not directly interchangeable.

Third, the implementation has engineering improvements that affect evidence
quality: ordered standard output is part of the observable state, formatted
floating-point output is serialized by IEEE bit pattern, 64-bit ABI values are
preserved, infeasible paths are removed by a bounded conservative prefilter,
path summaries are streamed to disk, and unconstrained paths recover their
complete input arity. The latest verifier also resolves several cases that the
paper reports as SMT-UNK. These changes are reported explicitly and are not
converted into correct results when path evidence remains incomplete.

## 1. Main fixed 62-case result

| Metric | Result |
|---|---:|
| Correct determinate | **58/62 (93.55%)** |
| Correct EQ | **29/33 (87.88%)** |
| Correct NEQ | **29/29 (100.00%)** |
| Wrong EQ / NEQ | **0** |
| UNK | **4** |

Per-family results:

| Family | Cases | Correct | UNK |
|---|---:|---:|---:|
| CLEVER | 28 | 28 | 0 |
| airy | 4 | 4 | 0 |
| bess | 14 | 10 | 4 |
| caldat | 2 | 2 | 0 |
| dart | 2 | 2 | 0 |
| Ell | 2 | 2 | 0 |
| gam | 4 | 4 | 0 |
| power | 2 | 2 | 0 |
| Ran | 4 | 4 | 0 |

The four UNK cases are:

| Case | Reason |
|---|---|
| `bess/bessi_Eq` | Symbolic-execution timeout |
| `bess/bessj_Eq` | Symbolic-execution timeout |
| `bess/bessk_Eq` | No complete symbolic paths |
| `bess/bessy_Eq` | No complete symbolic paths |

The 58 analyzed cases include 29 correct EQ, 29 correct NEQ, and no incorrect
EQ/NEQ result. The four remaining cases are excluded only from the denominator
for timing and ranking metrics; they remain UNK in the verdict denominator.

## 2. One-to-many path-matching ablation

Strict one-to-one mode requires a distinct, bidirectionally equal input-domain
match for every source and target path. The complete method additionally allows
one source region to be covered by a union of target regions.

| Configuration | Correct / 62 | Correct EQ | Correct NEQ | Wrong | UNK | Correct rate |
|---|---:|---:|---:|---:|---:|---:|
| Strict one-to-one | 57 | 28/33 | 29/29 | 0 | 5 | 91.94% |
| Bidirectional one-to-many coverage | **58** | **29/33** | **29/29** | **0** | **4** | **93.55%** |
| Difference | +1 | +1 EQ | 0 | 0 | -1 | +1.61 pp |

The additional case is `dart/test_Eq`: strict one-to-one returns UNK, while
coverage-based matching returns the correct EQ result. The four path-generation
failures (`bess/bessi_Eq`, `bess/bessj_Eq`, `bess/bessk_Eq`, and
`bess/bessy_Eq`) are UNK in both configurations.

### Column definitions

| Label | Definition |
|---|---|
| `Case` | Official benchmark case identifier. |
| `Family` | Benchmark family assigned by the benchmark manifest. |
| `Cases` | Number of official entries in the family; the full OSF denominator is 272. |
| `Configuration` | One experimental variant under comparison. |
| `Metric` | Aggregate quantity measured by a result table. |
| `Result` | Value produced by the current run. |
| `Outcome` | Final verdict/audit category assigned to one case. |
| `Reason` | Residual condition that prevented a more specific result. |
| `File` | Path-free or path-only result artifact linked by the README. |
| `Supported` | Entries for which a source-free harness could be generated and staged. |
| `Complete` | Entries whose old and new executions both produced path artifacts and completed exploration. |
| `Correct EQ` | The verdict is EQ and also matches the official EQ label. |
| `Correct NEQ` | The verdict is NEQ and also matches the official NEQ label. |
| `Correct determinate` | Correct EQ plus correct NEQ outcomes. |
| `Correct / 62` | Number of correct determinate verdicts over the fixed 62-case denominator. |
| `Correct rate` | Correct determinate verdicts divided by all 62 cases. |
| `Wrong EQ` | Determinate EQ verdicts for cases labelled NEQ. |
| `Wrong NEQ` | Determinate NEQ verdicts for cases labelled EQ. |
| `Difference` | Current full configuration minus the comparison configuration. |
| `Label inconsistent` | The released sources contradict the official label, so the row is excluded from correct/wrong counts. |
| `UB` | Final exclusion because source-level undefined behavior or unstable formatting prevents a trustworthy verdict. |
| `Undefined behavior excluded` | Long-form label for the `UB` outcome column. |
| `UNK` | The method declined to decide because evidence was incomplete or no proof was reached; UNK is not a wrong verdict. |
| `Failed` | Harness construction, symbolic execution, or another process stage failed before a verdict. |
| `Not attempted` | No harness could be constructed, including unsupported pointer/array signatures. |
| `Not attempted / unsupported` | Long-form label for entries with no executable harness. |
| `Entered symbolic execution` | At least one side started symbolic execution and produced path evidence. |
| `Both-side path artifacts` | Both binaries produced at least one path artifact, regardless of completeness. |
| `Both-side complete exploration` | Both sides have complete exploration markers, path artifacts, and no failure marker. |
| `Incomplete exploration` | Some path evidence exists, but at least one side does not have complete exploration. |
| `No path artifact` | Neither side produced a usable path artifact. |
| `Timed cases` | Cases with a recorded verifier wall-clock duration. Path- or verifier-failed cases without a duration are not imputed. |
| `Mean verifier time / timed case` | Arithmetic mean of `evaluation_wall_seconds` over `Timed cases` only; expressed in seconds. |
| `symbolic_timeout` | Symbolic execution exceeded its configured wall-clock limit. |
| `sigkill_or_oom` | The executor was terminated by SIGKILL, usually because of memory exhaustion. |
| `incomplete_symbolic_execution` | Exploration stopped with an incomplete path set. |
| `verifier_or_semantic_unknown` | Complete paths were available, but no trustworthy semantic proof was reached. |
| `no_complete_paths` | Symbolic execution produced no complete terminating path. |
| `unsupported_harness` | The source signature could not be represented by the source-free harness. |

## 3. Complete OSF evaluation

> **Provisional aggregate.** The current 272-entry table combines the previous
> complete OSF audit with targeted results for 27 cases supported by the latest
> entry/type adaptation. It is not yet a single end-to-end run. The summary
> records `provisional: true` and `full_osf_rerun_complete: false`.

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
| **Total** | **272** |

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

The only unsupported entry is `REVE/average_Eq`; its source declares `int a[]`
without an array extent.

Per-family OSF results:

| Family | Cases | Supported | Complete | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | UB | UNK | Failed | Not attempted | Timed cases | Mean verifier time / timed case (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CLEVER | 50 | 50 | 50 | 27 | 20 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 50 | 2.226 |
| REVE | 32 | 31 | 9 | 5 | 2 | 0 | 0 | 0 | 1 | 17 | 6 | 1 | 23 | 26.640 |
| airy | 12 | 12 | 12 | 4 | 6 | 0 | 0 | 1 | 0 | 1 | 0 | 0 | 10 | 1.504 |
| bess | 36 | 36 | 26 | 9 | 13 | 0 | 0 | 1 | 0 | 8 | 5 | 0 | 26 | 51.713 |
| caldat | 10 | 10 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 8 | 0 | 2 | 0.930 |
| dart | 2 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 1.825 |
| ej_hash | 12 | 12 | 12 | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 0.836 |
| ell | 26 | 26 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 2 | 11.449 |
| frenel | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 5 | 0 | 0 | NA |
| gam | 24 | 24 | 12 | 4 | 6 | 0 | 0 | 0 | 0 | 3 | 11 | 0 | 12 | 56.933 |
| optimization | 6 | 6 | 6 | 2 | 2 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 4 | 213.886 |
| pow | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.571 |
| ran | 22 | 22 | 5 | 3 | 2 | 0 | 0 | 0 | 0 | 3 | 14 | 0 | 6 | 2.661 |
| raytrace | 12 | 12 | 12 | 5 | 6 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | NA |
| sine | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 53.214 |
| statcalc | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.545 |
| tcas | 8 | 8 | 6 | 0 | 3 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 6 | 80.616 |
| tsafe | 8 | 8 | 8 | 2 | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 8 | 225.411 |
| **All** | **272** | **271** | **170** | **72** | **75** | **0** | **0** | **5** | **3** | **43** | **73** | **1** | **165** | **36.782** |

`NA` means that no case in that family had a recorded verifier wall time. The
overall mean is computed over all 165 timed cases, not as an unweighted mean of
the family means.

## Result files

| Result | File |
|---|---|
| Fixed 62 per-case outcomes | [`results/paper/cases.csv`](results/paper/cases.csv) |
| Fixed 62 summary | [`results/paper/summary.json`](results/paper/summary.json) |
| Fixed 62 definedness audit | [`results/paper/summary.md`](results/paper/summary.md) |
| Complete OSF per-case outcomes | [`results/osf/cases.csv`](results/osf/cases.csv) |
| Complete OSF summary | [`results/osf/summary.json`](results/osf/summary.json) |
| Complete OSF family table | [`results/osf/family_summary.csv`](results/osf/family_summary.csv) |
| Complete OSF failure table | [`results/osf/failure_cases.csv`](results/osf/failure_cases.csv) |
| Complete OSF label audit | [`results/osf/label_audit.csv`](results/osf/label_audit.csv) |
