                      
"""
Batch equivalence-analysis script.

Uses ``semantic_equivalence_analyzer.py`` to compare path constraints produced
by symbolic execution across many programs and optimization levels.

Features:
1. Automatically discover all programs and optimization levels
2. For each program, compare all optimization-level pairs
3. Record detailed timing information
4. Generate a comprehensive analysis report
"""

import os
import sys
import glob
import time
import datetime
import subprocess
import json
import re
from pathlib import Path
import argparse
from itertools import combinations
from collections import defaultdict

class BatchEquivalenceAnalyzer:
    """Manager for batched program equivalence analysis."""
    
    def __init__(self, timeout=120, equivalence_script="semantic_equivalence_analyzer.py"):
        self.timeout = timeout
        self.equivalence_script = equivalence_script
        self.results = {}
        self.total_start_time = None
        self.total_end_time = None
        self.failed_analyses = []
        self.successful_analyses = []
        self.all_comparisons = []
        self.target_programs = None              
        
    def discover_programs_and_optimizations(self):
        """Discover all programs and their available optimization levels."""
                  
        path_files = glob.glob("*_path_*.txt")
        
        if not path_files:
            print("❌ No path files found")
            return {}
        
                     
        programs = defaultdict(set)
        
        for file_path in path_files:
            filename = os.path.basename(file_path)
                                                  
            match = re.match(r'^(.+)_(O\d+)_path_\d+\.txt$', filename)
            if match:
                program, optimization = match.groups()
                programs[program].add(optimization)
        
                       
        result = {}
        for program, optimizations in programs.items():
            result[program] = sorted(list(optimizations))
        
        return result
    
    def get_comparison_pairs(self, optimizations):
        """Get all optimization-level pairs that need to be compared."""
        return list(combinations(optimizations, 2))
    
    def run_equivalence_analysis(self, program, opt1, opt2):
        """Run a single equivalence analysis for one program/opt-level pair."""
        prefix1 = f"{program}_{opt1}_path_"
        prefix2 = f"{program}_{opt2}_path_"
        
        print(f"  Comparing {opt1} vs {opt2}")
        print(f"    Prefix 1: {prefix1}")
        print(f"    Prefix 2: {prefix2}")
        
                    
        files1 = glob.glob(f"{prefix1}*.txt")
        files2 = glob.glob(f"{prefix2}*.txt")
        
        if not files1:
            print(f"    ❌ No path files found for {opt1}")
            return None
        if not files2:
            print(f"    ❌ No path files found for {opt2}")
            return None
        
        print(f"    Paths discovered: {len(files1)} vs {len(files2)}")
        
        start_time = time.time()
        
        try:
                  
            output_file = f"{program}_{opt1}_vs_{opt2}_equivalence_report.txt"
            cmd = [
                "python", self.equivalence_script,
                prefix1.rstrip('_'),
                prefix2.rstrip('_'),
                "--output", output_file,
                "--timeout", str(self.timeout * 1000)
            ]
            
            print(f"    Command: {' '.join(cmd)}")
            
                     
            result = subprocess.run(
                cmd,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
                timeout=self.timeout + 60             
            )
            
            end_time = time.time()
            execution_time = end_time - start_time
            
                  
            stdout_lines = result.stdout.split('\n')
            stderr_lines = result.stderr.split('\n')
            
                    
            program_equivalent = False
            equivalent_pairs = 0
            partial_pairs = 0
            total_paths_compared = 0
            
            for line in stdout_lines:
                if "Program equivalence:" in line:
                    program_equivalent = "✅ equivalent" in line
                elif "Fully equivalent path pairs:" in line:
                    try:
                        equivalent_pairs = int(line.split(":")[-1].strip())
                    except Exception:
                        pass
                elif "Partially equivalent path pairs:" in line:
                    try:
                        partial_pairs = int(line.split(":")[-1].strip())
                    except Exception:
                        pass
                elif "Total analyzed path pairs:" in line:
                    try:
                        total_paths_compared = int(line.split(":")[-1].strip())
                    except Exception:
                        pass
            
            analysis_result = {
                'program': program,
                'opt1': opt1,
                'opt2': opt2,
                'success': result.returncode == 0,
                'execution_time': execution_time,
                'program_equivalent': program_equivalent,
                'equivalent_pairs': equivalent_pairs,
                'partial_pairs': partial_pairs,
                'total_paths_compared': total_paths_compared,
                'paths1_count': len(files1),
                'paths2_count': len(files2),
                'return_code': result.returncode,
                'output_file': output_file,
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            if result.returncode == 0:
                equiv_status = "✅ equivalent" if program_equivalent else "❌ NOT equivalent"
                print(f"    {equiv_status}: {equivalent_pairs} fully equivalent pairs, "
                      f"{partial_pairs} partially equivalent pairs (time: {execution_time:.1f}s)")
                self.successful_analyses.append(analysis_result)
            else:
                print(f"    ❌ Failed: return code {result.returncode} (time: {execution_time:.1f}s)")
                analysis_result['error_output'] = result.stderr[:500]
                self.failed_analyses.append(analysis_result)
            
            self.all_comparisons.append(analysis_result)
            return analysis_result
            
        except subprocess.TimeoutExpired:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"    ⏰ Timeout: {execution_time:.1f}s")
            
            timeout_result = {
                'program': program,
                'opt1': opt1,
                'opt2': opt2,
                'success': False,
                'execution_time': execution_time,
                'program_equivalent': False,
                'equivalent_pairs': 0,
                'partial_pairs': 0,
                'total_paths_compared': 0,
                'paths1_count': len(files1),
                'paths2_count': len(files2),
                'return_code': -1,
                'error': 'timeout',
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.failed_analyses.append(timeout_result)
            self.all_comparisons.append(timeout_result)
            return timeout_result
            
        except Exception as e:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"    💥 Exception: {str(e)} (time: {execution_time:.1f}s)")
            
            exception_result = {
                'program': program,
                'opt1': opt1,
                'opt2': opt2,
                'success': False,
                'execution_time': execution_time,
                'program_equivalent': False,
                'equivalent_pairs': 0,
                'partial_pairs': 0,
                'total_paths_compared': 0,
                'paths1_count': len(files1) if 'files1' in locals() else 0,
                'paths2_count': len(files2) if 'files2' in locals() else 0,
                'return_code': -2,
                'error': str(e),
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.failed_analyses.append(exception_result)
            self.all_comparisons.append(exception_result)
            return exception_result
    
    def analyze_program(self, program, optimizations):
        """Analyze all optimization-level combinations for a single program."""
        print(f"\n📁 Analyzing program: {program}")
        print("=" * 60)
        
        if len(optimizations) < 2:
            print(f"  ⚠️  Only {len(optimizations)} optimization levels found; skipping")
            return []
        
        comparison_pairs = self.get_comparison_pairs(optimizations)
        print(f"  Optimizations: {', '.join(optimizations)}")
        print(f"  Comparison pairs needed: {len(comparison_pairs)}")
        
        program_results = []
        for i, (opt1, opt2) in enumerate(comparison_pairs, 1):
            print(f"\n  🔄 Comparing {i}/{len(comparison_pairs)}: {opt1} vs {opt2}")
            result = self.run_equivalence_analysis(program, opt1, opt2)
            if result:
                program_results.append(result)
        
        self.results[program] = program_results
        return program_results
    
    def run_batch_analysis(self):
        """Run the full batch equivalence analysis."""
        print("🚀 Starting batch equivalence analysis")
        print("=" * 60)
        
        self.total_start_time = time.time()
        start_datetime = datetime.datetime.now()
        print(f"Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
                     
        programs_optimizations = self.discover_programs_and_optimizations()
        
        if not programs_optimizations:
            print("❌ No program path files found")
            return
        
                               
        if self.target_programs:
            programs_to_analyze = {p: o for p, o in programs_optimizations.items() if p in self.target_programs}
            if not programs_to_analyze:
                print(f"❌ No programs/optimization levels matched: {', '.join(self.target_programs)}")
                return
            print(f"📋 Found {len(programs_to_analyze)} programs (filtered by --programs):")
        else:
            programs_to_analyze = programs_optimizations
            print(f"📋 Found {len(programs_optimizations)} programs:")
        
        total_comparisons = 0
        for program, optimizations in programs_to_analyze.items():
            pairs_count = len(list(combinations(optimizations, 2))) if len(optimizations) >= 2 else 0
            total_comparisons += pairs_count
            print(f"  {program}: {optimizations} ({pairs_count} comparisons)")
        
        print(f"Total of {total_comparisons} equivalence comparisons to perform")
        
                
        for i, (program, optimizations) in enumerate(programs_to_analyze.items(), 1):
            print(f"\n🔄 Progress: {i}/{len(programs_to_analyze)}")
            self.analyze_program(program, optimizations)
        
        self.total_end_time = time.time()
        total_time = self.total_end_time - self.total_start_time
        end_datetime = datetime.datetime.now()
        
        print(f"\n🎉 Batch equivalence analysis complete!")
        print(f"Total time: {total_time:.1f} s ({total_time/60:.1f} min)")
        print(f"End time: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
              
        self.generate_comprehensive_report()
    
    def preview_analysis(self):
        """Preview which comparisons will be run, without executing them."""
        print("🔍 Dry-run preview – scanning planned comparisons")
        print("=" * 60)
        
                     
        programs_optimizations = self.discover_programs_and_optimizations()
        
        if not programs_optimizations:
            print("❌ No program path files found")
            return
        
                               
        if self.target_programs:
            programs_to_analyze = {p: o for p, o in programs_optimizations.items() if p in self.target_programs}
            if not programs_to_analyze:
                print(f"❌ No programs/optimization levels matched: {', '.join(self.target_programs)}")
                return
            print(f"📋 Found {len(programs_to_analyze)} programs (filtered by --programs):")
        else:
            programs_to_analyze = programs_optimizations
            print(f"📋 Found {len(programs_optimizations)} programs:")
        
        total_comparisons = 0
        total_estimated_time = 0
        
        for program, optimizations in programs_to_analyze.items():
            print(f"\n🔹 {program}: {optimizations}")
            
            if len(optimizations) < 2:
                print(f"    ⚠️  Only {len(optimizations)} optimization levels; skipping")
                continue
            
            comparison_pairs = self.get_comparison_pairs(optimizations)
            print(f"    Comparisons needed: {len(comparison_pairs)} pairs")
            
                for opt1, opt2 in comparison_pairs:
                    files1 = glob.glob(f"{program}_{opt1}_path_*.txt")
                    files2 = glob.glob(f"{program}_{opt2}_path_*.txt")
                    
                    estimated_time = len(files1) * len(files2) * 0.1
                    total_estimated_time += estimated_time
                    
                    print(f"      - {opt1} vs {opt2}: {len(files1)} vs {len(files2)} paths "
                          f"(estimated {estimated_time:.1f}s)")
                
            total_comparisons += len(comparison_pairs)
        
        print(f"\n📊 Overall preview:")
        print(f"  Total programs: {len(programs_optimizations)}")
        print(f"  Total comparisons: {total_comparisons}")
        print(f"  Estimated total time: {total_estimated_time:.1f} s ({total_estimated_time/60:.1f} min)")
        print(f"  Timeout setting: {self.timeout} s/comparison")
        print(f"  Equivalence script: {self.equivalence_script}")
        
        print(f"\n💡 To start the actual analysis, run:")
        print(f"   python batch_equivalence_analyzer.py --timeout {self.timeout}")
        
        if total_estimated_time > 1800:
            print(f"\n⚠️  Long estimated time; consider running in the background:")
            print(f"   nohup python batch_equivalence_analyzer.py --timeout {self.timeout} > equivalence_analysis.log 2>&1 &")
    
    def generate_comprehensive_report(self):
        """Generate a comprehensive textual report for all batch analyses."""
        report_file = "batch_equivalence_analysis_report.txt"
        
        total_time = self.total_end_time - self.total_start_time if self.total_end_time else 0
        successful_count = len(self.successful_analyses)
        failed_count = len(self.failed_analyses)
        total_count = len(self.all_comparisons)
        
              
        total_equivalent_programs = sum(1 for result in self.successful_analyses if result['program_equivalent'])
        total_equivalent_pairs = sum(result['equivalent_pairs'] for result in self.successful_analyses)
        total_partial_pairs = sum(result['partial_pairs'] for result in self.successful_analyses)
        total_paths_compared = sum(result['total_paths_compared'] for result in self.successful_analyses)
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("Batch equivalence-analysis report\n")
            f.write("=" * 60 + "\n\n")
            
                  
            f.write("📊 Overall statistics:\n")
            f.write("-" * 30 + "\n")
            f.write(f"Start time: {datetime.datetime.fromtimestamp(self.total_start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"End time:   {datetime.datetime.fromtimestamp(self.total_end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total time: {total_time:.1f} s ({total_time/60:.1f} min)\n")
            f.write(f"Programs analyzed: {len(self.results)}\n")
            f.write(f"Total comparisons: {total_count}\n")
            f.write(f"Successful comparisons: {successful_count}\n")
            f.write(f"Failed comparisons: {failed_count}\n")
            f.write(f"Success rate: {successful_count/total_count*100:.1f}%\n")
            f.write(f"Programs with full equivalence: {total_equivalent_programs}\n")
            f.write(f"Total fully equivalent path pairs: {total_equivalent_pairs}\n")
            f.write(f"Total partially equivalent path pairs: {total_partial_pairs}\n")
            f.write(f"Total path pairs compared: {total_paths_compared}\n")
            if successful_count > 0:
                f.write(f"Average comparison time: "
                        f"{sum(r['execution_time'] for r in self.successful_analyses)/successful_count:.1f} s\n")
            f.write("\n")
            
                   
            f.write("📋 Per-program comparison details:\n")
            f.write("-" * 50 + "\n")
            
            for program, results in self.results.items():
                f.write(f"\n🔹 {program}:\n")
                f.write(f"  Comparisons: {len(results)}\n")
                
                successful_in_program = [r for r in results if r['success']]
                failed_in_program = [r for r in results if not r['success']]
                equivalent_in_program = [r for r in successful_in_program if r['program_equivalent']]
                
                f.write(f"  Successful: {len(successful_in_program)}\n")
                f.write(f"  Failed: {len(failed_in_program)}\n")
                f.write(f"  Equivalent optimization pairs: {len(equivalent_in_program)}\n")
                
                if successful_in_program:
                    program_time = sum(r['execution_time'] for r in successful_in_program)
                    f.write(f"  Total time: {program_time:.1f} s\n")
                    f.write(f"  Average time: {program_time/len(successful_in_program):.1f} s/comparison\n")
                
                      
                for result in results:
                    status = "✅" if result['success'] else "❌"
                    equiv_status = ""
                    if result['success']:
                        equiv_status = " (✅ equivalent)" if result['program_equivalent'] else " (❌ NOT equivalent)"
                    
                    f.write(f"    {status} {result['opt1']} vs {result['opt2']}{equiv_status}: ")
                    if result['success']:
                        f.write(f"{result['equivalent_pairs']} fully equivalent pairs, "
                                f"{result['partial_pairs']} partially equivalent pairs, "
                                f"{result['execution_time']:.1f}s\n")
                    else:
                        error_type = result.get('error', f"return code {result['return_code']}")
                        f.write(f"Failed ({error_type}), {result['execution_time']:.1f}s\n")
            
                    
            if self.failed_analyses:
                f.write(f"\n❌ Failed-analysis summary:\n")
                f.write("-" * 30 + "\n")
                
                error_types = {}
                for failure in self.failed_analyses:
                    error_type = failure.get('error', f"return code {failure['return_code']}")
                    if error_type not in error_types:
                        error_types[error_type] = []
                    error_types[error_type].append(failure)
                
                for error_type, failures in error_types.items():
                    f.write(f"  {error_type}: {len(failures)} comparisons\n")
                    for failure in failures[:3]:
                        f.write(f"    - {failure['program']} {failure['opt1']} vs {failure['opt2']}\n")
                    if len(failures) > 3:
                        f.write(f"    - ... and {len(failures)-3} more\n")
            
                   
            if successful_count >= 3:
                f.write(f"\n🏆 Equivalence ranking:\n")
                f.write("-" * 30 + "\n")
                
                program_equiv_counts = {}
                for result in self.successful_analyses:
                    program = result['program']
                    if program not in program_equiv_counts:
                        program_equiv_counts[program] = {'equivalent': 0, 'total': 0}
                    program_equiv_counts[program]['total'] += 1
                    if result['program_equivalent']:
                        program_equiv_counts[program]['equivalent'] += 1
                
                       
                for program, counts in program_equiv_counts.items():
                    counts['rate'] = counts['equivalent'] / counts['total'] * 100
                
                top_programs = sorted(
                    program_equiv_counts.items(),
                    key=lambda x: (x[1]['equivalent'], x[1]['rate']),
                    reverse=True
                )[:5]
                
                f.write("Top-5 programs by equivalence rate:\n")
                for i, (program, counts) in enumerate(top_programs, 1):
                    f.write(f"  {i}. {program}: {counts['equivalent']}/{counts['total']} "
                            f"({counts['rate']:.1f}%)\n")
        
        print(f"📄 Comprehensive report written to: {report_file}")
        
                     
        json_file = "batch_equivalence_analysis_data.json"
        detailed_data = {
            'summary': {
                'start_time': self.total_start_time,
                'end_time': self.total_end_time,
                'total_time': total_time,
                'successful_count': successful_count,
                'failed_count': failed_count,
                'total_equivalent_programs': total_equivalent_programs,
                'total_equivalent_pairs': total_equivalent_pairs,
                'total_partial_pairs': total_partial_pairs
            },
            'results': self.results,
            'successful_analyses': self.successful_analyses,
            'failed_analyses': self.failed_analyses,
            'all_comparisons': self.all_comparisons
        }
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(detailed_data, f, indent=2, ensure_ascii=False)
        
        print(f"📊 Detailed batch data written to: {json_file}")

def main():
    """CLI entry point for the batch equivalence analyzer."""
    parser = argparse.ArgumentParser(description='Batch program equivalence-analysis tool')
    parser.add_argument('--timeout', type=int, default=120, help='Timeout per equivalence analysis (seconds)')
    parser.add_argument('--script', default='semantic_equivalence_analyzer.py', help='Path to equivalence-analysis script')
    parser.add_argument('--dry-run', action='store_true', help='Preview mode: only show planned comparisons, do not run them')
    parser.add_argument('--programs', nargs='*', help='Limit analysis to specific programs (defaults to all discovered programs)')
    
    args = parser.parse_args()
    
              
    if not args.dry_run and not os.path.exists(args.script):
        print(f"❌ Equivalence-analysis script not found: {args.script}")
        sys.exit(1)
    
             
    analyzer = BatchEquivalenceAnalyzer(
        timeout=args.timeout,
        equivalence_script=args.script
    )
    
    if args.programs:
        analyzer.target_programs = set(args.programs)
        print(f"🎯 Target programs: {', '.join(args.programs)}")
    else:
        analyzer.target_programs = None
    
               
    if args.dry_run:
        analyzer.preview_analysis()
    else:
        analyzer.run_batch_analysis()

if __name__ == "__main__":
    main() 