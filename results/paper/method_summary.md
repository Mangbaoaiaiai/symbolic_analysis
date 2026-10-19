# Method comparison

| Method | Cases | Correct | Wrong | UNK | Failed | Hit@1 | Hit@3 | MRR | One-to-many records |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Naive | 62 | 58 | 0 | 4 | 0 | 19.62% | 34.49% | 0.3127 | 1 |
| VeriBin | 62 | 58 | 0 | 4 | 0 | 43.35% | 52.85% | 0.5201 | 1 |
| Hybrid | 62 | 58 | 0 | 4 | 0 | 75.95% | 80.06% | 0.7894 | 1 |
| Hybrid-one-to-one | 62 | 57 | 0 | 5 | 0 | 75.95% | 80.06% | 0.7894 | 0 |

Counts are computed from verified per-case CSV rows. Missing rows are
reported only when `expected_cases` is supplied; they are never treated
as correct, UNK, or wrong.
