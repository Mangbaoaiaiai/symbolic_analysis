# Evaluation and Run Audit

Audit date: 2026-10-21. Source-free definedness handling is enabled in this
release. Generated paths, binaries, local work paths, and run logs are omitted
from the repository; the tables below are curated from the actual run outputs.

## Run configuration

| Item | Value |
|---|---|
| Paper benchmark | 62 fixed cases |
| Paper input range | integer/float `[-100,100]`; Ell `[0,10]` / `[-1,1]` |
| Optimization | GCC `-O3` |
| Paper max paths / loop bound | 128 / 30 |
| OSF input range | complete 32-bit SMT bit-vector domains |
| OSF stage 1 | 2048 paths, loop bound 30, 600 s per binary |
| OSF stage 2 retry | 8192 paths, loop bound 128, 1200 s per binary |
| SMT query timeout | 60 s |
| Paper execution image | `symbolicana-bindiff:local` |
| Python | 3.12.15 |
| angr / claripy | 9.2.192 |
| Z3 | 4.12.2 |

The final fixed-62 regression command was:

```bash
python run_experiment.py \
  --suite paper \
  --image symbolicana-bindiff:local \
  --run-name ub_full62_rerun_20261021 \
  --fresh
```

The 130-test Docker suite covers the analysis, verifier, audit, and staging
paths. The complete OSF
audit uses the source-free definedness implementation and combines the staged
attempt evidence rather than selecting a favorable shard.

## Fixed 62-case result

| Metric | Result |
|---|---:|
| Total | 62 |
| Correct | 58 |
| Wrong | 0 |
| UNK | 4 |
| Correct EQ | 29/33 |
| Correct NEQ | 29/29 |

Definedness events:

| Classification | Logical witnesses |
|---|---:|
| `asymmetric_ub_like` | 2 |
| `both_ub_like` | 0 |
| `defined_neq` | 27 |
| `ub_status_unknown` | 0 |

In this fresh fixed-domain run, `gam/factrl_Eq` has no definedness event and is
a regular EQ result. Its complete-domain OSF counterpart remains UNK.

| Case | Closing reason |
|---|---|
| `bess/bessi_Eq` | old-side symbolic execution timeout |
| `bess/bessj_Eq` | old-side symbolic execution timeout |
| `bess/bessk_Eq` | no complete paths |
| `bess/bessy_Eq` | no complete paths |

These cases are not counted as correct or wrong. The fixed paper domains and
resource thresholds were not changed to force a different split.

## Complete OSF coverage

| Metric | Cases |
|---|---:|
| Official entries | 272 |
| Supported / staged | 244 |
| Unsupported by harness | 28 |
| Entered symbolic execution | 176 |
| Both-side path artifacts | 165 |
| Both-side complete exploration | 150 |
| Incomplete exploration | 26 |
| No path artifact | 68 |

Final outcome accounting:

| Outcome | Cases |
|---|---:|
| `correct_eq` | 64 |
| `correct_neq` | 65 |
| `wrong_eq` | 0 |
| `wrong_neq` | 0 |
| `label_inconsistent` | 5 |
| `undefined_behavior` | 3 |
| `harness_invalid` | 0 |
| `unk` | 39 |
| `failed` | 68 |
| `not_attempted` | 28 |
| **Correct determinate** | **129** |

The OSF run therefore obtains 129 trustworthy determinate outcomes and no
algorithmic false positives. The `undefined_behavior` column contains final
source-level exclusions, not every witness rejected by the heuristic. A separate
`ub_cases.csv` records all replay/definedness events, including two
equality-labelled cases with rejected UB-like witnesses.

## Change from the previous audited OSF run

| Metric | Previous | Current | Change |
|---|---:|---:|---:|
| Supported / staged | 232 | 244 | +12 |
| Entered symbolic execution | 146 | 176 | +30 |
| Both-side path artifacts | 146 | 165 | +19 |
| Both-side complete | 128 | 150 | +22 |
| Correct determinate | 110 | 129 | +19 |
| Wrong EQ | 0 | 0 | 0 |
| Wrong NEQ | 0 | 0 | 0 |

The gain is attributable to larger harness coverage and staged retry evidence.
It is not produced by relabeling cases, excluding incorrect verdicts, or turning
resource failures into correct outcomes.

## Failure categories

