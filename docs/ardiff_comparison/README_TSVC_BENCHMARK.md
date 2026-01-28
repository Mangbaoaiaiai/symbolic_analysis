# TSVC Benchmark 符号分析比较项目

这个项目将您的符号分析工具与PLDI 2019论文中的等价性检查器进行比较，使用相同的TSVC benchmarks。

## 项目概述

PLDI 2019论文"Semantic Program Alignment for Equivalence Checking"提出了一种基于语义对齐的程序等价性检查方法。本项目提取了该论文中使用的TSVC benchmarks，并提供了一个框架来使用您现有的符号分析工具进行分析，以便与原始结果进行比较。

## 文件结构

```
.
├── README_TSVC_BENCHMARK.md           # 本文档
├── tsvc_benchmark_runner.py           # TSVC benchmark提取和运行器
├── tsvc_symbolic_integration.py       # 符号分析工具集成器
├── quick_start_demo.py                # 快速演示脚本
├── semantic_equivalence_analyzer.py   # 您的语义等价性分析器
├── clang_improved.py                   # 您的Clang工具
└── pldi19-equivalence-checker/        # 克隆的原始项目
    └── pldi19/TSVC/clean.c            # TSVC benchmark源代码
```

## 环境要求

- Python 3.6+
- GCC编译器
- Z3求解器 (通过python-z3包)
- 必要的Python包：pathlib, json, subprocess

```bash
pip install z3-solver
```

## 快速开始

### 1. 检查文件

确保您已经克隆了PLDI19项目并且所有文件都在正确位置：

```bash
python -c "import os; print('TSVC源文件存在:', os.path.exists('pldi19-equivalence-checker/pldi19/TSVC/clean.c'))"
```

### 2. 运行快速演示

```bash
python quick_start_demo.py
```

这会运行一个简化的演示，展示整个工作流程。

### 3. 运行完整分析

```bash
python tsvc_symbolic_integration.py
```

这会运行所有推荐的benchmark并生成比较报告。

## TSVC Benchmarks

本项目使用的benchmark包括：

### 推荐的benchmarks（基于原论文）：
- `s000`: 简单向量加法 `a[i] = b[i] + 1`
- `s1112`: 反向循环向量操作
- `s121`: 向前依赖 `a[i] = a[i+1] + b[i]`
- `s1221`: 向后依赖 `a[i] = a[i-4] + b[i]`
- `s1251`: 复合赋值操作
- `s1351`: 条件赋值
- `s173`: 向量复制操作
- `s2244`: 多重赋值
- `vpv`, `vpvpv`, `vpvtv`, `vtv`, `vtvtv`: 各种向量操作模式

### 分析的优化级别：
- O1 vs O2
- O1 vs O3  
- O2 vs O3

## 输出结果

运行完成后，您会得到：

1. **tsvc_analysis_results/**: 包含每个benchmark的详细分析结果
2. **tsvc_vs_pldi19_comparison.txt**: 综合比较报告
3. **各种临时文件和路径文件**: 用于调试和详细分析

## 比较维度

本项目从以下维度比较您的方法与原始PLDI19方法：

1. **成功率**: 能够验证等价性的benchmark百分比
2. **性能**: 分析每个benchmark所需的时间
3. **准确性**: 与预期结果的一致性
4. **覆盖率**: 分析的执行路径数量

## 自定义和扩展

### 添加新的benchmark

在`TSVCBenchmarkExtractor`类中修改`recommended_benchmarks`列表：

```python
self.recommended_benchmarks = [
    's000', 's1112', 's121', 's1221', 's1251', 's1351', 
    's173', 's2244', 'vpv', 'vpvpv', 'vpvtv', 'vtv', 'vtvtv',
    'your_new_benchmark'  # 添加新的benchmark
]
```

### 集成您的路径生成工具

在`TSVCSymbolicIntegrator.generate_execution_paths()`方法中，替换模拟的路径生成代码为您实际的工具：

```python
def generate_execution_paths(self, binary_path, benchmark_name, num_paths=50):
    # 替换为您的实际路径生成代码
    # 例如：调用angr、SAGE、KLEE等符号执行引擎
    pass
```

### 自定义分析指标

在`analyze_path_equivalence()`方法中添加您的分析逻辑：

```python
def analyze_path_equivalence(self, paths1, paths2, comparison_name):
    # 添加您的自定义分析方法
    # 例如：基于约束求解、模型检查等
    pass
```

## 已知限制

1. **环境限制**: 当前环境不支持AVX指令，无法运行原始PLDI19工具进行直接比较
2. **路径生成**: 目前使用模拟的路径约束，需要集成实际的符号执行引擎
3. **性能**: 某些复杂benchmark可能需要大量计算资源

## 故障排除

### 编译错误
如果遇到编译错误，检查：
- GCC是否正确安装
- 是否有足够的权限创建临时文件
- 源代码语法是否正确

### 路径生成失败
如果路径生成失败：
- 检查二进制文件是否正确生成
- 确保有足够的磁盘空间
- 验证路径生成工具的配置

### 分析超时
如果分析过程超时：
- 减少分析的路径数量
- 增加超时限制
- 使用更快的求解器配置

## 与原始结果的比较

原始PLDI19论文报告的结果：
- 在云环境中使用多个SMT求解器（Z3、CVC4）
- 支持并行验证多个证明义务
- 在支持AVX指令的机器上运行
- 某些benchmark需要1000+ CPU小时

我们的方法：
- 单机环境，单线程分析
- 使用Z3求解器
- 基于路径聚类和约束等价性检查
- 针对相同的benchmark进行对比分析

## 结果解读

分析完成后，查看`tsvc_vs_pldi19_comparison.txt`文件：

```
=== 统计概览 ===
成功分析: 10
分析失败: 3  
成功率: 76.9%

=== 与PLDI19原始结果的比较 ===
s000: PLDI19=成功, 我们的方法=成功
s121: PLDI19=成功, 我们的方法=失败
...
```

## 贡献和改进

欢迎提交改进建议：
1. 更准确的路径生成方法
2. 更高效的约束求解策略
3. 更全面的等价性判断标准
4. 更详细的性能分析指标

## 参考文献

- Churchill, B., Padon, O., Sharma, R., & Aiken, A. (2019). Semantic program alignment for equivalence checking. PLDI 2019.
- TSVC Benchmark Suite: https://github.com/bchurchill/pldi19-equivalence-checker 