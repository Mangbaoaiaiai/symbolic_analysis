# Final Equivalence Results

| Bench | # M | Equivalent: Ours Res | Equivalent: Ours Time (s) | Equivalent: VERIBIN Res | Equivalent: VERIBIN Time (s) | Equivalent: Naive Res | Equivalent: Naive Time (s) | Not Equivalent: Ours Res | Not Equivalent: Ours Time (s) | Not Equivalent: VERIBIN Res | Not Equivalent: VERIBIN Time (s) | Not Equivalent: Naive Res | Not Equivalent: Naive Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Airy | 4 | 2/2 | 1.9940 | 2/2 | 1.9900 | 2/2 | 1.9767 | 2/2 | 1.9881 | 2/2 | 1.9693 | 2/2 | 1.9879 |
| Bess | 14 | 3/7 | 15.3591 | 3/7 | 15.4321 | 3/7 | 15.4395 | 7/7 | 16.9225 | 7/7 | 16.9170 | 7/7 | 17.0179 |
| Ell | 2 | 1/1 | 4.1000 | 1/1 | 3.9978 | 1/1 | 4.0067 | NA | 2.6784 | NA | 2.6658 | NA | 2.6697 |
| ModDiff | 28 | 16/16 | 2.6912 | 16/16 | 2.6781 | 16/16 | 2.7232 | 11/12 | 2.9596 | 11/12 | 2.9493 | 11/12 | 2.9640 |
| Ran | 4 | 2/2 | 1.9822 | 2/2 | 1.9812 | 2/2 | 1.9855 | 1/2 | 3.9802 | 1/2 | 3.9738 | 1/2 | 3.9832 |
| caldat | 2 | 1/1 | 2.9677 | 1/1 | 2.9650 | 1/1 | 3.1659 | 1/1 | 3.1430 | 1/1 | 3.1977 | 1/1 | 3.1981 |
| dart | 2 | 0/1 | 3.4562 | 0/1 | 3.5028 | 0/1 | 3.5384 | 1/1 | 5.3930 | 1/1 | 5.3916 | 1/1 | 5.3011 |
| gam | 4 | 0/2 | 86.0060 | 0/2 | 86.0458 | 0/2 | 86.0063 | 2/2 | 86.7320 | 2/2 | 86.3041 | 2/2 | 85.8034 |
| power | 2 | 0/1 | 2.4951 | 0/1 | 2.4943 | 0/1 | 2.6836 | 1/1 | 2.3974 | 1/1 | 2.3956 | 1/1 | 2.3943 |
| Total | 62 | 25/33 | 10.4108 | 25/33 | 10.4203 | 25/33 | 10.4539 | 26/28 | 12.1719 | 26/28 | 12.1364 | 26/28 | 12.1312 |

Res = TP/TN/FP/FN classification against ground truth; Time (s) = T_total = T_se + T_align + T_smt.