| Category | Cases |
|---|---:|
| `sigkill_or_oom` | 44 |
| `symbolic_timeout` | 23 |
| `incomplete_symbolic_exploration` | 26 |
| `no_complete_paths` | 1 |
| `verifier_or_semantic_unknown` | 13 |
| `unsupported_harness` | 28 |
| `other_symbolic_execution_failure` | 0 |
| `unclassified_failure` | 0 |

These categories account for all 135 cases that are not correct determinate
outcomes: 68 failed, 39 UNK, and 28 not attempted. Per-case reasons are retained
in [`results/osf/failure_cases.csv`](results/osf/failure_cases.csv).

The dominant residual source is memory exhaustion. During a separate
single-container retry, `REVE/ackermann_Eq` raised the Docker/WSL memory footprint
to roughly 14 GB and terminated the daemon. This is recorded as an OOM failure.
It demonstrates that at least part of the 44-case SIGKILL category remains even
without four-container contention.

## Upstream ARDiff 142-case subset

| Cases | Supported | Entered SE | Complete | Correct | Correct EQ | Correct NEQ | Wrong | Label inconsistent | UB | UNK | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 142 | 142 | 99 | 93 | 81 | 38 | 43 | 0 | 2 | 1 | 15 | 43 |

The subset is derived from the upstream ARDiff runner and is recorded separately
so that its denominator is not mixed with the complete OSF set.

## Source-level label inconsistencies

The official labels and the released C sources disagree in five entries. They
remain `label_inconsistent` and are excluded from correct and wrong counts.

| Case | Official label | Audit finding |
|---|---|---|
| `CLEVER/fib_Eq` | EQ | Replay at `x=2`: old returns 1, new returns 2 |
| `CLEVER/is_prime1_Neq` | NEQ | Both released C files have SHA-256 `209e2a5133437cb1261f9a381a427e4288d8b58d0e3ecfe09567e188cf6dfe51` |
| `CLEVER/is_prime2_Eq` | EQ | Replay at `x=19`: old returns 0, new returns 1 |
| `airy/Sign_Eq` | EQ | At `a=-0x1p-1022`, `b=NaN`, the sign of the smallest subnormal differs |
| `bess/SIGN_Eq` | EQ | Same floating-point special-value defect as `airy/Sign_Eq` |

This is a data-label audit, not a method false-positive count. The original
label and the final verdict remain separate columns in
[`results/osf/cases.csv`](results/osf/cases.csv).

## Undefined-behavior findings

Three entries receive a final UB exclusion:

| Case | Evidence |
|---|---|
| `REVE/loop5_Eq` | Full-domain witness evaluates signed `int` `n+n` outside its range |
| `dart/test_Eq` | Full-domain witness evaluates signed `int` `x*x*x` outside its range |
| `optimization/theta_Neq` | Both harnesses print a `double` with `%d`; replay output is unstable |

The audit separately preserves two equality-labelled cases for which every
tested UB-like witness was rejected rather than promoting the candidate
discrepancy:

- `gam/factln_Eq`: three `both_ub_like` witnesses rejected; the fixed paper and
  complete OSF outcomes are both EQ.
- `gam/factrl_Eq`: two `both_ub_like` witnesses rejected; the fixed paper
  outcome is conditional EQ, while the complete-domain OSF outcome is UNK.

For `CLEVER/odd_NEq`, one definedness status could not be established and the
explicit policy treats that unknown status as NEQ. Its final replayed result is a
correct NEQ and the decision is visible in `ub_cases.csv`.

## Verification

The final checks for the release checkout are:

```bash
python -m unittest discover -s tests -v
python scripts/validate_delivery_results.py
git diff --check
```

The shipped data must satisfy all of the following:

- Paper result: 62 unique cases, 58 correct, zero wrong, four UNK.
- OSF result: 272 unique cases and zero `wrong_eq` / `wrong_neq`.
- Exactly five `label_inconsistent` and exactly three final UB exclusions.
- No local drive paths, container-workspace paths, generated logs, binaries, or
  path directories in committed delivery files.
- Benchmark archive SHA-256 equals
  `e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005`.

## Limits of the result

The 129 determinate OSF outcomes do not imply support for all 272 entries. The
remaining cases are constrained by entry-point extraction, path explosion,
loop bounds, solver time, or memory. The definedness heuristic is applied only
to concrete replayed witnesses and does not prove absence of UB over all inputs.
Potential UB in EQ evidence is handled conservatively and every decision is kept
in the audit rather than hidden behind an aggregate score.
