
# Benchmark比较分析模板

## 如何进行编译器/工具链比较

### 数据准备
1. **Dataset1**: 第一组数据（如LLVM编译的程序）
2. **Dataset2**: 第二组数据（如GCC编译的程序）

### 期望的文件格式示例

#### 文件1: llvm_benchmarks.md
```
| 程序 | 符号执行(s) | 等价性分析(s) | 总时间(s) | 路径数 | 比较次数 | 平均SE时间 |
|------|-------------|---------------|-----------|--------|----------|------------|
| s000 | 89.2 | 1.90 | 91.1 | 64 | 6 | 22.3 |
| s121 | 68.9 | 1.14 | 70.0 | 48 | 3 | 23.0 |
```

#### 文件2: gcc_benchmarks.md  
```
| 程序 | 符号执行(s) | 等价性分析(s) | 总时间(s) | 路径数 | 比较次数 | 平均SE时间 |
|------|-------------|---------------|-----------|--------|----------|------------|
| s000-gcc | 95.5 | 2.1 | 97.6 | 64 | 6 | 23.9 |
| s121-gcc | 72.3 | 1.2 | 73.5 | 48 | 3 | 24.1 |
```

### 使用方法
```python
comparator = BenchmarkComparator()
comparator.load_data_from_md('llvm_benchmarks.md', 'dataset1')
comparator.load_data_from_md('gcc_benchmarks.md', 'dataset2') 
comparator.generate_comparison_report()
```
