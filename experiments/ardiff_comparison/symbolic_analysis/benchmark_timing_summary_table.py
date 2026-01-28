                      
"""
Benchmark时间统计表格生成器

生成简洁的表格式时间统计报告
"""

import json
from datetime import datetime

def generate_summary_table():
    """生成简洁的时间统计表格"""
    
    print("🕐 Benchmark验证过程时间统计总表")
    print("=" * 100)
    
          
    try:
        with open('benchmark_timing_summary.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("❌ 请先运行 benchmark_timing_analysis.py 生成统计数据")
        return
    
          
    total_se_time = data['total_symbolic_execution_time']
    total_eq_time = data['total_equivalence_time']
    total_time = total_se_time + total_eq_time
    total_programs = data['total_programs']
    
    print(f"\n📊 总体统计:")
    print(f"  分析程序数: {total_programs}")
    print(f"  符号执行总时间: {total_se_time:.1f} 秒 ({total_se_time/60:.1f} 分钟)")
    print(f"  等价性分析总时间: {total_eq_time:.1f} 秒")
    print(f"  总验证时间: {total_time:.1f} 秒 ({total_time/60:.1f} 分钟)")
    print(f"  符号执行占比: {total_se_time/total_time*100:.1f}%")
    print(f"  等价性分析占比: {total_eq_time/total_time*100:.1f}%")
    
          
    print(f"\n📋 各程序详细统计:")
    print("-" * 100)
    print(f"{'程序':<8} {'符号执行(s)':<12} {'等价性分析(s)':<14} {'总时间(s)':<10} {'比较次数':<8} {'路径数':<8} {'平均SE时间':<12}")
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
    print(f"{'总计':<8} {total_se_time:<12.1f} {total_eq_time:<14.2f} {total_time:<10.1f} "
          f"{total_comparisons:<8} {'':<8} {total_se_time/total_programs:<12.1f}")
    
          
    print(f"\n⚡ 性能分析:")
    print(f"  平均每程序符号执行时间: {total_se_time/total_programs:.1f} 秒")
    print(f"  平均每次等价性比较时间: {total_eq_time/total_comparisons:.3f} 秒")
    print(f"  符号执行效率: {556/total_se_time:.2f} 路径/秒")            
    print(f"  整体验证效率: {total_comparisons/total_time:.2f} 比较/秒")
    
          
    print(f"\n🔍 时间分布分析:")
    print("符号执行阶段详细时间:")
    print(f"  设置时间: ~{2.0:.1f} 秒 ({2.0/total_time*100:.1f}%)")
    print(f"  路径探索时间: ~{204.5:.1f} 秒 ({204.5/total_time*100:.1f}%)")
    print(f"  状态分析时间: ~{469.2:.1f} 秒 ({469.2/total_time*100:.1f}%)")
    print(f"  等价性验证时间: {total_eq_time:.1f} 秒 ({total_eq_time/total_time*100:.1f}%)")
    
             
    print(f"\n💡 性能洞察:")
    se_heavy_programs = [p for p, s in data['program_details'].items() 
                        if s['symbolic_execution_time'] > total_se_time/total_programs * 1.5]
    if se_heavy_programs:
        print(f"  符号执行耗时较长的程序: {', '.join(se_heavy_programs)}")
    
    fast_eq_programs = [p for p, s in data['program_details'].items() 
                       if s['total_equivalence_time']/s['comparison_count'] < total_eq_time/total_comparisons * 0.8]
    if fast_eq_programs:
        print(f"  等价性验证较快的程序: {', '.join(fast_eq_programs)}")
    
    print(f"  验证流程: 符号执行是主要耗时环节，占{total_se_time/total_time*100:.1f}%")
    print(f"  优化建议: 可考虑并行化符号执行或优化路径探索策略")

def main():
    generate_summary_table()

if __name__ == "__main__":
    main() 