                      
"""
Summary script for batched equivalence-analysis results.
"""

import json
import datetime

def load_analysis_data():
    """Load batched equivalence-analysis data from JSON."""
    try:
        with open('batch_equivalence_analysis_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ Analysis data file not found: batch_equivalence_analysis_data.json")
        return None

def print_summary(data):
    """Print a human-readable summary of equivalence results."""
    summary = data['summary']
    results = data['results']
    
    print("🎯 Batched equivalence-analysis summary")
    print("=" * 60)
    
          
    start_time = datetime.datetime.fromtimestamp(summary['start_time'])
    end_time = datetime.datetime.fromtimestamp(summary['end_time'])
    print(f"⏱️  Analysis time:")
    print(f"  Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  End:   {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total: {summary['total_time']:.1f} s ({summary['total_time']/60:.1f} min)")
    
          
    print(f"\n📊 Overall statistics:")
    print(f"  Programs analyzed: {len(results)}")
    print(f"  Total comparisons: {summary['successful_count'] + summary['failed_count']}")
    print(f"  Successful comparisons: {summary['successful_count']}")
    print(f"  Failed comparisons: {summary['failed_count']}")
    print(f"  Success rate: {summary['successful_count']/(summary['successful_count']+summary['failed_count'])*100:.1f}%")
    
           
    print(f"\n✅ Equivalence results:")
    print(f"  Fully equivalent program pairs: {summary['total_equivalent_programs']}")
    print(f"  Total fully equivalent path pairs: {summary['total_equivalent_pairs']}")
    print(f"  Total partially equivalent path pairs: {summary['total_partial_pairs']}")
    
           
    print(f"\n📋 Per-program results:")
    program_stats = []
    
    for program, program_results in results.items():
        successful = [r for r in program_results if r['success']]
        equivalent = [r for r in successful if r['program_equivalent']]
        
        total_time = sum(r['execution_time'] for r in successful)
        equiv_rate = len(equivalent) / len(program_results) * 100 if program_results else 0
        
        program_stats.append({
            'program': program,
            'total_comparisons': len(program_results),
            'equivalent_pairs': len(equivalent),
            'equiv_rate': equiv_rate,
            'total_time': total_time
        })
    
            
    program_stats.sort(key=lambda x: (x['equiv_rate'], x['equivalent_pairs']), reverse=True)
    
    for stat in program_stats:
        print(f"  {stat['program']}: {stat['equivalent_pairs']}/{stat['total_comparisons']} "
              f"({stat['equiv_rate']:.1f}%) - {stat['total_time']:.1f}s")
    
                      
    if 's000' in results:
        print(f"\n🔍 Detailed results for s000 (including O0 optimization level):")
        s000_results = results['s000']
        for result in s000_results:
            equiv_status = "✅ equivalent" if result['program_equivalent'] else "❌ not equivalent"
            print(f"  {result['opt1']} vs {result['opt2']}: {equiv_status} "
                  f"({result['equivalent_pairs']} fully equivalent pairs, {result['execution_time']:.1f}s)")
    
          
    all_successful = data['successful_analyses']
    if all_successful:
        avg_time = sum(r['execution_time'] for r in all_successful) / len(all_successful)
        print(f"\n⚡ Performance statistics:")
        print(f"  Average comparison time: {avg_time:.2f} s")
        print(f"  Fastest comparison: {min(r['execution_time'] for r in all_successful):.2f} s")
        print(f"  Slowest comparison: {max(r['execution_time'] for r in all_successful):.2f} s")

def main():
    data = load_analysis_data()
    if data:
        print_summary(data)
    else:
        print("Please run the batched equivalence analysis first: python batch_equivalence_analyzer.py")

if __name__ == "__main__":
    main() 