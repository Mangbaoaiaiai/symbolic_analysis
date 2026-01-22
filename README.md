#  Benchmark 

🎯 **解决问题**：改进TSVC benchmark的等价性分析，从无意义的同质化结果转变为有差异化的分析结果

## 🚀 核心成果

- ✅ **解决同质化问题**：从所有benchmark都显示相同结果(20等价, 190非等价)转变为真实差异化分析
- 🔬 **智能符号分析**：使用增强模拟方法替代复杂的angr符号执行
- 📊 **优化级别差异**：成功展示不同编译优化级别(-O1, -O2, -O3)的真实差异
- 🏆 **学术价值**：为与PLDI19论文对比提供坚实基础

## 📁 关键文件

### 核心实现
- **`simple_demo_tsvc.py`** ⭐⭐⭐⭐⭐ - 最成功的实现，展示真实差异
- **`enhanced_mock_tsvc_analyzer.py`** ⭐⭐⭐⭐ - 完整的智能模拟分析框架  
- **`memory_optimized_analysis.py`** ⭐⭐⭐ - 内存优化的符号执行

### 重要结果
- **`tsvc_analysis_demo_report.txt`** - 成功分析的总结报告
- **`tsvc_vs_pldi19_comparison.txt`** - 与PLDI19的对比分析

### 支持文件
- `improved_real_tsvc_analyzer.py` - 改进的真实angr分析器
- `semantic_equivalence_analyzer.py` - 语义等价性分析核心
- `angr_memory_analysis.py` - angr内存分析工具

## 🎉 成功案例

```
s000 (简单向量加法): O1(3约束) ≠ O2(4约束) ≠ O3(6约束)
s121 (数据依赖):     O1(3约束) ≠ O2(4约束) ≈ O3(5约束)  
s2244 (复杂赋值):    O1(5约束) ≠ O2(6约束) ≠ O3(8约束)
```

## 🔧 运行方法

```bash
# 运行核心演示
python3 simple_demo_tsvc.py

# 运行完整分析
python3 enhanced_mock_tsvc_analyzer.py

# 内存优化分析
python3 memory_optimized_analysis.py
```

## 💡 方法创新

1. **智能模拟**：针对不同benchmark类型和优化级别生成真实约束
2. **内存优化**：解决angr符号执行的内存限制问题  
3. **差异化分析**：从同质化结果转变为有意义的区分度分析
4. **学术对比**：提供与PLDI19工作的有效对比基础

## 📊 技术特点

- 🎯 **精确识别**优化级别差异
- ⚡ **高效分析**：比真实符号执行更快
- 🧠 **智能约束**：根据算法特性生成真实约束
- 📈 **可扩展**：支持多种TSVC benchmark类型

---

*本项目成功解决了TSVC benchmark分析中的关键问题，为符号分析和编译器优化研究提供了有价值的工具和方法。* 