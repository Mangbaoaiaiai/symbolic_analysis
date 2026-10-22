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

## Complete OSF audit

- [x] `results/osf/summary.json` records `"provisional": false` and
      `"full_osf_rerun_complete": true`.
- [x] `271 / 272` entries are supported or staged.
- [x] `195` entries entered symbolic execution.
- [x] `180` entries have both-side path artifacts.
- [x] `165` entries have complete exploration on both sides.
- [x] The strict audit reports `144` correct determinate outcomes: `72` EQ and
      `72` NEQ.
- [x] The strict audit reports zero `wrong_eq` and zero `wrong_neq`.
- [x] No conflicting stage verdicts remain.
- [x] Five source-level label inconsistencies and three final
      undefined-behavior exclusions remain visible per case.
- [x] Failure accounting reports 26 symbolic timeouts, 63 SIGKILL/OOM cases,
      15 incomplete explorations, 13 verifier/semantic unknowns, two
      no-complete-path cases, and one unsupported harness.
- [x] The upstream ARDiff 142-case subset has its own summary and case table.
- [x] The benchmark archive SHA-256 is
      `e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005`.

## Verification

- [x] The analysis image reports Python 3.12.15, GCC 12.2, angr/claripy
      9.2.192, and Z3 4.12.2.
- [x] The Docker unit/integration suite passes (`162` tests).
- [x] `python scripts/validate_delivery_results.py` passes for the complete
      OSF table.
- [x] `git diff --check` passes.
- [x] The curated tables contain no host or container work paths.

## Repository delivery

- [x] The completed 272-entry run has been re-audited across all stage and
      retry roots.
- [x] Missing evaluation reports for complete paths were regenerated.
- [x] Case-ID filtering is case-insensitive, so `_NEq` cases are not omitted.
- [x] Final result files replace the provisional aggregate.
- [x] README, result audit, checklist, and validator use the final counts.
- [x] Commit the final full-run results and push `main`.
