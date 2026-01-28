# Benchmark验证过程完整时间统计报告

## 总体统计

| 指标 | 数值 | 说明 |
|------|------|------|
| **符号执行总时间** | **212.8秒** (3.5分钟) | 占总时间74.2% |
| **等价性分析总时间** | **73.8秒** | 占总时间25.8% |
| **总验证时间** | **286.6秒** (4.8分钟) | 完整验证流程 |
| **分析程序对数** | **55个** | 30个Eq + 25个NEq |
| **总路径数** | **348条** | 符号执行生成 |
| **总比较次数** | **262次** | 路径对比较 |
| **预测准确率** | **60.0%** | 33/55正确 |

## 分类统计

| 类型 | 程序数 | 符号执行时间 | 等价性分析时间 | 正确预测 | 准确率 |
|------|--------|--------------|----------------|----------|--------|
| **Eq (应该等价)** | 30 | 112.0s | 65.2s | 22 | 73.3% |
| **NEq (应该不等价)** | 25 | 100.7s | 8.7s | 11 | 44.0% |

## 详细时间统计

| Benchmark | 类型 | 符号执行(s) | 等价性分析(s) | 总时间(s) | 路径数 | 比较次数 | 预测结果 | 准确性 |
|-----------|------|-------------|---------------|-----------|--------|----------|----------|--------|
| **Airy_MAX_Eq** | Eq | 3.5 | 0.2 | **3.6** | 4 | 4 | ❌ | ❌ |
| **Airy_MAX_Eq_instrumented** | Eq | 4.2 | 0.1 | **4.4** | 4 | 4 | ❌ | ❌ |
| **Airy_MAX_NEq** | NEq | 3.4 | 0.1 | **3.5** | 4 | 2 | ✅ | ❌ |
| **Airy_Sign_Eq** | Eq | 2.3 | 0.2 | **2.4** | 8 | 5 | ✅ | ✅ |
| **Airy_Sign_NEq** | NEq | 2.5 | 0.2 | **2.7** | 8 | 6 | ❌ | ✅ |
| **Bess_SIGN_Eq** | Eq | 2.2 | 0.1 | **2.4** | 8 | 5 | ✅ | ✅ |
| **Bess_SIGN_NEq** | NEq | 2.2 | 0.2 | **2.4** | 8 | 6 | ❌ | ✅ |
| **Bess_SQR_Eq** | Eq | 2.9 | 0.1 | **3.0** | 2 | 1 | ✅ | ✅ |
| **Bess_SQR_NEq** | NEq | 2.8 | 0.1 | **2.8** | 2 | 1 | ✅ | ❌ |
| **Bess_bessi0_Eq** | Eq | 2.0 | 0.1 | **2.1** | 4 | 2 | ✅ | ✅ |
| **Bess_bessi0_NEq** | NEq | 2.1 | 0.1 | **2.1** | 4 | 2 | ✅ | ❌ |
| **Bess_bessi1_Eq** | Eq | 5.3 | 0.1 | **5.4** | 8 | 4 | ✅ | ✅ |
| **Bess_bessi1_NEq** | NEq | 6.7 | 1.1 | **7.8** | 9 | 20 | ❌ | ✅ |
| **Bess_probks_Eq** | Eq | 3.5 | 0.1 | **3.6** | 4 | 2 | ✅ | ✅ |
| **Bess_probks_NEq** | NEq | 2.8 | 0.1 | **2.9** | 4 | 2 | ✅ | ❌ |
| **Ell_rc_Eq** | Eq | 22.4 | 0.1 | **22.5** | 6 | 3 | ✅ | ✅ |
| **Ell_rc_NEq** | NEq | 24.5 | 1.1 | **25.6** | 5 | 6 | ❌ | ✅ |
| **ModDiff_Eq_Add** | Eq | 3.0 | 0.1 | **3.1** | 2 | 1 | ✅ | ✅ |
| **ModDiff_Eq_Comp** | Eq | 1.5 | 0.1 | **1.6** | 2 | 1 | ✅ | ✅ |
| **ModDiff_Eq_Const** | Eq | 2.8 | 0.1 | **2.9** | 2 | 1 | ✅ | ✅ |
| **ModDiff_Eq_LoopMult10** | Eq | 2.4 | 0.2 | **2.6** | 8 | 5 | ❌ | ❌ |
| **ModDiff_Eq_LoopMult15** | Eq | 2.6 | 0.2 | **2.8** | 8 | 5 | ❌ | ❌ |
| **ModDiff_Eq_LoopMult20** | Eq | 3.4 | 0.2 | **3.6** | 9 | 6 | ❌ | ❌ |
| **ModDiff_Eq_LoopMult5** | Eq | 2.1 | 0.1 | **2.2** | 7 | 4 | ❌ | ❌ |
| **ModDiff_Eq_LoopSub** | Eq | 1.5 | 0.1 | **1.5** | 2 | 1 | ✅ | ✅ |
| **ModDiff_Eq_LoopUnreach10** | Eq | 2.0 | 0.1 | **2.1** | 6 | 3 | ✅ | ✅ |
| **ModDiff_Eq_LoopUnreach15** | Eq | 2.2 | 0.1 | **2.3** | 6 | 3 | ✅ | ✅ |
| **ModDiff_Eq_LoopUnreach2** | Eq | 1.9 | 0.1 | **2.0** | 6 | 3 | ✅ | ✅ |
| **ModDiff_Eq_LoopUnreach20** | Eq | 1.9 | 0.1 | **2.0** | 6 | 3 | ✅ | ✅ |
| **ModDiff_Eq_LoopUnreach5** | Eq | 2.2 | 0.1 | **2.3** | 6 | 3 | ✅ | ✅ |
| **ModDiff_Eq_Sub** | Eq | 1.5 | 0.1 | **1.6** | 2 | 1 | ✅ | ✅ |
| **ModDiff_NEq_LoopMult10** | NEq | 1.9 | 0.2 | **2.1** | 8 | 5 | ❌ | ✅ |
| **ModDiff_NEq_LoopMult15** | NEq | 1.9 | 0.2 | **2.1** | 8 | 5 | ❌ | ✅ |
| **ModDiff_NEq_LoopMult20** | NEq | 2.1 | 0.2 | **2.3** | 9 | 6 | ❌ | ✅ |
| **ModDiff_NEq_LoopMult5** | NEq | 1.7 | 0.1 | **1.8** | 7 | 4 | ❌ | ✅ |
| **ModDiff_NEq_LoopSub** | NEq | 2.5 | 0.1 | **2.6** | 4 | 1 | ✅ | ❌ |
| **ModDiff_NEq_LoopUnreach10** | NEq | 1.7 | 0.1 | **1.8** | 6 | 3 | ✅ | ❌ |
| **ModDiff_NEq_LoopUnreach15** | NEq | 1.6 | 0.1 | **1.7** | 6 | 3 | ✅ | ❌ |
| **ModDiff_NEq_LoopUnreach2** | NEq | 1.7 | 0.1 | **1.8** | 6 | 3 | ✅ | ❌ |
| **ModDiff_NEq_LoopUnreach20** | NEq | 1.6 | 0.1 | **1.7** | 6 | 3 | ✅ | ❌ |
| **ModDiff_NEq_LoopUnreach5** | NEq | 1.6 | 0.1 | **1.7** | 6 | 3 | ✅ | ❌ |
| **Ran_gammln_Eq** | Eq | 2.9 | 0.1 | **3.0** | 2 | 1 | ✅ | ✅ |
| **Ran_gammln_NEq** | NEq | 2.9 | 0.1 | **3.0** | 2 | 1 | ❌ | ✅ |
| **Ran_ranzero_Eq** | Eq | 3.6 | 60.2 | **63.8** | 4 | 4 | ❌ | ❌ |
| **Ran_ranzero_NEq** | NEq | 3.8 | 0.1 | **3.9** | 4 | 2 | ✅ | ❌ |
| **caldat_julday_Eq** | Eq | 10.6 | 0.2 | **10.8** | 18 | 9 | ✅ | ✅ |
| **caldat_julday_NEq** | NEq | 10.9 | 0.2 | **11.1** | 18 | 9 | ✅ | ❌ |
| **dart_test_Eq** | Eq | 2.2 | 1.1 | **3.3** | 9 | 18 | ❌ | ❌ |
| **dart_test_NEq** | NEq | 2.5 | 2.1 | **4.6** | 12 | 36 | ❌ | ✅ |
| **gam_ei_Eq** | Eq | 9.9 | 0.8 | **10.7** | 10 | 5 | ✅ | ✅ |
| **gam_ei_NEq** | NEq | 11.6 | 1.9 | **13.5** | 11 | 12 | ❌ | ✅ |
| **gam_erfcc_Eq** | Eq | 1.6 | 0.1 | **1.7** | 4 | 2 | ✅ | ✅ |
| **gam_erfcc_NEq** | NEq | 1.7 | 0.1 | **1.8** | 4 | 2 | ✅ | ❌ |
| **power_test_Eq** | Eq | 2.1 | 0.1 | **2.2** | 10 | 5 | ✅ | ✅ |
| **power_test_NEq** | NEq | 2.0 | 0.1 | **2.1** | 10 | 5 | ✅ | ❌ |

