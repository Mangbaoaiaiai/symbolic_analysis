# Optimization-level equivalence analysis tool

A tool for verifying program equivalence across compiler optimization levels using symbolic execution and constraint-based semantic equivalence.

## Overview

This tool automatically analyzes semantic equivalence of programs under different compiler optimization levels. It uses symbolic execution to extract path constraints and the Z3 solver to verify logical equivalence between optimized versions.

## File description

- `se_script.py` - Symbolic execution script; generates path constraint files
- `semantic_equivalence_analyzer.py` - Semantic equivalence analyzer
- `run_benchmark_analysis.py` - Automated analysis script
- `README_benchmark_analysis.md` - This documentation

## Requirements

```bash
# Install dependencies
pip install angr z3-solver claripy
```

## Usage

### Method 1: One-shot automated analysis (recommended)

```bash
# Analyze entire benchmark directory
python run_benchmark_analysis.py benchmark_temp_s000

# Or specify timeout
python run_benchmark_analysis.py benchmark_temp_s000 --timeout 180

# Run symbolic execution only
python run_benchmark_analysis.py benchmark_temp_s000 --step se

# Run equivalence analysis only (assumes path files exist)
python run_benchmark_analysis.py benchmark_temp_s000 --step equiv
```

### Method 2: Step-by-step manual execution

#### Step 1: Symbolic execution
```bash
# Batch analyze all optimization levels
python se_script.py --benchmark benchmark_temp_s000

# Or analyze each binary separately
python se_script.py --binary benchmark_temp_s000/s000_O1 --output-prefix s000_O1
python se_script.py --binary benchmark_temp_s000/s000_O2 --output-prefix s000_O2
python se_script.py --binary benchmark_temp_s000/s000_O3 --output-prefix s000_O3
```

#### Step 2: Equivalence analysis
```bash
# Batch compare all optimization-level pairs
python semantic_equivalence_analyzer.py --benchmark benchmark_temp_s000

# Or manually compare specified levels
python semantic_equivalence_analyzer.py --prefix1 s000_O1 --prefix2 s000_O2
python semantic_equivalence_analyzer.py --prefix1 s000_O1 --prefix2 s000_O3
python semantic_equivalence_analyzer.py --prefix1 s000_O2 --prefix2 s000_O3
```

## Output files

### Symbolic execution phase

- `s000_O1_path_*.txt` - Path constraint files for O1
- `s000_O2_path_*.txt` - Path constraint files for O2
- `s000_O3_path_*.txt` - Path constraint files for O3
- `symbolic_execution_summary.txt` - Symbolic execution summary report

### Equivalence analysis phase

- `equivalence_report_s000_O1_vs_s000_O2.txt` - O1 vs O2 detailed comparison report
- `equivalence_report_s000_O1_vs_s000_O3.txt` - O1 vs O3 detailed comparison report
- `equivalence_report_s000_O2_vs_s000_O3.txt` - O2 vs O3 detailed comparison report
- `optimization_equivalence_summary.txt` - Overall equivalence summary

## Interpreting results

### Equivalence types

1. **Semantically equivalent** - The two optimized versions are logically equivalent
2. **Not equivalent** - Semantic differences exist; may be due to optimization-induced behavior changes
3. **Analysis error** - Z3 timeout or other technical issue

### Conclusion

- ✓ **Fully equivalent**: All path pairs are semantically equivalent
- ⚠ **Mostly equivalent**: Most paths equivalent, with a small number of differences
- ❌ **Differences present**: Significant semantic differences between optimization levels

## Example run

```bash
# Full analysis example
$ python run_benchmark_analysis.py benchmark_temp_s000

============================================================
Running: Symbolic execution analysis
Command: python se_script.py --benchmark benchmark_temp_s000 --timeout 120
============================================================
Found 3 binaries:
  benchmark_temp_s000/s000_O1
  benchmark_temp_s000/s000_O2
  benchmark_temp_s000/s000_O3

Analyzing: benchmark_temp_s000/s000_O1
Starting symbolic execution: benchmark_temp_s000/s000_O1
Finished s000_O1: 2 paths

Analyzing: benchmark_temp_s000/s000_O2
Finished s000_O2: 2 paths

Analyzing: benchmark_temp_s000/s000_O3
Finished s000_O3: 2 paths

============================================================
Running: Semantic equivalence analysis
Command: python semantic_equivalence_analyzer.py --benchmark benchmark_temp_s000
============================================================
Found 3 optimization levels:
  s000_O1: 2 path files
  s000_O2: 2 path files
  s000_O3: 2 path files

Comparing s000_O1 vs s000_O2
✓ Equivalent: path_1 <-> path_1
✓ Equivalent: path_2 <-> path_2

Overall conclusion: ✓ All optimization levels are semantically fully equivalent
```

## Advanced options

### Z3 solver timeout
```bash
python semantic_equivalence_analyzer.py --benchmark benchmark_temp_s000 --timeout 60000
```

### Custom output file
```bash
python semantic_equivalence_analyzer.py --prefix1 s000_O1 --prefix2 s000_O2 --output my_report.txt
```

## Troubleshooting

### Common issues

1. **angr load failure**
   - Ensure binaries have execute permission
   - Check that they are valid ELF

2. **Z3 timeout**
   - Increase the timeout parameter
   - Simplify program logic or reduce input variables

3. **Path files not found**
   - Run the symbolic execution step first
   - Verify file paths and prefixes

### Performance tips

- For complex programs, increase symbolic execution and Z3 timeouts
- Test the pipeline with a small benchmark first
- Batch mode is more efficient than analyzing individually

## Technical overview

1. **Symbolic execution**: Uses angr to run binary programs symbolically and produce path constraints
2. **Constraint extraction**: Converts angr constraints to SMT-LIB format
3. **Equivalence checking**: Uses Z3 to check whether `(F1 ∧ ¬F2) ∨ (¬F1 ∧ F2)` is satisfiable
4. **Interpretation**: If unsatisfiable, then F1≡F2, i.e. the two paths are semantically equivalent

This approach can detect semantic changes introduced by compiler optimizations and verify optimization correctness.
