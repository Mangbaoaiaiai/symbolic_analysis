# 优化等级等价性分析工具

基于符号执行和约束语义等价性的程序优化等级验证工具

## 功能概述

这套工具可以自动分析不同编译器优化等级下程序的语义等价性，通过符号执行提取程序路径约束，然后使用Z3求解器验证不同优化版本的逻辑等价性。

## 文件说明

- `se_script.py` - 符号执行脚本，生成路径约束文件
- `semantic_equivalence_analyzer.py` - 语义等价性分析器
- `run_benchmark_analysis.py` - 自动化分析脚本
- `README_benchmark_analysis.md` - 本说明文档

## 环境要求

```bash
# 安装依赖
pip install angr z3-solver claripy
```

## 使用方法

### 方法1: 一键自动化分析（推荐）

```bash
# 分析整个benchmark目录
python run_benchmark_analysis.py benchmark_temp_s000

# 或者指定超时时间
python run_benchmark_analysis.py benchmark_temp_s000 --timeout 180

# 只运行符号执行
python run_benchmark_analysis.py benchmark_temp_s000 --step se

# 只运行等价性分析（假设已有路径文件）
python run_benchmark_analysis.py benchmark_temp_s000 --step equiv
```

### 方法2: 分步手动执行

#### 步骤1: 符号执行
```bash
# 批量分析所有优化等级
python se_script.py --benchmark benchmark_temp_s000

# 或者分别分析每个二进制文件
python se_script.py --binary benchmark_temp_s000/s000_O1 --output-prefix s000_O1
python se_script.py --binary benchmark_temp_s000/s000_O2 --output-prefix s000_O2
python se_script.py --binary benchmark_temp_s000/s000_O3 --output-prefix s000_O3
```

#### 步骤2: 等价性分析
```bash
# 批量比较所有优化等级对
python semantic_equivalence_analyzer.py --benchmark benchmark_temp_s000

# 或者手动比较指定的优化等级
python semantic_equivalence_analyzer.py --prefix1 s000_O1 --prefix2 s000_O2
python semantic_equivalence_analyzer.py --prefix1 s000_O1 --prefix2 s000_O3
python semantic_equivalence_analyzer.py --prefix1 s000_O2 --prefix2 s000_O3
```

## 输出文件说明

### 符号执行阶段生成的文件

- `s000_O1_path_*.txt` - O1优化等级的路径约束文件
- `s000_O2_path_*.txt` - O2优化等级的路径约束文件  
- `s000_O3_path_*.txt` - O3优化等级的路径约束文件
- `symbolic_execution_summary.txt` - 符号执行摘要报告

### 等价性分析阶段生成的文件

- `equivalence_report_s000_O1_vs_s000_O2.txt` - O1 vs O2详细比较报告
- `equivalence_report_s000_O1_vs_s000_O3.txt` - O1 vs O3详细比较报告
- `equivalence_report_s000_O2_vs_s000_O3.txt` - O2 vs O3详细比较报告
- `optimization_equivalence_summary.txt` - 总体等价性摘要

## 分析结果解读

### 等价性类型

1. **语义等价** - 两个优化版本在逻辑上完全等价
2. **非等价** - 存在语义差异，可能是优化引入的行为改变
3. **分析错误** - Z3求解超时或其他技术问题

### 结论判断

- ✓ **完全等价**: 所有路径对都语义等价
- ⚠ **大部分等价**: 大多数路径等价，但存在少量差异
- ❌ **存在差异**: 优化等级间有显著的语义差异

## 示例运行

```bash
# 完整分析示例
$ python run_benchmark_analysis.py benchmark_temp_s000

============================================================
正在执行: 符号执行分析
命令: python se_script.py --benchmark benchmark_temp_s000 --timeout 120
============================================================
发现 3 个二进制文件:
  benchmark_temp_s000/s000_O1
  benchmark_temp_s000/s000_O2
  benchmark_temp_s000/s000_O3

正在分析: benchmark_temp_s000/s000_O1
开始符号执行: benchmark_temp_s000/s000_O1
完成分析 s000_O1: 共 2 条路径

正在分析: benchmark_temp_s000/s000_O2
完成分析 s000_O2: 共 2 条路径

正在分析: benchmark_temp_s000/s000_O3
完成分析 s000_O3: 共 2 条路径

============================================================
正在执行: 语义等价性分析
命令: python semantic_equivalence_analyzer.py --benchmark benchmark_temp_s000
============================================================
发现 3 个优化等级:
  s000_O1: 2 个路径文件
  s000_O2: 2 个路径文件
  s000_O3: 2 个路径文件

比较 s000_O1 vs s000_O2
✓ 等价: path_1 <-> path_1
✓ 等价: path_2 <-> path_2

总体结论: ✓ 所有优化等级在语义上完全等价
```

## 高级选项

### 调整Z3求解器超时
```bash
python semantic_equivalence_analyzer.py --benchmark benchmark_temp_s000 --timeout 60000
```

### 自定义输出文件
```bash
python semantic_equivalence_analyzer.py --prefix1 s000_O1 --prefix2 s000_O2 --output my_report.txt
```

## 故障排除

### 常见问题

1. **angr加载失败**
   - 确保二进制文件有执行权限
   - 检查是否为正确的ELF格式

2. **Z3求解超时**
   - 增加timeout参数值
   - 简化程序逻辑或减少输入变量

3. **路径文件未找到**
   - 确保先运行符号执行步骤
   - 检查文件路径和前缀是否正确

### 性能优化建议

- 对于复杂程序，建议增加符号执行和Z3求解的超时时间
- 可以先用小型benchmark测试工具链是否正常工作
- 批量模式比单独分析更高效

## 技术原理

1. **符号执行**: 使用angr框架对二进制程序进行符号执行，为每条路径生成约束条件
2. **约束提取**: 将angr的约束转换为SMT-LIB格式
3. **等价性验证**: 使用Z3求解器检查 `(F1 ∧ ¬F2) ∨ (¬F1 ∧ F2)` 是否可满足
4. **结果解释**: 如果不可满足则F1≡F2，即两个路径语义等价

这种方法可以发现编译器优化引入的语义变化，验证优化的正确性。 