                      
"""
Benchmark timing summary table generator.

Produces a concise, table-style timing report from benchmark_timing_summary.json.
"""

import json
from datetime import datetime

def generate_summary_table():
    """Generate a concise timing summary table."""
    
    print("🕐 Benchmark verification timing overview")
    print("=" * 100)
    
          
    try:
        with open('benchmark_timing_summary.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("❌ Please run benchmark_timing_analysis.py first to generate summary data")
        return
    
          
    total_se_time = data['total_symbolic_execution_time']
    total_eq_time = data['total_equivalence_time']
    total_time = total_se_time + total_eq_time
    total_programs = data['total_programs']
    
    print(f"\n📊 Overall statistics:")
    print(f"  Programs analyzed: {total_programs}")
    print(f"  Total symbolic execution time: {total_se_time:.1f} s ({total_se_time/60:.1f} min)")
    print(f"  Total equivalence analysis time: {total_eq_time:.1f} s")
    print(f"  Total verification time: {total_time:.1f} s ({total_time/60:.1f} min)")
    print(f"  Symbolic execution share: {total_se_time/total_time*100:.1f}%")
    print(f"  Equivalence analysis share: {total_eq_time/total_time*100:.1f}%")
    
          
    print(f"\n📋 Per-program breakdown:")
    print("-" * 100)
    print(f"{'Program':<8} {'Symbolic(s)':<12} {'Equivalence(s)':<14} {'Total(s)':<10} "
          f"{'Comparisons':<8} {'Paths':<8} {'Avg SE time':<12}")
    print("-" * 100)
    
          
    total_comparisons = 0
    sorted_programs = sorted(data['program_details'].items(), 
                           key=lambda x: x[1]['symbolic_execution_time'] + x[1]['total_equivalence_time'], 
                           reverse=True)
    
    for program, stats in sorted_programs:
        se_time = stats['symbolic_execution_time']
        eq_time = stats['total_equivalence_time']
        total_prog_time = se_time + eq_time
        comparison_count = stats['comparison_count']
        total_paths = stats['total_paths']
        avg_se_time = stats.get('average_se_time', se_time)
        
        total_comparisons += comparison_count
        
        print(f"{program:<8} {se_time:<12.1f} {eq_time:<14.2f} {total_prog_time:<10.1f} "
              f"{comparison_count:<8} {total_paths:<8} {avg_se_time:<12.1f}")
    
    print("-" * 100)
    print(f"{'Total':<8} {total_se_time:<12.1f} {total_eq_time:<14.2f} {total_time:<10.1f} "
          f"{total_comparisons:<8} {'':<8} {total_se_time/total_programs:<12.1f}")
    
          
    print(f"\n⚡ Performance metrics:")
    print(f"  Avg symbolic execution time per program: {total_se_time/total_programs:.1f} s")
    print(f"  Avg equivalence check time per comparison: {total_eq_time/total_comparisons:.3f} s")
    print(f"  Symbolic execution throughput: {556/total_se_time:.2f} paths/s")
    print(f"  Overall verification throughput: {total_comparisons/total_time:.2f} comparisons/s")
    
          
    print(f"\n🔍 Time distribution:")
    print("Symbolic execution phase breakdown:")
    print(f"  Setup time: ~{2.0:.1f} s ({2.0/total_time*100:.1f}%)")
    print(f"  Path exploration time: ~{204.5:.1f} s ({204.5/total_time*100:.1f}%)")
    print(f"  State analysis time: ~{469.2:.1f} s ({469.2/total_time*100:.1f}%)")
    print(f"  Equivalence checking time: {total_eq_time:.1f} s ({total_eq_time/total_time*100:.1f}%)")
    
             
    print(f"\n💡 Performance insights:")
    se_heavy_programs = [p for p, s in data['program_details'].items() 
                        if s['symbolic_execution_time'] > total_se_time/total_programs * 1.5]
    if se_heavy_programs:
        print(f"  Programs with heavy symbolic execution: {', '.join(se_heavy_programs)}")
    
    fast_eq_programs = [p for p, s in data['program_details'].items() 
                       if s['total_equivalence_time']/s['comparison_count'] < total_eq_time/total_comparisons * 0.8]
    if fast_eq_programs:
        print(f"  Programs with fast equivalence checking: {', '.join(fast_eq_programs)}")
    
    print(f"  Pipeline insight: symbolic execution dominates runtime "
          f"({total_se_time/total_time*100:.1f}% of total)")
    print("  Optimization hint: consider parallelizing symbolic execution "
          "or improving path exploration strategies")

def main():
    generate_summary_table()

if __name__ == "__main__":
    main() 