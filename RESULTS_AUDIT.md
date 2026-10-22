# Evaluation and Run Audit

Audit date: 2026-10-22.

This document records the current implementation's fixed 62-case experiment
and a complete 272-entry OSF run. The published tables are curated outputs:
generated paths, binaries, caches, logs, and local work paths are excluded.

## Run configuration

| Item | Value |
|---|---|
| Fixed benchmark | 62 cases: 33 EQ and 29 NEQ |
| Fixed input range | integer/float `[-100,100]`; Ell `[0,10]` and `[-1,1]` |
| OSF input range | complete representable 32-bit SMT input spaces |
| Optimization | GCC 12.2, x86-64, `-O3` |
| Fixed benchmark max paths / loop bound | 128 / 30 |
| OSF stage 1 | 2048 paths, loop bound 30, 600 s per binary |
| OSF stage 2 retry | 8192 paths, loop bound 128, 1200 s per binary |
| Verifier wall limit | 600 s per case |
| SMT query timeout | 60 s |
| Python | 3.12.15 |
| angr / claripy | 9.2.192 |
| Z3 | 4.12.2 |
| Container test suite | 162 tests |

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
| `bess/bessk_Eq` | No complete symbolic paths |
| `bess/bessy_Eq` | No complete symbolic paths |

The fixed benchmark and its input domains were not changed to alter the
`58/62` result.

## Complete OSF result

| Outcome | Cases |
|---|---:|
| `correct_eq` | 72 |
| `correct_neq` | 72 |
| **Correct determinate** | **144** |
| `wrong_eq` | 0 |
| `wrong_neq` | 0 |
| `label_inconsistent` | 5 |
| `undefined_behavior` | 3 |
| `unk` | 43 |
| `failed` | 76 |
| `not_attempted` | 1 |
| **Total** | **272** |

Coverage and failure accounting:

| Metric | Cases |
|---|---:|
| Supported / staged | 271 |
| Unsupported by harness | 1 |
| Entered symbolic execution | 195 |
| Both-side path artifacts | 180 |
| Both-side complete exploration | 165 |
| Incomplete exploration | 30 |
| No path artifact | 76 |
| `symbolic_timeout` | 26 |
| `sigkill_or_oom` | 63 |
| `incomplete_symbolic_exploration` | 15 |
| `verifier_or_semantic_unknown` | 13 |
| `no_complete_paths` | 2 |
| `unsupported_harness` | 1 |

The only unsupported entry is `REVE/average_Eq`. Its source declares `int a[]`
without an array extent, so a complete source-free input harness cannot be
defined without inventing a bound.

The strict audit reports no conflicting stage verdicts and no incorrect EQ or
NEQ decisions. Every residual case remains in `cases.csv` and
`failure_cases.csv`.

## Change from the provisional aggregate

The previous `results/osf` table was marked provisional and reported 147
correct determinate outcomes. The completed strict run reports 144:

- Five provisional correct outcomes were not retained: two complete EQ cases
  exceeded the verifier wall limit, and three NEQ cases lacked complete or
  successful symbolic-execution evidence.
- Two cases previously marked UNK obtained complete path evidence and a
  verified EQ result: `optimization/wood_Eq` and `raytrace/normalize_Eq`.
- Several non-correct categories also changed between failed and UNK after
  strict path and evaluation evidence was applied.

The net change is therefore `147 - 5 + 2 = 144`. Old rows were not copied into
the final aggregate when current-run evidence was incomplete.

During shard evaluation, the `--pair` selector was initially case-sensitive.
That omitted 23 NEQ cases whose public IDs use `_NEq` while internal pair IDs
use `_Neq`. The selector is now case-insensitive, and all 23 cases were
re-evaluated before generating the final audit. Their reports account for the
increase from the intermediate strict count of 121 to the final 144.

## Per-family results

The detailed per-family table, including timed cases and mean verifier time,
is in [`results/osf/family_summary.csv`](results/osf/family_summary.csv) and in
the README.

## Upstream ARDiff 142-case subset

| Cases | Supported | Entered SE | Complete | Correct | Correct EQ | Correct NEQ | Wrong | Label inconsistent | UB | UNK | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 142 | 142 | 96 | 90 | 79 | 38 | 41 | 0 | 2 | 1 | 14 | 46 |

The subset has a separate denominator and is not added to the full OSF count.

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

The shipped result files satisfy these checks:

- Fixed benchmark: 62 unique cases, 58 correct, 0 wrong, 4 UNK.
- OSF: 272 unique cases, 144 correct, 0 wrong EQ/NEQ, and no stage conflicts.
- Exactly 5 source-level label inconsistencies and 3 final UB exclusions.
- Every failure has a row in `failure_cases.csv`.
- No host/container work paths, generated logs, binaries, or path directories
  are committed.
- The benchmark archive SHA-256 is
  `e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005`.

## Limits

The 144 determinate OSF outcomes are the result of the recorded resource limits
and complete-input-space profile. The remaining entries are constrained by
harness coverage, path explosion, loop and path bounds, solver time, memory,
and incomplete verification. The UB heuristic applies only to concrete
replayed witnesses and does not prove the absence of UB over all inputs.
