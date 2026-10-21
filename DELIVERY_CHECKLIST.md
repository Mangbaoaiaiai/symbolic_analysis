# Delivery Checklist

- [x] The README starts with an `Evaluation` hyperlink.
- [x] The first half documents pinned tools and one-command paper/OSF runs.
- [x] The paper benchmark reports `58/62` correct, `0` wrong, and `4` UNK.
- [x] The paper split reports `29/33` correct EQ and `29/29` correct NEQ.
- [x] All 272 OSF entries are present in the per-case audit.
- [x] `244` OSF entries are supported/staged and `176` entered symbolic execution.
- [x] `150` OSF entries have complete evidence on both sides.
- [x] The OSF audit reports `129` correct determinate outcomes.
- [x] The OSF audit reports zero `wrong_eq` and zero `wrong_neq` outcomes.
- [x] Five source-level label inconsistencies remain visible per case.
- [x] Three final undefined-behavior exclusions remain visible per case.
- [x] The failure audit reports `44` SIGKILL/OOM, `23` symbolic timeouts,
      `26` incomplete explorations, and `28` unsupported harnesses.
- [x] The upstream ARDiff 142-case subset has its own summary and case table.
- [x] The benchmark archive SHA-256 is
      `e3cdbb21ab079ed69d3a40286cebf4d21d0ec51ee64ca898d93a57d885ba4005`.
- [x] Generated path files, binaries, caches, and raw logs are excluded.
- [x] Shipped result tables contain no host or container work paths.
- [x] The source and benchmark licenses are included.
- [x] The Docker image reports Python 3.12.15, GCC 12.2, angr/claripy
      9.2.192, and Z3 4.12.2.
- [x] All 130 Docker unit/integration tests pass.
- [x] A one-case Docker smoke run completes from the release checkout.
- [x] A fresh fixed-62 regression completed with the exact expected totals.
- [x] The curated tables pass `python scripts/validate_delivery_results.py`.
- [x] Changes are committed normally and pushed to GitHub `main`.
