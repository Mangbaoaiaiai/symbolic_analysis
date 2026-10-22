# Complete OSF strict audit

## Coverage

| Metric | Cases |
|---|---:|
| Official entries | 272 |
| Supported / staged | 271 |
| Unsupported by harness | 1 |
| Entered symbolic execution | 195 |
| Both-side path artifacts | 180 |
| Both-side complete exploration | 165 |
| Incomplete exploration | 30 |
| No path artifact | 76 |

An EQ is accepted only when both exploration manifests and the
matching verifier report are complete. A NEQ remains valid when a
verified, replayable observable difference exists.

## Target-level audit

Jointly wrapped cases are partitioned by their `Target <name>:`
stdout blocks. A target is reported as NEQ only when that block
differs on the same replayed input; a whole-process difference is
never attributed to every target.

| Metric | Count |
|---|---:|
| Multi-target cases | 15 |
| Target observations | 59 |
| Target EQ | 9 |
| Target NEQ | 4 |
| Target UNK | 46 |
| Case/target verdict inconsistencies | 0 |

## Outcomes

| Outcome | Cases |
|---|---:|
| correct_eq | 72 |
| correct_neq | 72 |
| wrong_eq | 0 |
| wrong_neq | 0 |
| label_inconsistent | 5 |
| undefined_behavior | 3 |
| harness_invalid | 0 |
| unk | 43 |
| failed | 76 |
| not_attempted | 1 |
| **Correct determinate** | **144** |
| UB status unknown, treated as NEQ | 1 |

### Definedness classifications

| Classification | Witnesses |
|---|---:|
| `asymmetric_ub_like` | 8 |
| `both_ub_like` | 13 |
| `defined_neq` | 73 |
| `ub_status_unknown` | 1 |

## Failure categories

| Category | Cases |
|---|---:|
| `unsupported_harness` | 1 |
| `sigkill_or_oom` | 63 |
| `symbolic_timeout` | 26 |
| `no_complete_paths` | 2 |
| `other_symbolic_execution_failure` | 0 |
| `incomplete_symbolic_exploration` | 15 |
| `verifier_or_semantic_unknown` | 13 |
| `unclassified_failure` | 0 |

## Family table

| Family | Cases | Supported | Complete | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | Undefined behavior | UNK | Failed | Not attempted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CLEVER | 50 | 50 | 50 | 27 | 20 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| REVE | 32 | 31 | 9 | 5 | 2 | 0 | 0 | 0 | 1 | 17 | 6 | 1 |
| airy | 12 | 12 | 10 | 3 | 5 | 0 | 0 | 1 | 0 | 3 | 0 | 0 |
| bess | 36 | 36 | 24 | 9 | 12 | 0 | 0 | 1 | 0 | 7 | 7 | 0 |
| caldat | 10 | 10 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 8 | 0 |
| dart | 2 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| ej_hash | 12 | 12 | 12 | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ell | 26 | 26 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 24 | 0 |
| frenel | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 |
| gam | 24 | 24 | 11 | 4 | 5 | 0 | 0 | 0 | 0 | 4 | 11 | 0 |
| optimization | 6 | 6 | 6 | 2 | 2 | 0 | 0 | 0 | 1 | 1 | 0 | 0 |
| pow | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ran | 22 | 22 | 5 | 3 | 2 | 0 | 0 | 0 | 0 | 3 | 14 | 0 |
| raytrace | 12 | 12 | 12 | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sine | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| statcalc | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| tcas | 8 | 8 | 6 | 0 | 3 | 0 | 0 | 0 | 0 | 5 | 0 | 0 |
| tsafe | 8 | 8 | 8 | 2 | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 |

## Upstream ARDiff 142

| Cases | Supported | Entered SE | Complete | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | Undefined behavior | UNK | Failed | Not attempted |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 142 | 142 | 96 | 90 | 38 | 41 | 0 | 0 | 2 | 1 | 14 | 46 | 0 |
