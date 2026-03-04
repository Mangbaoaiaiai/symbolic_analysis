                      
"""
Benchmark timing analysis script.

Aggregates and summarizes each benchmark's verification time, including:
1. Symbolic execution time
2. Equivalence analysis time
3. Overall statistics
"""

import json
import glob
import re
import os
from collections import defaultdict
from datetime import datetime

class BenchmarkTimingAnalyzer:
    def __init__(self):
        self.equivalence_data = None
        self.symbolic_execution_data = {}
        self.combined_stats = defaultdict(dict)
    
    def load_equivalence_data(self):
        """Load equivalence analysis data."""
        try:
            with open('batch_equivalence_analysis_data.json', 'r', encoding='utf-8') as f:
                self.equivalence_data = json.load(f)
            print("✅ Loaded equivalence analysis data")
            return True
        except FileNotFoundError:
            print("❌ Equivalence analysis data file not found")
            return False
    
    def load_symbolic_execution_data(self):
        """Load symbolic execution data."""
        try:
                            
            if os.path.exists('batch_symbolic_execution_data.json'):
                with open('batch_symbolic_execution_data.json', 'r', encoding='utf-8') as f:
                    se_json = json.load(f)
                self.parse_symbolic_execution_json(se_json)
                print("✅ Loaded symbolic execution JSON data")
                return True
            
                                   
            se_files = glob.glob("*symbolic_execution_report.txt")
            if not se_files:
                print("⚠️  No symbolic-execution data files found")
                return False
            
            for file in se_files:
                self.parse_symbolic_execution_file(file)
            
            print(f"✅ Loaded {len(se_files)} symbolic-execution reports")
            return True
        except Exception as e:
            print(f"❌ Failed to load symbolic-execution data: {e}")
            return False
    
    def parse_symbolic_execution_json(self, se_json):
        """Parse symbolic-execution JSON data."""
        try:
            for benchmark, binaries in se_json['results'].items():
                                                               
                benchmark_name = benchmark.replace('benchmark_temp_', '')
                
                                   
                total_time = 0.0
                total_paths = 0
                optimization_levels = {}
                
                for binary_data in binaries:
                    binary_name = binary_data['binary_name']
                                              
                    if '_' in binary_name:
                        opt_level = binary_name.split('_')[-1]
                        optimization_levels[opt_level] = {
                            'execution_time': binary_data['execution_time'],
                            'paths_found': binary_data['paths_found'],
                            'setup_time': binary_data.get('setup_time', 0),
                            'exploration_time': binary_data.get('exploration_time', 0),
                            'analysis_time': binary_data.get('analysis_time', 0)
                        }
                    
                    total_time += binary_data['execution_time']
                    total_paths += binary_data['paths_found']
                
                        
                avg_time = total_time / len(binaries) if binaries else 0
                
                self.symbolic_execution_data[benchmark_name] = {
                    'total_execution_time': total_time,
                    'average_execution_time': avg_time,
                    'total_paths_found': total_paths,
                    'optimization_levels': optimization_levels,
                    'binary_count': len(binaries)
                }
                
        except Exception as e:
            print(f"⚠️  Failed to parse symbolic-execution JSON data: {e}")
    
    def parse_symbolic_execution_file(self, filename):
        """Parse a textual symbolic-execution report file."""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            
                         
            programs = re.findall(r'Program: (.+?)\n', content)
            execution_times = re.findall(r'Execution time: ([0-9.]+) s', content)
            
                         
            sections = content.split('=' * 60)
            for section in sections:
                if 'Analysis result:' in section and 'Program:' in section:
                    program_match = re.search(r'Program: (.+?)\n', section)
                    time_match = re.search(r'Execution time: ([0-9.]+) s', section)
                    paths_match = re.search(r'Paths found: (\d+)', section)
                    
                    if program_match and time_match:
                        program = program_match.group(1).strip()
                        time = float(time_match.group(1))
                        paths = int(paths_match.group(1)) if paths_match else 0
                        
                        self.symbolic_execution_data[program] = {
                            'execution_time': time,
                            'paths_found': paths,
                            'source_file': filename
                        }
        
        except Exception as e:
            print(f"⚠️  Failed to parse {filename}: {e}")
    
    def combine_timing_data(self):
        """Merge symbolic-execution and equivalence-analysis timing data."""
        if not self.equivalence_data:
            return
        

                   
        for program, comparisons in self.equivalence_data['results'].items():
            if program not in self.combined_stats:
                self.combined_stats[program] = {
                    'symbolic_execution_time': 0.0,
                    'equivalence_comparisons': [],
                    'total_equivalence_time': 0.0,
                    'total_paths': 0,
                    'comparison_count': 0
                }
            
            total_eq_time = 0.0
            total_paths = 0
            
            for comparison in comparisons:
                self.combined_stats[program]['equivalence_comparisons'].append({
                    'opt1': comparison['opt1'],
                    'opt2': comparison['opt2'],
                    'time': comparison['execution_time'],
                    'equivalent_pairs': comparison['equivalent_pairs'],
                    'paths_compared': comparison['total_paths_compared']
                })
                total_eq_time += comparison['execution_time']
                total_paths = max(total_paths, comparison['total_paths_compared'])
            
            self.combined_stats[program]['total_equivalence_time'] = total_eq_time
            self.combined_stats[program]['total_paths'] = total_paths
            self.combined_stats[program]['comparison_count'] = len(comparisons)
        
                  
        for program, se_data in self.symbolic_execution_data.items():
                      
            matched_program = None
                      
            if program in self.combined_stats:
                matched_program = program
            else:
                                 
                possible_matches = []
                for combined_program in self.combined_stats.keys():
                    if program in combined_program or combined_program in program:
                        possible_matches.append((combined_program, len(combined_program)))
                                  
                if possible_matches:
                    matched_program = min(possible_matches, key=lambda x: x[1])[0]
            
            if matched_program:
                          
                if 'total_execution_time' in se_data:
                              
                    self.combined_stats[matched_program]['symbolic_execution_time'] = se_data['total_execution_time']
                    self.combined_stats[matched_program]['average_se_time'] = se_data['average_execution_time']
                    self.combined_stats[matched_program]['se_optimization_levels'] = se_data['optimization_levels']
                    self.combined_stats[matched_program]['se_binary_count'] = se_data['binary_count']
                    if se_data['total_paths_found'] > 0:
                        self.combined_stats[matched_program]['total_paths'] = se_data['total_paths_found']
                else:
                            
                    self.combined_stats[matched_program]['symbolic_execution_time'] = se_data['execution_time']
                    if se_data['paths_found'] > 0:
                        self.combined_stats[matched_program]['total_paths'] = se_data['paths_found']
    
    def generate_timing_report(self):
        """Generate a timing summary report."""
        if not self.combined_stats:
            print("❌ No timing data available")
            return
        
        print("\n🕐 Benchmark verification timing report")
        print("=" * 80)
        
              
        total_se_time = sum(stats['symbolic_execution_time'] for stats in self.combined_stats.values())
        total_eq_time = sum(stats['total_equivalence_time'] for stats in self.combined_stats.values())
        total_programs = len(self.combined_stats)
        total_comparisons = sum(stats['comparison_count'] for stats in self.combined_stats.values())
        
        print(f"\n📊 Overall statistics:")
        print(f"  Programs analyzed: {total_programs}")
        print(f"  Equivalence comparisons: {total_comparisons}")
        print(f"  Total symbolic execution time: {total_se_time:.2f} s")
        print(f"  Total equivalence analysis time: {total_eq_time:.2f} s")
        print(f"  Total verification time: {total_se_time + total_eq_time:.2f} s")
        
        print(f"\n📋 Per-program statistics:")
        print("-" * 80)
        print(f"{'Program':<12} {'SE time':<10} {'Eq time':<12} {'Total':<10} {'Paths':<8} {'Comps':<8}")
        print("-" * 80)
        
        sorted_programs = sorted(self.combined_stats.items(), 
                               key=lambda x: x[1]['symbolic_execution_time'] + x[1]['total_equivalence_time'], 
                               reverse=True)
        
        for program, stats in sorted_programs:
            se_time = stats['symbolic_execution_time']
            eq_time = stats['total_equivalence_time']
            total_time = se_time + eq_time
            paths = stats['total_paths']
            comparisons = stats['comparison_count']
            
            print(f"{program:<12} {se_time:<10.2f} {eq_time:<12.2f} {total_time:<10.2f} {paths:<8} {comparisons:<8}")
        
                
        print(f"\n⚡ Time distribution:")
        se_percentage = (total_se_time / (total_se_time + total_eq_time)) * 100 if (total_se_time + total_eq_time) > 0 else 0
        eq_percentage = (total_eq_time / (total_se_time + total_eq_time)) * 100 if (total_se_time + total_eq_time) > 0 else 0
        
        print(f"  Symbolic execution share: {se_percentage:.1f}%")
        print(f"  Equivalence analysis share: {eq_percentage:.1f}%")
        
        avg_se_time = total_se_time / total_programs if total_programs > 0 else 0
        avg_eq_time = total_eq_time / total_comparisons if total_comparisons > 0 else 0
        
        print(f"  Avg SE time: {avg_se_time:.2f} s/program")
        print(f"  Avg equivalence time: {avg_eq_time:.2f} s/comparison")
    
    def generate_detailed_breakdown(self):
        """Generate a detailed timing breakdown report."""
        print(f"\n🔍 Detailed timing breakdown:")
        print("=" * 80)
        
        for program, stats in sorted(self.combined_stats.items()):
            print(f"\n📁 {program}:")
            print(f"  Total symbolic execution time: {stats['symbolic_execution_time']:.2f} s")
            
                            
            if 'se_optimization_levels' in stats:
                print(f"  SE details ({stats.get('se_binary_count', 0)} binaries):")
                for opt_level, opt_data in stats['se_optimization_levels'].items():
                    print(f"    {opt_level}: {opt_data['execution_time']:.2f}s "
                          f"(setup: {opt_data.get('setup_time', 0):.3f}s, "
                          f"explore: {opt_data.get('exploration_time', 0):.3f}s, "
                          f"analysis: {opt_data.get('analysis_time', 0):.3f}s, "
                          f"paths: {opt_data['paths_found']})")
                print(f"    Avg SE time: {stats.get('average_se_time', 0):.2f} s/binary")
            
            print(f"  Total paths found: {stats['total_paths']}")
            print(f"  Equivalence comparisons ({stats['comparison_count']}):")
            
            for comp in stats['equivalence_comparisons']:
                print(f"    {comp['opt1']} vs {comp['opt2']}: {comp['time']:.3f}s "
                      f"({comp['equivalent_pairs']} equivalent pairs, {comp['paths_compared']} paths)")
            
            print(f"  Total equivalence analysis time: {stats['total_equivalence_time']:.2f} s")
            total_time = stats['symbolic_execution_time'] + stats['total_equivalence_time']
            print(f"  🕐 Total time: {total_time:.2f} s")
    
    def save_timing_summary(self):
        """Save timing summary JSON to disk."""
        summary = {
            'generated_time': datetime.now().isoformat(),
            'total_programs': len(self.combined_stats),
            'total_symbolic_execution_time': sum(stats['symbolic_execution_time'] for stats in self.combined_stats.values()),
            'total_equivalence_time': sum(stats['total_equivalence_time'] for stats in self.combined_stats.values()),
            'program_details': dict(self.combined_stats)
        }
        
        with open('benchmark_timing_summary.json', 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Timing summary saved to: benchmark_timing_summary.json")

def main():
    """Main entry."""
    analyzer = BenchmarkTimingAnalyzer()
    
          
    if not analyzer.load_equivalence_data():
        return
    
    analyzer.load_symbolic_execution_data()
    
             
    analyzer.combine_timing_data()
    
          
    analyzer.generate_timing_report()
    analyzer.generate_detailed_breakdown()
    analyzer.save_timing_summary()

if __name__ == "__main__":
    main() 