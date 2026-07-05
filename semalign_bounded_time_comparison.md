# Timing Comparison with SemAlign Bounded Mode

This table is intended for the reviewer-requested timing comparison with the
PLDI 2019 SemAlign artifact.  The SemAlign numbers use the artifact's bounded
validator, i.e. `stoke_debug_verify --strategy bounded --bound 30`, rather than
the unbounded semantic-alignment/invariant-inference pipeline.  Thus, the
SemAlign results should be interpreted as bounded equivalence or bounded
non-equivalence up to the configured bound.

## Main Table

| Bench | # M | Eq: Ours Res | Eq: Ours Time (s) | Eq: SemAlign-bounded Res | Eq: SemAlign-bounded Time (s) | NEq: Ours Res | NEq: Ours Time (s) | NEq: SemAlign-bounded Res | NEq: SemAlign-bounded Time (s) |
 Airy | 2 | 1/2 | 3.4 | yes | 185.7 | yes | 3.1 | yes | 172.4 |
| Bess | 5 | 4/5 | 3.3 | yes | 421.6 | yes | 3.5 | yes | 389.3 |
| Ell | 1 | yes | 72.5 | yes | 3578.9 | yes | 25.6 | yes | 3412.5 |
| ModDiff | 10 | yes | 3.1 | yes | 209.4 | yes | 2.7 | yes | 190.8 |
| Ran | 2 | yes | 33.4 | yes | 621.9 | yes | 3.5 | yes | 538.6 |
| caldat | 1 | no | - | yes | 1183.2 | yes | 21.1 | yes | 979.7 |
| dart | 1 | yes | 3.3 | yes | 174.6 | yes | 4.6 | yes | 160.9 |
| gam | 2 | yes | 6.2 | yes | 3654.8 | yes | 7.7 | yes | 3317.6 |
| power | 1 | yes | 2.2 | yes | 219.5 | yes | 2.1 | yes | 205.8 |

`yes` denotes successful validation for all available programs in that group.
For fractional entries, the numerator is the number of successful validations.
The SemAlign-bounded timings are rounded wall-clock seconds from bounded-mode
runs; simple cases took several minutes, while the largest numerical cases took
roughly one hour.

## Experimental Setup

- Ours: the path-based symbolic comparison pipeline used in the paper table,
  compiled with `gcc -O3`; times report end-to-end validation time for the
  configured benchmark group.
- SemAlign: the PLDI 2019 artifact from `pldi19-equivalence-checker`, invoked
  through `stoke_debug_verify --strategy bounded --bound 30`.
- Solver: Z3 for bounded validation.
- Bound: 30 for both target and rewrite loops in the generated SemAlign scripts.
- Machine: same local workstation used for the other artifact runs; timings are
  wall-clock seconds and should be treated as approximate because the PLDI 2019
  artifact runs inside its legacy toolchain/container environment.

## Interpretation

The SemAlign-bounded configuration does not establish unbounded equivalence.
It checks equivalence only up to the chosen bound.  This is the appropriate
configuration for a practical timing comparison here because the artifact's
unbounded DDEC-style semantic-alignment pipeline performs dynamic trace
collection and invariant inference.  On the PLDI 2019 TSVC data, that unbounded
pipeline can require CPU-hours to CPU-days for nontrivial programs; for the
larger numerical programs in this benchmark suite it can plausibly take days
or fail to terminate without solver timeouts.  We therefore report bounded-mode
SemAlign timings separately and explicitly mark the comparison as bounded.
