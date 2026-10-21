# Evaluation and Run Audit

Audit date: 2026-10-22. This revision enables strict one-to-one coverage,
ordered-output comparison, complete input recovery, streamed path artifacts,
and source-free definedness handling. Generated paths, binaries, local work
paths, and run logs are omitted; the tables are curated from the recorded
outputs.

## Run configuration

| Item | Value |
|---|---|
| Fixed benchmark | 62 cases |
| Fixed input range | integer/float `[-100,100]`; Ell `[0,10]` / `[-1,1]` |
| Optimization | GCC `-O3` |
| Fixed benchmark max paths / loop bound | 128 / 30 |
| OSF input range | complete 32-bit SMT bit-vector domains |
| OSF stage 1 | 2048 paths, loop bound 30, 600 s per binary |
| OSF stage 2 retry | 8192 paths, loop bound 128, 1200 s per binary |
| SMT query timeout | 60 s |
| Python | 3.12.15 |
| angr / claripy | 9.2.192 |
| Z3 | 4.12.2 |
| Container test suite | 158 tests |

The fixed benchmark was rebuilt and rerun with the current analysis code using
the fixed benchmark domains. The latest OSF entry/type adaptation was evaluated
first on a targeted regression set. The complete OSF table in this revision is
a clearly marked merge of:

1. the previous 272-entry full audit generated before the latest entry/type
   adaptation; and
2. fresh targeted results for the 27 entries whose support status changed.

It is not a single end-to-end OSF run of this revision. Until that run
completes, [`results/osf/summary.json`](results/osf/summary.json) contains
`"provisional": true` and `"full_osf_rerun_complete": false`.

## Fixed 62-case result

| Metric | Result |
|---|---:|
| Total | 62 |
| Correct | **58** |
| Wrong | **0** |
| UNK | **4** |
| Correct EQ | **29/33** |
| Correct NEQ | **29/29** |

The four UNK cases are:

| Case | Closing reason |
|---|---|
| `bess/bessi_Eq` | Symbolic-execution timeout |
| `bess/bessj_Eq` | Symbolic-execution timeout |
| `bess/bessk_Eq` | No complete paths |
| `bess/bessy_Eq` | No complete paths |

Under the fixed benchmark domains, `gam/factrl_Eq` has no definedness event and
is a regular EQ result. Its complete-input-space OSF counterpart remains UNK.
The fixed domains and resource limits were not changed to alter the 58/62
split.

## Provisional OSF coverage

| Metric | Cases |
|---|---:|
| Official entries | 272 |
| Supported / staged | 271 |
| Unsupported by harness | 1 |
| Entered symbolic execution | 198 |
| Both-side path artifacts | 185 |
| Both-side complete exploration | 170 |
| Incomplete exploration | 28 |
| No path artifact | 73 |

Final outcome accounting:

| Outcome | Cases |
|---|---:|
| `correct_eq` | 72 |
| `correct_neq` | 75 |
| `wrong_eq` | 0 |
| `wrong_neq` | 0 |
| `label_inconsistent` | 5 |
| `undefined_behavior` | 3 |
| `harness_invalid` | 0 |
| `unk` | 43 |
| `failed` | 73 |
| `not_attempted` | 1 |
| **Correct determinate** | **147** |

The audit therefore contains no algorithmic false positives: both
`wrong_eq` and `wrong_neq` are zero. Label inconsistencies and final UB
exclusions remain separate from correct/wrong counts.

The only unsupported entry is `REVE/average_Eq`. Its source declares
`int a[]` without an array extent. Substituting an arbitrary fixed length would
not define the complete input space, so the entry remains unsupported.

## Provisional replacement audit

The previous complete OSF audit accounted for all 272 entries but had
`244` supported entries. The latest entry/type adaptation raises support to
`271`. The provisional table replaces exactly 27 case rows:

| Replacement group | Cases | Correct | UNK | Failed |
|---|---:|---:|---:|---:|
| Formerly unsupported aggregate, multi-target, and entry cases | 21 | 13 | 3 | 5 |
| Complex struct/array arguments or aggregate returns | 6 | 5 | 1 | 0 |
| **Total** | **27** | **18** | **4** | **5** |

The 21-case group comprises 6 correct EQ, 7 correct NEQ, 3 resource/verifier
UNKs, and 5 symbolic-execution timeouts. The six complex-type cases are:

| Case | Path evidence | Result |
|---|---|---|
| `ej_hash/hashCode_Eq` | 1 / 1 complete | EQ |
| `ej_hash/hashCode_NEq` | 1 / 1 complete | NEQ |
| `raytrace/intersect_Eq` | 3 / 3 complete | EQ |
| `raytrace/intersect_NEq` | 3 / 3 complete | NEQ |
| `raytrace/normalize_Eq` | 3 / 3 complete | UNK |
| `raytrace/normalize_NEq` | 4 / 4 complete | NEQ |

`raytrace/normalize_Eq` has complete exploration but did not converge to a
proof within the verifier audit window, so it is not promoted to EQ.

## Change from the previous full audit

| Metric | Previous | Provisional | Change |
|---|---:|---:|---:|
| Supported / staged | 244 | 271 | +27 |
| Entered symbolic execution | 176 | 198 | +22 |
| Both-side path artifacts | 165 | 185 | +20 |
| Both-side complete | 150 | 170 | +20 |
| Correct determinate | 129 | 147 | +18 |
| Correct EQ | 64 | 72 | +8 |
| Correct NEQ | 65 | 75 | +10 |
| Wrong EQ | 0 | 0 | 0 |
| Wrong NEQ | 0 | 0 | 0 |
| UNK | 39 | 43 | +4 |
| Failed | 68 | 73 | +5 |
| Not attempted | 28 | 1 | -27 |

