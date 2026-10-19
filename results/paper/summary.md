# Paper evaluation summary

Primary manifest: `benchmarks\osf_all_paths_v2_merged`

Supplemental manifests fill only pair IDs absent from the primary manifest:

- `benchmarks\paper_v3_paths_bounded10_z3_412`

| Variant | Candidates | Path complete | Correct | Wrong | UNK | Verifier failed | Path failed | Correct rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all_72 | 72 | 64 | 60 | 0 | 4 | 0 | 8 | 93.75% |
| exclude_gam_erfcc | 70 | 62 | 58 | 0 | 4 | 0 | 8 | 93.55% |
| exclude_gam_gcf | 70 | 62 | 60 | 0 | 2 | 0 | 8 | 96.77% |
