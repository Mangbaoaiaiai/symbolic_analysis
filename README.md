#  Benchmark 


## 关键文件


### 重要结果
- **`tsvc_analysis_demo_report.txt`** - 成功分析的总结报告
- **`tsvc_vs_pldi19_comparison.txt`** - 与PLDI19的对比分析

### 支持文件
- `improved_real_tsvc_analyzer.py` - 改进的真实angr分析器
- `semantic_equivalence_analyzer.py` - 语义等价性分析核心
- `angr_memory_analysis.py` - angr内存分析工具

## 成功案例

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

## 方法创新

1. **智能模拟**：针对不同benchmark类型和优化级别生成真实约束
2. **内存优化**：解决angr符号执行的内存限制问题  
3. **差异化分析**：从同质化结果转变为有意义的区分度分析