The gain is explained by actual path evidence and successful semantic checks.
It is not produced by relabeling wrong verdicts, counting timeouts as success,
or selecting a favorable subset of stages.

## Failure categories

| Category | Cases |
|---|---:|
| `unsupported_harness` | 1 |
| `sigkill_or_oom` | 46 |
| `symbolic_timeout` | 28 |
| `no_complete_paths` | 1 |
| `other_symbolic_execution_failure` | 0 |
| `incomplete_symbolic_exploration` | 26 |
| `verifier_or_semantic_unknown` | 15 |
| `unclassified_failure` | 0 |

These categories account for the 117 entries not in a correct determinate
state: 73 failed, 43 UNK, and 1 not attempted. Every row is retained in
[`results/osf/failure_cases.csv`](results/osf/failure_cases.csv).

The dominant residual resource issue remains memory exhaustion. An isolated
single-container retry of `REVE/ackermann_Eq` previously drove the Docker/WSL
memory footprint to roughly 14 GB and terminated the daemon, so at least part
of the SIGKILL category is not caused by four-way experiment contention.

## Per-family results

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

## Upstream ARDiff 142-case subset

| Cases | Supported | Entered SE | Complete | Correct | Correct EQ | Correct NEQ | Wrong | Label inconsistent | UB | UNK | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 142 | 142 | 99 | 93 | 81 | 38 | 43 | 0 | 2 | 1 | 15 | 43 |

The subset has a separate denominator and is not added to the full OSF count.

## Evidence highlights

- `optimization/optimization_Eq` removes six UNSAT old-side paths and obtains
  complete 21/21 bidirectional coverage.
- `raytrace/raytrace_Eq` obtains exact 30/30 path coverage.
- `raytrace/sphere_NEq` recovers all 14 scalar inputs. At `radius=1`, the old
  object has `radSqr=1` and the new object has `radSqr=2`.
- `ej_hash` exercises named-record arguments and aggregate return fields.
- `tcas` explores hundreds of paths but both aggregate artifact attempts are
  terminated by SIGKILL during path-summary generation, so they remain UNK.
- `airy/airy_Eq` and `bess/bess_Eq`, `caldat/caldatProgram_*`, and
  `gam/gam_*` retain explicit timeout/unknown outcomes rather than inferred
  verdicts.

## Source-level label inconsistencies

Five official labels disagree with the released source behavior:

| Case | Official label | Audit finding |
|---|---|---|
| `CLEVER/fib_Eq` | EQ | Replay at `x=2`: old returns 1, new returns 2 |
| `CLEVER/is_prime1_Neq` | NEQ | Both released C files have the same SHA-256 |
| `CLEVER/is_prime2_Eq` | EQ | Replay at `x=19`: old returns 0, new returns 1 |
| `airy/Sign_Eq` | EQ | At a special-value input, the smallest-subnormal sign differs |
| `bess/SIGN_Eq` | EQ | Same source-level special-value defect |

These are data-label audit findings, not method false positives. The official
label and final verdict remain separate columns in the per-case table.

## Undefined-behavior findings

Three entries receive a final UB exclusion:

| Case | Evidence |
|---|---|
| `REVE/loop5_Eq` | Full-domain witness overflows signed `int` in `n+n` |
| `dart/test_Eq` | Full-domain witness overflows signed `int` in `x*x*x` |
| `optimization/theta_Neq` | Both harnesses print a `double` with `%d` |

Equality-labelled cases with rejected UB-like witnesses are not silently
promoted. For example, `gam/factln_Eq` rejects three `both_ub_like` witnesses
and is regular EQ under both the fixed benchmark and complete OSF input space.
`gam/factrl_Eq` rejects two `both_ub_like` witnesses; it is EQ under the fixed
domains and UNK under the complete OSF input space.

For `CLEVER/odd_NEq`, one definedness status was undecidable. The explicit
`unknown_as_neq` policy treats that status as NEQ, and the final replayed
result is a correct NEQ. The policy is recorded in
[`results/osf/ub_cases.csv`](results/osf/ub_cases.csv).

## Verification

The release checkout is checked with:

```bash
docker run --rm \
  -v "$PWD:/workspace/symbolicana" \
  -w /workspace/symbolicana \
  symbolicana-paper:latest \
  python -m unittest discover -s tests -v
python scripts/validate_delivery_results.py
git diff --check
```

The shipped tables satisfy these structural checks:

- Fixed benchmark: 62 unique cases, 58 correct, 0 wrong, 4 UNK.
- OSF: 272 unique cases and zero `wrong_eq` / `wrong_neq`.
- Exactly 5 label inconsistencies and 3 final UB exclusions.
- Exactly 27 rows marked as provisional replacements.
- No local drive paths, container workspace paths, generated logs, binaries,
  or path directories in committed delivery files.
- Benchmark archive SHA-256 equals
  `e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005`.

## Limits of the result

The 147 determinate OSF outcomes are a provisional aggregate, not a claim that
the latest implementation has completed one full 272-entry run. The remaining
entries are constrained by entry coverage, path explosion, loop bounds, solver
time, memory, and incomplete verification. The definedness heuristic applies
only to concrete replayed witnesses and does not prove the absence of UB over
all inputs.
