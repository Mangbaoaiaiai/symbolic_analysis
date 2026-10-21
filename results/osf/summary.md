# Complete OSF strict audit

## Coverage

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

An EQ is accepted only when both exploration manifests and the
matching verifier report are complete. A NEQ remains valid when a
verified, replayable observable difference exists.

## Outcomes

| Outcome | Cases |
|---|---:|
| correct_eq | 64 |
| correct_neq | 65 |
| wrong_eq | 0 |
| wrong_neq | 0 |
| label_inconsistent | 5 |
| undefined_behavior | 3 |
| harness_invalid | 0 |
| unk | 39 |
| failed | 68 |
| not_attempted | 28 |
| **Correct determinate** | **129** |
| UB status unknown, treated as NEQ | 1 |

### Definedness classifications

| Classification | Witnesses |
|---|---:|
| `asymmetric_ub_like` | 9 |
| `both_ub_like` | 15 |
| `defined_neq` | 67 |
| `ub_status_unknown` | 1 |

## Failure categories

| Category | Cases |
|---|---:|
| `unsupported_harness` | 28 |
| `sigkill_or_oom` | 44 |
| `symbolic_timeout` | 23 |
| `no_complete_paths` | 1 |
| `other_symbolic_execution_failure` | 0 |
| `incomplete_symbolic_exploration` | 26 |
| `verifier_or_semantic_unknown` | 13 |
| `unclassified_failure` | 0 |

## Family table

| Family | Cases | Supported | Complete | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | Undefined behavior | UNK | Failed | Not attempted |
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

## Upstream ARDiff 142

| Cases | Supported | Entered SE | Complete | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | Undefined behavior | UNK | Failed | Not attempted |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 142 | 142 | 99 | 93 | 38 | 43 | 0 | 0 | 2 | 1 | 15 | 43 | 0 |
