# Final Equivalence Results

| Bench | # M | Equivalent: Ours Res | Equivalent: Ours Time (s) | Equivalent: VERIBIN Res | Equivalent: VERIBIN Time (s) | Equivalent: Naive Res | Equivalent: Naive Time (s) | Not Equivalent: Ours Res | Not Equivalent: Ours Time (s) | Not Equivalent: VERIBIN Res | Not Equivalent: VERIBIN Time (s) | Not Equivalent: Naive Res | Not Equivalent: Naive Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Airy | 4 | 2/2 | 1.9313 | 2/2 | 1.9286 | 2/2 | 1.9489 | 2/2 | 1.9173 | 2/2 | 1.9156 | 2/2 | 1.9017 |
| Bess | 10 | 4/5 | 39.5038 | 4/5 | 39.7770 | 4/5 | 39.5321 | 5/5 | 42.8039 | 5/5 | 41.9761 | 5/5 | 41.7482 |
| Ell | 4 | 2/2 | 40.4176 | 2/2 | 40.3999 | 2/2 | 40.4262 | 1/2 | 47.1318 | 1/2 | 47.1001 | 1/2 | 47.1053 |
| ModDiff | 28 | 16/16 | 2.6964 | 16/16 | 2.6807 | 16/16 | 2.7200 | 11/12 | 3.0198 | 11/12 | 3.0122 | 11/12 | 3.0280 |
| Ran | 4 | 2/2 | 1.7464 | 2/2 | 1.7623 | 2/2 | 1.7835 | 1/2 | 1.7769 | 1/2 | 1.7748 | 1/2 | 1.7746 |
| caldat | 2 | 1/1 | 1.6604 | 1/1 | 1.6590 | 1/1 | 1.6587 | 1/1 | 1.6120 | 1/1 | 1.6109 | 1/1 | 1.6112 |
| dart | 2 | 0/1 | 3.5187 | 0/1 | 3.5127 | 0/1 | 3.5056 | 1/1 | 5.3954 | 1/1 | 5.3978 | 1/1 | 5.3132 |
| gam | 4 | 1/1 | 8.9080 | 1/1 | 8.8746 | 1/1 | 8.9179 | 1/2 | 52.9069 | 1/2 | 51.9703 | 1/2 | 54.7614 |
| power | 2 | 0/1 | 2.4854 | 0/1 | 2.4919 | 0/1 | 2.6244 | 1/1 | 2.4027 | 1/1 | 2.4099 | 1/1 | 2.4477 |
| Total | 60 | 28/31 | 11.0729 | 28/31 | 11.1054 | 28/31 | 11.0975 | 24/28 | 16.6833 | 24/28 | 16.4631 | 24/28 | 16.6263 |

Res = TP/TN/FP/FN classification against ground truth; Time (s) = T_total = T_se + T_align + T_smt.
