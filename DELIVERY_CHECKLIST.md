# Delivery Checklist

- [x] The README starts with an `Evaluation` hyperlink.
- [x] The first half documents the pinned toolchain and one-command rerun.
- [x] The second half contains the paper benchmark and complete OSF tables.
- [x] The paper benchmark reports 58/62 correct and 4 UNK.
- [x] The OSF table reports 0 algorithmic `wrong_eq` and 0 `wrong_neq`.
- [x] The three remaining audited label inconsistencies remain visible per case.
- [x] `gam/factln_Neq` is verified as NEQ from its ordered output difference,
      with a native replay witness for `n=-100`.
- [x] The complete benchmark archive, license, and manifests are included.
- [x] Generated path files, compiled binaries, and raw logs are excluded.
- [x] The Docker image builds and reports Python 3.12.15, GCC 12.2,
      angr/claripy 9.2.192, and Z3 4.12.2.
- [x] All 53 tests pass inside the built image.
- [x] `python run_experiment.py --suite paper --max-cases 1` completes.
