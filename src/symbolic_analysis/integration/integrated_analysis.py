                      
"""
Integrated symbolic-execution and equivalence-analysis tool.

Combines symbolic execution with semantic equivalence analysis to provide a
complete analysis pipeline and detailed timing statistics.
"""

import os
import time
import datetime
import argparse
import glob
from collections import defaultdict
import re                                               

        
from se_script import BenchmarkAnalyzer, ImprovedPathAnalyzer
from semantic_equivalence_analyzer import BenchmarkEquivalenceAnalyzer, PathClusterAnalyzer

class ProgramSpecificEquivalenceAnalyzer:
    """Equivalence analyzer focusing on a single target program."""
    
    def __init__(self, benchmark_dir, program_name):
        self.benchmark_dir = benchmark_dir
        self.program_name = program_name
        self.analyzer = PathClusterAnalyzer()
        
    def find_program_optimization_levels(self):
        """Find all optimization-level path files for the target program."""
        optimization_levels = {}
        
                      
        pattern = os.path.join(self.benchmark_dir, f"{self.program_name}_O*_path_*.txt")
        path_files = glob.glob(pattern)
        
        print(f"Search pattern: {pattern}")
        print(f"Found {len(path_files)} path files")
        
        for file_path in path_files:
            basename = os.path.basename(file_path)
                                                          
            match = re.match(rf'{self.program_name}_(O[0-3])_path_\d+\.txt', basename)
            if match:
                opt_level = match.group(1)
                opt_prefix = f"{self.program_name}_{opt_level}"
                if opt_prefix not in optimization_levels:
                    optimization_levels[opt_prefix] = []
                optimization_levels[opt_prefix].append(file_path)
        
        return optimization_levels
    
    def compare_program_optimization_pairs(self):
        """Compare all optimization-level pairs for the target program."""
        
        optimization_levels = self.find_program_optimization_levels()
        
        if len(optimization_levels) < 2:
            print(f"Program {self.program_name} has too few optimization levels for comparison "
                  f"(found {len(optimization_levels)})")
            print("Discovered optimization levels:", list(optimization_levels.keys()))
            return None
        
        print(f"Program {self.program_name} has {len(optimization_levels)} optimization levels:")
        for opt_level in sorted(optimization_levels.keys()):
            print(f"  {opt_level}: {len(optimization_levels[opt_level])} path files")
        
                   
        opt_levels = sorted(optimization_levels.keys())
        comparison_results = {}
        
        for i, opt1 in enumerate(opt_levels):
            for j, opt2 in enumerate(opt_levels):
                if i >= j:
                    continue
                
                print(f"\n{'='*60}")
                print(f"Comparing {opt1} vs {opt2}")
                print(f"{'='*60}")
                
                               
                prefix1 = os.path.join(self.benchmark_dir, f"{opt1}_path_")
                prefix2 = os.path.join(self.benchmark_dir, f"{opt2}_path_")
                
                try:
                    results = self.analyzer.analyze_path_clusters(prefix1, prefix2)
                    comparison_results[(opt1, opt2)] = results
                    
                             
                    report_file = os.path.join(
                        self.benchmark_dir, 
                        f"equivalence_report_{opt1}_vs_{opt2}.txt"
                    )
                    self.analyzer.generate_report(results, report_file)
                    print(f"Report written to: {report_file}")
                    
                except Exception as e:
                    print(f"Error while comparing {opt1} vs {opt2}: {e}")
                    comparison_results[(opt1, opt2)] = {
                        'error': str(e),
                        'status': 'failed'
                    }
        
                     
        self.generate_program_summary_report(comparison_results)
        
        return comparison_results
    
    def generate_program_summary_report(self, comparison_results):
        """Generate a summary report for a single program."""
        summary_file = os.path.join(self.benchmark_dir, f"{self.program_name}_equivalence_summary.txt")
        
        with open(summary_file, "w", encoding='utf-8') as f:
            f.write(f"Equivalence-analysis summary for program {self.program_name}\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"Analysis directory: {self.benchmark_dir}\n")
            f.write(f"Target program: {self.program_name}\n")
            f.write(f"Number of optimization-level pairs compared: {len(comparison_results)}\n\n")
            
            for (opt1, opt2), results in comparison_results.items():
                f.write(f"Comparison {opt1} vs {opt2}:\n")
                if 'error' in results:
                    f.write(f"  Status: FAILED\n")
                    f.write(f"  Error: {results['error']}\n")
                else:
                    f.write(f"  Status: OK\n")
                    if 'equivalent_pairs' in results:
                        f.write(f"  Equivalent path pairs: {len(results['equivalent_pairs'])}\n")
                    if 'non_equivalent_pairs' in results:
                        f.write(f"  Non-equivalent path pairs: {len(results['non_equivalent_pairs'])}\n")
                f.write("\n")
        
        print(f"Program-specific summary report written to: {summary_file}")

class IntegratedAnalysisFramework:
    """Integrated analysis framework for symbolic execution plus equivalence checking."""
    
    def __init__(self, benchmark_dir, timeout=120, force_rerun=False, target_program=None):
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.force_rerun = force_rerun
        self.target_program = target_program            
        self.timing_data = {
            'total_start_time': None,
            'total_end_time': None,
            'symbolic_execution': {},
            'equivalence_analysis': {},
            'phase_times': {}
        }
        
    def run_complete_analysis(self, binary_patterns=None):
        """Run the complete integrated analysis pipeline."""
        print("=" * 80)
        print("Starting integrated analysis: symbolic execution + equivalence checking")
        if self.target_program:
            print(f"Target program: {self.target_program}")
        print("=" * 80)
        
        self.timing_data['total_start_time'] = time.time()
        
                  
        print(f"\n📊 Phase 1: symbolic execution")
        print("-" * 50)
        se_start_time = time.time()
        
        if binary_patterns:
            se_results = self.run_targeted_symbolic_execution(binary_patterns)
        else:
            se_results = self.run_batch_symbolic_execution()
        
        se_end_time = time.time()
        se_duration = se_end_time - se_start_time
        
        self.timing_data['phase_times']['symbolic_execution'] = se_duration
        self.timing_data['symbolic_execution'] = se_results
        
        print(f"\n✅ Symbolic-execution phase finished in {se_duration:.3f} seconds")
        
        print(f"\n🔍 Phase 2: equivalence analysis")
        print("-" * 50)
        eq_start_time = time.time()
        
        eq_results = self.run_equivalence_analysis()
        
        eq_end_time = time.time()
        eq_duration = eq_end_time - eq_start_time
        
        self.timing_data['phase_times']['equivalence_analysis'] = eq_duration
        self.timing_data['equivalence_analysis'] = eq_results
        
        print(f"\n✅ Equivalence-analysis phase finished in {eq_duration:.3f} seconds")
        
        self.timing_data['total_end_time'] = time.time()
        total_duration = self.timing_data['total_end_time'] - self.timing_data['total_start_time']
        self.timing_data['phase_times']['total'] = total_duration
        
        print(f"\n🎉 Integrated analysis completed in {total_duration:.3f} seconds")
        
                
        self.generate_comprehensive_report()
        
        return {
            'symbolic_execution_results': se_results,
            'equivalence_analysis_results': eq_results,
            'timing_data': self.timing_data
        }
    
    def run_batch_symbolic_execution(self):
        """Run symbolic execution on all relevant binaries under the benchmark directory."""
        print("Searching for binaries...")
        
        analyzer = BenchmarkAnalyzer(self.benchmark_dir, self.timeout)
        results = analyzer.analyze_all_binaries()
        
                   
        se_timing = {}
        for binary_name, paths in results.items():
            se_timing[binary_name] = {
                'path_count': len(paths),
                'estimated_time': len(paths) * 0.1        
            }
        
        analyzer.generate_summary_report()
        
        return {
            'results': results,
            'timing': se_timing,
            'summary_file': os.path.join(self.benchmark_dir, "symbolic_execution_summary.txt")
        }
    
    def run_targeted_symbolic_execution(self, binary_patterns):
        """Run symbolic execution only on binaries matching given patterns."""
        results = {}
        se_timing = {}
        
        for pattern in binary_patterns:
            all_files = glob.glob(os.path.join(self.benchmark_dir, pattern))
            binary_files = [f for f in all_files if not f.endswith('.txt') and not f.endswith('.c')]
            
            for binary_path in binary_files:
                print(f"Checking binary file: {binary_path}")
                
                basename = os.path.basename(binary_path)
                
                                                   
                current_dir_paths = glob.glob(f"{basename}_path_*.txt")
                benchmark_dir_paths = glob.glob(os.path.join(self.benchmark_dir, f"{basename}_path_*.txt"))
                
                existing_paths = current_dir_paths + benchmark_dir_paths
                
                if existing_paths and not self.force_rerun:
                    print(f"Found existing path files: {len(existing_paths)}")
                    print("Skipping symbolic execution and reusing existing paths")
                    
                            
                    mock_paths = []
                    for i, path_file in enumerate(existing_paths):
                        mock_paths.append({
                            'index': i + 1,
                            'signature': {'output': f'path_{i+1}'},
                            'smt_constraints': f'from file: {path_file}',
                            'state': None
                        })
                    
                    results[basename] = mock_paths
                    se_timing[basename] = {
                        'path_count': len(existing_paths),
                        'actual_time': 0.0,            
                        'skipped': True
                    }
                    
                    print(f"Using existing paths for {basename}: {len(existing_paths)} paths")
                else:
                    if existing_paths and self.force_rerun:
                        print(f"Force-rerun mode: deleting {len(existing_paths)} existing path files")
                        for path_file in existing_paths:
                            try:
                                os.remove(path_file)
                                print(f"  Deleted: {path_file}")
                            except OSError as e:
                                print(f"  Failed to delete {path_file}: {e}")
                        print("Existing path files removed")
                    
                    print(f"Analyzing binary: {binary_path}")
                    
                    binary_start = time.time()
                    
                    analyzer = ImprovedPathAnalyzer(binary_path, basename, self.timeout)
                    paths = analyzer.run_symbolic_execution()
                    
                    binary_end = time.time()
                    binary_duration = binary_end - binary_start
                    
                    results[basename] = paths
                    se_timing[basename] = {
                        'path_count': len(paths),
                        'actual_time': binary_duration,
                        'skipped': False
                    }
                    
                    print(f"Finished {basename}: {len(paths)} paths in {binary_duration:.3f} seconds")
        
        return {
            'results': results,
            'timing': se_timing
        }
    
    def run_equivalence_analysis(self):
        """Run the equivalence-analysis phase."""
        print("Starting equivalence analysis...")
        
                     
        current_dir_files = glob.glob("*_path_*.txt")
        benchmark_dir_files = glob.glob(os.path.join(self.benchmark_dir, "*_path_*.txt"))
        
                        
        if current_dir_files and not benchmark_dir_files:
            print(f"Found path files in current directory; switching analysis directory to '.'")
            analysis_dir = "."
        else:
            analysis_dir = self.benchmark_dir
        
                              
        if self.target_program:
            print(f"Using program-specific analyzer: {self.target_program}")
            program_analyzer = ProgramSpecificEquivalenceAnalyzer(analysis_dir, self.target_program)
            comparison_results = program_analyzer.compare_program_optimization_pairs()
        else:
            print("Using generic analyzer for all programs")
            benchmark_analyzer = BenchmarkEquivalenceAnalyzer(analysis_dir)
            comparison_results = benchmark_analyzer.compare_all_optimization_pairs()
        
                      
        if comparison_results is None:
            error_msg = "Not enough optimization levels or path files found"
            if self.target_program:
                error_msg += f" (target program: {self.target_program})"
            print(f"❌ Equivalence analysis failed: {error_msg}")
            return {
                'comparison_results': {},
                'timing': {},
                'summary_file': None,
                'error': error_msg
            }
        
                      
        eq_timing = {}
        for (opt1, opt2), results in comparison_results.items():
            comparison_name = f"{opt1}_vs_{opt2}"
            if 'timing_info' in results:
                eq_timing[comparison_name] = results['timing_info']
        
                 
        if self.target_program:
            summary_file = os.path.join(analysis_dir, f"{self.target_program}_equivalence_summary.txt")
        else:
            summary_file = os.path.join(analysis_dir, "optimization_equivalence_summary.txt")
        
        return {
            'comparison_results': comparison_results,
            'timing': eq_timing,
            'summary_file': summary_file
        }
    
    def generate_comprehensive_report(self):
        """Generate an integrated analysis report combining both phases."""
        report_file = os.path.join(self.benchmark_dir, "integrated_analysis_report.txt")
        
        with open(report_file, "w", encoding='utf-8') as f:
            f.write("Integrated analysis report\n")
            f.write("=" * 60 + "\n\n")
            
                    
            f.write("Overall timing statistics:\n")
            f.write("-" * 40 + "\n")
            
            total_time = self.timing_data['phase_times']['total']
            se_time = self.timing_data['phase_times']['symbolic_execution']
            eq_time = self.timing_data['phase_times']['equivalence_analysis']
            
            f.write(f"  Total analysis time: {total_time:.3f} seconds\n\n")
            
            f.write("Per-phase timing breakdown:\n")
            f.write("-" * 40 + "\n")
            f.write(f"  Symbolic-execution phase: {se_time:.3f} seconds ({se_time/total_time*100:.1f}%)\n")
            f.write(f"  Equivalence-analysis phase: {eq_time:.3f} seconds ({eq_time/total_time*100:.1f}%)\n\n")
            
                      
            if 'timing' in self.timing_data['symbolic_execution']:
                f.write("Symbolic-execution detailed statistics:\n")
                f.write("-" * 40 + "\n")
                
                se_timing = self.timing_data['symbolic_execution']['timing']
                if se_timing:
                    total_paths = sum(info['path_count'] for info in se_timing.values())
                    skipped_count = sum(1 for info in se_timing.values() if info.get('skipped', False))
                    actual_analyzed = len(se_timing) - skipped_count
                    
                    f.write(f"  Binaries considered: {len(se_timing)}\n")
                    f.write(f"  Binaries with symbolic execution skipped: {skipped_count}\n")
                    f.write(f"  Binaries actually symbolically executed: {actual_analyzed}\n")
                    f.write(f"  Total paths generated: {total_paths}\n")
                    
                    if len(se_timing) > 0:
                        f.write(f"  Average paths per binary: {total_paths/len(se_timing):.1f}\n")
                    
                    if actual_analyzed > 0:
                        actual_times = [
                            info['actual_time']
                            for info in se_timing.values()
                            if 'actual_time' in info and not info.get('skipped', False)
                        ]
                        if actual_times:
                            avg_time = sum(actual_times) / len(actual_times)
                            f.write(f"  Average analysis time per binary: {avg_time:.3f} seconds\n")
                    
                    if total_paths > 0 and se_time > 0:
                        f.write(f"  Average path-generation time: {se_time/total_paths:.4f} seconds\n")
                    
                              
                    empty_path_files = 0
                    if self.target_program:
                        pattern = f"{self.target_program}_O*_path_*.txt"
                        path_files = glob.glob(pattern) + glob.glob(os.path.join(self.benchmark_dir, pattern))
                        
                        for path_file in path_files:
                            try:
                                with open(path_file, 'r') as pf:
                                    content = pf.read()
                                    if "'count': 0" in content or "constraint info: {'count': 0}" in content:
                                        empty_path_files += 1
                            except Exception:
                                pass
                        
                        if empty_path_files > 0:
                            f.write(f"\n  ⚠️  Path-quality diagnostics:\n")
                            f.write(f"     Detected {empty_path_files} path files with empty constraints\n")
                            f.write(f"     Possible cause: program uses fixed inputs or lacks symbolic variables\n")
                            f.write(f"     Suggestion: check symbolic-execution configuration and symbolic inputs\n")
                    
                    f.write("\n")
                else:
                    f.write("  No symbolic execution performed (existing paths reused)\n\n")
                
                         
                f.write("Per-binary symbolic-execution details:\n")
                for binary_name, timing_info in se_timing.items():
                    f.write(f"  {binary_name}:\n")
                    f.write(f"    Path count: {timing_info['path_count']}\n")
                    
                    if timing_info.get('skipped', False):
                        f.write(f"    Status: reused existing paths\n")
                    else:
                        if 'actual_time' in timing_info:
                            f.write(f"    Analysis time: {timing_info['actual_time']:.3f} seconds\n")
                            if timing_info['path_count'] > 0:
                                f.write(f"    Time per path: {timing_info['actual_time']/timing_info['path_count']:.4f} seconds\n")
                        f.write(f"    Status: freshly executed\n")
                    f.write("\n")
            
                       
            if 'timing' in self.timing_data['equivalence_analysis']:
                eq_timing = self.timing_data['equivalence_analysis']['timing']
                
                if eq_timing:
                    f.write("Equivalence-analysis detailed statistics:\n")
                    f.write("-" * 40 + "\n")
                    
                    total_comparisons = len(eq_timing)
                    total_z3_time = sum(timing.get('z3_total_time', 0) for timing in eq_timing.values())
                    total_z3_calls = sum(timing.get('z3_call_count', 0) for timing in eq_timing.values())
                    
                    f.write(f"  Optimization-pair comparisons: {total_comparisons}\n")
                    f.write(f"  Total Z3 solving time: {total_z3_time:.3f} seconds ({total_z3_time/eq_time*100:.1f}%)\n")
                    f.write(f"  Total Z3 calls: {total_z3_calls}\n")
                    if total_z3_calls > 0:
                        f.write(f"  Average Z3 solve time: {total_z3_time/total_z3_calls:.4f} seconds\n")
                    f.write(f"  Non-Z3 processing time: {eq_time - total_z3_time:.3f} seconds "
                            f"({(eq_time - total_z3_time)/eq_time*100:.1f}%)\n\n")
                    
                           
                    total_equiv_pairs = 0
                    total_non_equiv_pairs = 0
                    
                                   
                    if 'comparison_results' in self.timing_data['equivalence_analysis']:
                        comp_results = self.timing_data['equivalence_analysis']['comparison_results']
                        for (opt1, opt2), results in comp_results.items():
                            if 'equivalent_pairs' in results:
                                total_equiv_pairs += len(results['equivalent_pairs'])
                            if 'non_equivalent_pairs' in results:
                                total_non_equiv_pairs += len(results['non_equivalent_pairs'])
                    
                    if total_equiv_pairs + total_non_equiv_pairs > 0:
                        equiv_rate = total_equiv_pairs / (total_equiv_pairs + total_non_equiv_pairs) * 100
                        f.write(f"  Total equivalent path pairs: {total_equiv_pairs}\n")
                        f.write(f"  Total non-equivalent path pairs: {total_non_equiv_pairs}\n")
                        f.write(f"  Equivalence success rate: {equiv_rate:.1f}%\n\n")
                    
                              
                    f.write("Per-optimization-pair timing details:\n")
                    for comparison_name, timing_info in eq_timing.items():
                        f.write(f"  {comparison_name}:\n")
                        f.write(f"    Total time: {timing_info.get('total_time', 0):.3f} seconds\n")
                        f.write(f"    File loading: {timing_info.get('load_time', 0):.3f} seconds\n")
                        f.write(f"    Path comparison: {timing_info.get('comparison_time', 0):.3f} seconds\n")
                        f.write(f"    Z3 solving: {timing_info.get('z3_total_time', 0):.3f} seconds\n")
                        f.write(f"    Z3 calls: {timing_info.get('z3_call_count', 0)}\n")
                        f.write("\n")
                else:
                    f.write("Equivalence-analysis status:\n")
                    f.write("-" * 40 + "\n")
                    error_msg = self.timing_data['equivalence_analysis'].get('error', 'Unknown error')
                    f.write(f"  ❌ Equivalence analysis failed: {error_msg}\n")
                    
                    if self.target_program:
                        f.write(f"  🔍 Diagnostic suggestions for program {self.target_program}:\n")
                        f.write(f"    1. Check that valid path files exist\n")
                        f.write(f"    2. Verify that path files contain meaningful constraints\n")
                        f.write(f"    3. Ensure at least two distinct optimization levels are present\n")
                    else:
                        f.write(f"  🔍 Diagnostic suggestions:\n")
                        f.write(f"    1. Check that path files are generated correctly\n")
                        f.write(f"    2. Verify file naming conventions are correct\n")
                        f.write(f"    3. Ensure enough optimization levels are present in the directory\n")
                    f.write("\n")
            
                     
            f.write("Performance analysis and optimization suggestions:\n")
            f.write("-" * 40 + "\n")
            
            if se_time > eq_time:
                f.write("  Symbolic execution is the primary time bottleneck.\n")
                f.write("  Suggested optimization directions:\n")
                f.write("    - Tune constraint-solving strategies\n")
                f.write("    - Adjust path-exploration depth\n")
                f.write("    - Parallelize symbolic-execution runs\n")
            else:
                f.write("  Equivalence analysis is the primary time bottleneck.\n")
                f.write("  Suggested optimization directions:\n")
                f.write("    - Tune Z3 solver configuration\n")
                f.write("    - Improve path-matching algorithms\n")
                f.write("    - Parallelize equivalence checking\n")
            
            if 'timing' in self.timing_data['equivalence_analysis']:
                eq_timing = self.timing_data['equivalence_analysis']['timing']
                if eq_timing:
                    total_z3_time = sum(timing.get('z3_total_time', 0) for timing in eq_timing.values())
                    total_comparison_time = sum(timing.get('total_time', 0) for timing in eq_timing.values())
                    
                        if total_comparison_time > 0:
                            z3_ratio = total_z3_time / total_comparison_time
                            f.write(f"\n  Z3 time as fraction of equivalence-analysis time: {z3_ratio*100:.1f}%\n")
                            if z3_ratio > 0.8:
                                f.write("    Z3 solving is the primary equivalence-analysis bottleneck\n")
                            elif z3_ratio < 0.5:
                                f.write("    Path matching and pre-processing dominate cost\n")
                else:
                    f.write(f"\n  ⚠️  Equivalence analysis did not complete successfully\n")
                    if self.target_program:
                        f.write(f"     This may be because program {self.target_program} has empty path constraints\n")
                        f.write(f"     Suggestion: check symbolic-execution configuration or program inputs\n")
        
        print(f"\n📄 Integrated analysis report written to: {report_file}")
        
        print(f"\n📊 Key performance metrics:")
        print(f"   Total analysis time: {self.timing_data['phase_times']['total']:.3f} seconds")
        print(f"   Symbolic execution: {self.timing_data['phase_times']['symbolic_execution']:.3f} seconds "
              f"({self.timing_data['phase_times']['symbolic_execution']/self.timing_data['phase_times']['total']*100:.1f}%)")
        print(f"   Equivalence analysis: {self.timing_data['phase_times']['equivalence_analysis']:.3f} seconds "
              f"({self.timing_data['phase_times']['equivalence_analysis']/self.timing_data['phase_times']['total']*100:.1f}%)")
        
        if self.target_program:
            print(f"   Target program: {self.target_program}")
            
            pattern = f"{self.target_program}_O*_path_*.txt"
            path_files = glob.glob(pattern) + glob.glob(os.path.join(self.benchmark_dir, pattern))
            
            empty_constraint_files = 0
            for path_file in path_files:
                try:
                    with open(path_file, 'r') as pf:
                        content = pf.read()
                        if "'count': 0" in content:
                            empty_constraint_files += 1
                except Exception:
                    pass
            
            if empty_constraint_files > 0:
                print(f"   ⚠️  Found {empty_constraint_files} path files with empty constraints")
                print(f"   💡 Suggestion: check whether the program uses symbolic inputs")

class QuickAnalysisMode:
    """Quick-analysis mode – focused on a single program."""
    
    def __init__(self, program_name, benchmark_dir, timeout=120, force_rerun=False):
        self.program_name = program_name
        self.benchmark_dir = benchmark_dir
        self.timeout = timeout
        self.force_rerun = force_rerun
        
    def run_quick_analysis(self):
        """Run quick analysis over all optimization levels of the target program."""
        print(f"🚀 Quick analysis mode: {self.program_name}")
        print("=" * 60)
        
                      
        binary_patterns = [f"{self.program_name}_O*"]
        
        framework = IntegratedAnalysisFramework(self.benchmark_dir, self.timeout, self.force_rerun, self.program_name)
        results = framework.run_complete_analysis(binary_patterns)
        
        return results

def main():
    """CLI entry point for the integrated analysis tool."""
    parser = argparse.ArgumentParser(description='Integrated symbolic-execution and equivalence-analysis tool')
    parser.add_argument('--benchmark', default='.', help='Path to benchmark directory')
    parser.add_argument('--timeout', type=int, default=120, help='Symbolic-execution timeout (seconds)')
    parser.add_argument('--program', help='Target program name for quick analysis (e.g., s000)')
    parser.add_argument('--quick', action='store_true', help='Enable quick-analysis mode')
    parser.add_argument('--force-rerun', '-f', action='store_true', help='Force re-running symbolic execution and delete existing path files')
    
    args = parser.parse_args()
    
    if args.quick and args.program:
        quick_analyzer = QuickAnalysisMode(args.program, args.benchmark, args.timeout, args.force_rerun)
        results = quick_analyzer.run_quick_analysis()
    else:
                
        framework = IntegratedAnalysisFramework(args.benchmark, args.timeout, args.force_rerun)
        results = framework.run_complete_analysis()
    
    print("\n🎯 Analysis complete! See the following files for details:")
    print(f"   📄 Integrated report: {os.path.join(args.benchmark, 'integrated_analysis_report.txt')}")
    print(f"   📊 Symbolic-execution summary: {os.path.join(args.benchmark, 'symbolic_execution_summary.txt')}")
    print(f"   🔍 Equivalence-analysis summary: {os.path.join(args.benchmark, 'optimization_equivalence_summary.txt')}")

if __name__ == "__main__":
    main() 