## 错误预测分析

### Eq程序被错误预测为不等价:

- `benchmarks/Airy/MAX/Eq` (符号执行: 3.5s, 分析: 0.2s)
- `benchmarks/Airy/MAX/Eq/instrumented` (符号执行: 4.2s, 分析: 0.1s)
- `benchmarks/ModDiff/Eq/LoopMult10` (符号执行: 2.4s, 分析: 0.2s)
- `benchmarks/ModDiff/Eq/LoopMult15` (符号执行: 2.6s, 分析: 0.2s)
- `benchmarks/ModDiff/Eq/LoopMult20` (符号执行: 3.4s, 分析: 0.2s)
- `benchmarks/ModDiff/Eq/LoopMult5` (符号执行: 2.1s, 分析: 0.1s)
- `benchmarks/Ran/ranzero/Eq` (符号执行: 3.6s, 分析: 60.2s)
- `benchmarks/dart/test/Eq` (符号执行: 2.2s, 分析: 1.1s)

### NEq程序被错误预测为等价:

- `benchmarks/Airy/MAX/NEq` (符号执行: 3.4s, 分析: 0.1s)
- `benchmarks/Bess/SQR/NEq` (符号执行: 2.8s, 分析: 0.1s)
- `benchmarks/Bess/bessi0/NEq` (符号执行: 2.1s, 分析: 0.1s)
- `benchmarks/Bess/probks/NEq` (符号执行: 2.8s, 分析: 0.1s)
- `benchmarks/ModDiff/NEq/LoopSub` (符号执行: 2.5s, 分析: 0.1s)
- `benchmarks/ModDiff/NEq/LoopUnreach10` (符号执行: 1.7s, 分析: 0.1s)
- `benchmarks/ModDiff/NEq/LoopUnreach15` (符号执行: 1.6s, 分析: 0.1s)
- `benchmarks/ModDiff/NEq/LoopUnreach2` (符号执行: 1.7s, 分析: 0.1s)
- `benchmarks/ModDiff/NEq/LoopUnreach20` (符号执行: 1.6s, 分析: 0.1s)
- `benchmarks/ModDiff/NEq/LoopUnreach5` (符号执行: 1.6s, 分析: 0.1s)
- `benchmarks/Ran/ranzero/NEq` (符号执行: 3.8s, 分析: 0.1s)
- `benchmarks/caldat/julday/NEq` (符号执行: 10.9s, 分析: 0.2s)
- `benchmarks/gam/erfcc/NEq` (符号执行: 1.7s, 分析: 0.1s)
- `benchmarks/power/test/NEq` (符号执行: 2.0s, 分析: 0.1s)

## 性能分析

- **平均符号执行时间**: 3.9秒/程序对
- **平均等价性分析时间**: 1.3秒/程序对
- **平均路径数**: 6.3条/程序对
- **平均比较次数**: 4.8次/程序对
- **符号执行效率**: 1.6路径/秒
- **等价性分析效率**: 3.5比较/秒
