# Final Equivalence Results

| Bench | # M | Equivalent: Ours Res | Equivalent: Ours Time (s) | Equivalent: VERIBIN Res | Equivalent: VERIBIN Time (s) | Equivalent: Naive Res | Equivalent: Naive Time (s) | Not Equivalent: Ours Res | Not Equivalent: Ours Time (s) | Not Equivalent: VERIBIN Res | Not Equivalent: VERIBIN Time (s) | Not Equivalent: Naive Res | Not Equivalent: Naive Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Airy | 4 | 1/2 | 1.9476 | 1/2 | 1.9469 | 1/2 | 1.9720 | 2/2 | 1.9396 | 2/2 | 1.9336 | 2/2 | 1.9300 |
| Bess | 14 | 5/7 | 29.7991 | 5/7 | 29.9075 | 5/7 | 37.7240 | 6/7 | 47.9633 | 6/7 | 48.4780 | 6/7 | 49.8578 |
| Ell | 2 | 1/1 | 4.1231 | 1/1 | 4.0124 | 1/1 | 4.0193 | 1/1 | 4.2255 | 1/1 | 4.2305 | 1/1 | 4.2567 |
| ModDiff | 28 | 16/16 | 2.6901 | 16/16 | 2.6766 | 16/16 | 2.7222 | 11/12 | 2.9559 | 11/12 | 2.9488 | 11/12 | 2.9633 |
| Ran | 4 | 2/2 | 1.8848 | 2/2 | 1.8837 | 2/2 | 1.8854 | 1/2 | 4.4382 | 1/2 | 4.4052 | 1/2 | 4.4013 |
| caldat | 2 | 1/1 | 2.7609 | 1/1 | 2.7484 | 1/1 | 2.9548 | 1/1 | 2.9435 | 1/1 | 2.9878 | 1/1 | 2.9900 |
| dart | 2 | 0/1 | 3.4464 | 0/1 | 3.5074 | 0/1 | 3.4978 | 1/1 | 5.3978 | 1/1 | 5.4014 | 1/1 | 5.3145 |
| gam | 4 | 2/2 | 96.0264 | 2/2 | 96.4741 | 2/2 | 99.7830 | 1/2 | 125.1617 | 1/2 | 125.3101 | 1/2 | 128.4931 |
| power | 2 | 0/1 | 2.4372 | 0/1 | 2.4393 | 0/1 | 2.6193 | 1/1 | 2.3541 | 1/1 | 2.3529 | 1/1 | 2.3534 |
| Total | 62 | 28/33 | 14.0643 | 28/33 | 14.1059 | 28/33 | 15.9998 | 25/29 | 22.3867 | 25/29 | 22.5173 | 25/29 | 23.0734 |

Res = TP/TN/FP/FN classification against ground truth; Time (s) = T_total = T_se + T_align + T_smt.
