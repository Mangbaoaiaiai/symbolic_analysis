# Evaluation Summary by Subset

| Method | Subset A ACC % | Subset A Hit@1 % | Subset A Hit@3 % | Subset A MRR | Subset A T_se s | Subset A T_align s | Subset A T_smt s | Subset A T_total s | Subset A Pruning % | Subset B ACC % | Subset B Hit@1 % | Subset B Hit@3 % | Subset B MRR | Subset B T_se s | Subset B T_align s | Subset B T_smt s | Subset B T_total s | Subset B Pruning % | Subset C ACC % | Subset C Hit@1 % | Subset C Hit@3 % | Subset C MRR | Subset C T_se s | Subset C T_align s | Subset C T_smt s | Subset C T_total s | Subset C Pruning % | Subset D ACC % | Subset D Hit@1 % | Subset D Hit@3 % | Subset D MRR | Subset D T_se s | Subset D T_align s | Subset D T_smt s | Subset D T_total s | Subset D Pruning % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Naive | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA |
| VERIBIN | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA |
| Ours | NA | 60.5556 | 66.6667 | 0.6727 | NA | NA | NA | NA | NA | NA | 10.5556 | 23.3333 | 0.2585 | NA | NA | NA | NA | NA | NA | 10.5556 | 23.3333 | 0.2570 | NA | NA | NA | NA | NA | NA | 6.2500 | 18.7500 | 0.2181 | NA | NA | NA | NA | NA |

Confusion counts use the ground-truth label per binary pair: TP/TN are correct decisions; FP/FN are wrong decisions.
Ranking metrics use path-level ground truth: Hit@1 is the percentage of queries whose correct match is ranked first; Hit@3 counts ranks 1-3; MRR averages reciprocal rank.
T_se is symbolic-execution time for old/new binaries; T_total = T_se + T_align + T_smt.
Pruning % = (1 - SMT_calls / (original_path_count * patched_path_count)) * 100.
