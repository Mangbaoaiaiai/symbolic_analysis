                      
"""
批量等价性分析结果总结脚本
"""

import json
import datetime

def load_analysis_data():
    """加载分析数据"""
    try:
        with open('batch_equivalence_analysis_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ 未找到分析数据文件: batch_equivalence_analysis_data.json")
        return None

def print_summary(data):
    """打印总结信息"""
    summary = data['summary']
    results = data['results']
    
    print("🎯 批量等价性分析总结")
    print("=" * 60)
    
          
    start_time = datetime.datetime.fromtimestamp(summary['start_time'])
    end_time = datetime.datetime.fromtimestamp(summary['end_time'])
    print(f"⏱️  分析时间:")
    print(f"  开始: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  结束: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  总耗时: {summary['total_time']:.1f} 秒 ({summary['total_time']/60:.1f} 分钟)")
    
          
    print(f"\n📊 总体统计:")
    print(f"  分析程序数: {len(results)}")
    print(f"  总比较次数: {summary['successful_count'] + summary['failed_count']}")
    print(f"  成功比较: {summary['successful_count']}")
    print(f"  失败比较: {summary['failed_count']}")
    print(f"  成功率: {summary['successful_count']/(summary['successful_count']+summary['failed_count'])*100:.1f}%")
    
           
    print(f"\n✅ 等价性结果:")
    print(f"  完全等价的程序对: {summary['total_equivalent_programs']}")
    print(f"  完全等价路径对总数: {summary['total_equivalent_pairs']}")
    print(f"  部分等价路径对总数: {summary['total_partial_pairs']}")
    
           
    print(f"\n📋 各程序结果:")
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
        print(f"\n🔍 s000程序详细结果 (包含O0优化等级):")
        s000_results = results['s000']
        for result in s000_results:
            equiv_status = "✅ 等价" if result['program_equivalent'] else "❌ 不等价"
            print(f"  {result['opt1']} vs {result['opt2']}: {equiv_status} "
                  f"({result['equivalent_pairs']} 完全等价对, {result['execution_time']:.1f}s)")
    
          
    all_successful = data['successful_analyses']
    if all_successful:
        avg_time = sum(r['execution_time'] for r in all_successful) / len(all_successful)
        print(f"\n⚡ 性能统计:")
        print(f"  平均比较时间: {avg_time:.2f} 秒")
        print(f"  最快比较: {min(r['execution_time'] for r in all_successful):.2f} 秒")
        print(f"  最慢比较: {max(r['execution_time'] for r in all_successful):.2f} 秒")

def main():
    data = load_analysis_data()
    if data:
        print_summary(data)
    else:
        print("请先运行批量等价性分析: python batch_equivalence_analyzer.py")

if __name__ == "__main__":
    main() 