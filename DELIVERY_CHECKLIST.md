# Delivery Checklist

## Release contents

- [x] `README.md` starts with an `Evaluation` hyperlink.
- [x] The first half documents pinned tools and one-command reruns.
- [x] The fixed benchmark reports `58/62` correct, `0` wrong, and `4` UNK.
- [x] The fixed split reports `29/33` correct EQ and `29/29` correct NEQ.
- [x] All 272 official OSF entries are present in the manifest and per-case
      result audit.
- [x] The benchmark archive and source manifests are included without
      generated path files.
- [x] The OSF aggregate table and all per-family tables are included.
- [x] The source and benchmark licenses are included.
- [x] Generated paths, binaries, caches, raw logs, and local workspace paths
      are excluded.

## Current provisional OSF audit

- [x] `results/osf/summary.json` marks the aggregate as provisional and records
      that the complete rerun is not finished.
- [x] Exactly 27 case rows are replaced: 21 from the all-method entry
      regression and 6 from the complex-type regression.
- [x] The previous 272-entry full audit supplies all other case rows.
- [x] `271 / 272` entries are supported or staged.
- [x] `198` entries entered symbolic execution.
- [x] `185` entries have both-side path artifacts.
- [x] `170` entries have complete exploration on both sides.
- [x] The provisional audit reports `147` correct determinate outcomes:
      `72` EQ and `75` NEQ.
- [x] The provisional audit reports zero `wrong_eq` and zero `wrong_neq`.
- [x] Five source-level label inconsistencies remain visible per case.
- [x] Three final undefined-behavior exclusions remain visible per case.
- [x] Failure accounting reports 28 symbolic timeouts, 46 SIGKILL/OOM
      cases, 26 incomplete explorations, 15 verifier/semantic unknowns, one
      no-complete-path case, and one unsupported harness.
- [x] The upstream ARDiff 142-case subset has its own summary and case table.
- [x] The benchmark archive SHA-256 is
      `e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005`.

## Verification

- [x] The analysis image reports Python 3.12.15, GCC 12.2, angr/claripy
      9.2.192, and Z3 4.12.2.
- [x] All 158 Docker unit/integration tests pass.
- [x] `python scripts/validate_delivery_results.py` passes for the provisional
      table.
- [x] `git diff --check` passes.
- [x] The curated tables contain no host or container work paths.

## Pending final OSF run

- [ ] Commit and push this provisional release to GitHub `main`.
- [ ] Start a fresh 272-entry OSF run from the pushed release checkout.
- [ ] Complete both OSF path-generation/evaluation stages.
- [ ] Re-audit every case from the new run without reusing the provisional
      rows.
- [ ] Replace `results/osf/` with the final path-free audit.
- [ ] Update README, this checklist, and the result validator with the final
      measured counts.
- [ ] Set `"provisional": false` and
      `"full_osf_rerun_complete": true` in `results/osf/summary.json`.
- [ ] Commit the final full-run results and push to GitHub `main`.
