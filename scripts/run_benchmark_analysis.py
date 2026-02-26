                      
"""
Benchmark analysis automation script.

Runs symbolic execution and semantic equivalence analysis in one flow.
Uses the improved symbolic execution script for benchmarks without external input.
"""

import os
import sys
import subprocess
import time
import argparse

def run_command(cmd, description):
    """Run command and show progress."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {cmd}")
    print(f"{'='*60}")
    
    start_time = time.time()
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    end_time = time.time()
    
    print(f"Elapsed: {end_time - start_time:.2f} s")
    
    if result.returncode == 0:
        print("✓ Success")
        if result.stdout:
            print("Output:")
            print(result.stdout)
    else:
        print("❌ Failed")
        print("Stderr:")
        print(result.stderr)
        return False
    
    return True

def analyze_benchmark(benchmark_dir, timeout=120, use_improved=True):
    """Analyze the whole benchmark."""
    print(f"Starting benchmark analysis: {benchmark_dir}")
    
    if not os.path.exists(benchmark_dir):
        print(f"Error: benchmark directory '{benchmark_dir}' does not exist")
        return False
    
    se_script = "se_script_improved.py" if use_improved else "se_script.py"
    
    print(f"\nStep 1: Run symbolic execution for all optimization levels using {se_script}")
    se_cmd = f"python {se_script} --benchmark {benchmark_dir} --timeout {timeout}"
    if not run_command(se_cmd, "Improved symbolic execution analysis"):
        return False
    
    print("\nStep 2: Run semantic equivalence analysis")
    equiv_cmd = f"python semantic_equivalence_analyzer.py --benchmark {benchmark_dir}"
    if not run_command(equiv_cmd, "Semantic equivalence analysis"):
        return False
    
    print("\nStep 3: Show analysis results")
    summary_file = os.path.join(benchmark_dir, "optimization_equivalence_summary.txt")
    if os.path.exists(summary_file):
        print("Analysis complete. Summary:")
        with open(summary_file, 'r', encoding='utf-8') as f:
            content = f.read()
            print(content)
        
        if "✓ 所有优化等级在语义上完全等价" in content or "all optimization levels are semantically fully equivalent" in content.lower():
            print("\n🎉 Conclusion: All optimization levels are semantically equivalent; compiler optimizations are safe.")
        elif "⚠ 大部分优化等级在语义上等价" in content or "mostly equivalent" in content.lower():
            print("\n⚠️  Conclusion: Mostly equivalent; check differing parts.")
        else:
            print("\n🔍 Conclusion: Optimization differences found. This may indicate:")
            print("   1. Compiler optimizations changed program behavior")
            print("   2. Further analysis of the differences is needed")
            print("   3. For benchmark programs, such differences may be expected")
    else:
        print("Summary file not found")
    
    return True

def main():
    parser = argparse.ArgumentParser(description='Benchmark analysis automation tool')
    parser.add_argument('benchmark_dir', help='Path to benchmark directory')
    parser.add_argument('--timeout', type=int, default=120, help='Symbolic execution timeout (seconds)')
    parser.add_argument('--step', choices=['se', 'equiv', 'all'], default='all', 
                       help='Step to run: se (symbolic execution only), equiv (equivalence only), all')
    parser.add_argument('--use-original', action='store_true', 
                       help='Use original symbolic execution script (for programs with input)')
    
    args = parser.parse_args()
    
    use_improved = not args.use_original
    se_script = "se_script.py" if args.use_original else "se_script_improved.py"
    
    if args.step in ['se', 'all']:
        print(f"Using script: {se_script}")
        se_cmd = f"python {se_script} --benchmark {args.benchmark_dir} --timeout {args.timeout}"
        if not run_command(se_cmd, "Symbolic execution analysis"):
            return
    
    if args.step in ['equiv', 'all']:
        equiv_cmd = f"python semantic_equivalence_analyzer.py --benchmark {args.benchmark_dir}"
        if not run_command(equiv_cmd, "Semantic equivalence analysis"):
            return
    
    summary_file = os.path.join(args.benchmark_dir, "optimization_equivalence_summary.txt")
    if os.path.exists(summary_file):
        print(f"\nAnalysis complete. Summary: {summary_file}")
        print("\nGenerated files:")
        path_files = subprocess.run(f"find {args.benchmark_dir} -name '*_path_*.txt' -type f 2>/dev/null", 
                                   shell=True, capture_output=True, text=True)
        if path_files.stdout:
            print("Path constraint files:")
            for file in sorted(path_files.stdout.strip().split('\n')):
                if file:
                    print(f"  {file}")
        report_files = subprocess.run(f"find {args.benchmark_dir} -name 'equivalence_report_*.txt' -type f 2>/dev/null", 
                                     shell=True, capture_output=True, text=True)
        if report_files.stdout:
            print("Equivalence reports:")
            for file in sorted(report_files.stdout.strip().split('\n')):
                if file:
                    print(f"  {file}")
        summary_files = subprocess.run(f"find {args.benchmark_dir} -name '*summary*.txt' -type f 2>/dev/null", 
                                      shell=True, capture_output=True, text=True)
        if summary_files.stdout:
            print("Summary reports:")
            for file in sorted(summary_files.stdout.strip().split('\n')):
                if file:
                    print(f"  {file}")

if __name__ == "__main__":
    main() 