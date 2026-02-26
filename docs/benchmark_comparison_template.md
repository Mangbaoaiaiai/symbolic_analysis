
# Benchmark comparison analysis template

## How to compare compilers / toolchains

### Data preparation
1. **Dataset1**: First dataset (e.g. LLVM-compiled programs)
2. **Dataset2**: Second dataset (e.g. GCC-compiled programs)

### Expected file format example

#### File 1: llvm_benchmarks.md
```
| Program | Symbolic execution (s) | Equivalence analysis (s) | Total time (s) | Paths | Comparisons | Avg SE time |
|---------|------------------------|---------------------------|----------------|-------|-------------|-------------|
| s000 | 89.2 | 1.90 | 91.1 | 64 | 6 | 22.3 |
| s121 | 68.9 | 1.14 | 70.0 | 48 | 3 | 23.0 |
```

#### File 2: gcc_benchmarks.md
```
| Program | Symbolic execution (s) | Equivalence analysis (s) | Total time (s) | Paths | Comparisons | Avg SE time |
|---------|------------------------|---------------------------|----------------|-------|-------------|-------------|
| s000-gcc | 95.5 | 2.1 | 97.6 | 64 | 6 | 23.9 |
| s121-gcc | 72.3 | 1.2 | 73.5 | 48 | 3 | 24.1 |
```

### Usage
```python
comparator = BenchmarkComparator()
comparator.load_data_from_md('llvm_benchmarks.md', 'dataset1')
comparator.load_data_from_md('gcc_benchmarks.md', 'dataset2')
comparator.generate_comparison_report()
```
