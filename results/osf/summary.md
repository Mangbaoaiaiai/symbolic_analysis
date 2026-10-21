# Provisional complete OSF audit

> This table combines the previous 272-case full audit with targeted
> results for 27 newly supported cases. It is not a
> fresh end-to-end run and is retained only until the final full-suite
> replacement completes.

## Coverage

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

## Outcomes

| Outcome | Cases |
|---|---:|
| correct_eq | 72 |
| correct_neq | 75 |
| wrong_eq | 0 |
| wrong_neq | 0 |
| label_inconsistent | 5 |
| undefined_behavior | 3 |
| harness_invalid | 0 |
| unk | 43 |
| failed | 73 |
| not_attempted | 1 |
| **Correct determinate** | **147** |
| UB status unknown treated as NEQ | 1 |

## Failure categories

| Category | Cases |
|---|---:|
| unsupported_harness | 1 |
| sigkill_or_oom | 46 |
| symbolic_timeout | 28 |
| no_complete_paths | 1 |
| other_symbolic_execution_failure | 0 |
| incomplete_symbolic_exploration | 26 |
| verifier_or_semantic_unknown | 15 |
| unclassified_failure | 0 |

## Family table

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

## Upstream ARDiff 142

| Cases | Supported | Entered SE | Complete | Correct EQ | Correct NEQ | Wrong | Label inconsistent | UB | UNK | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 142 | 142 | 99 | 93 | 38 | 43 | 0 | 2 | 1 | 15 | 43 |
