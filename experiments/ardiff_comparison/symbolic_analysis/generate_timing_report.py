                      
"""
生成完整的benchmark时间统计报告
收集符号执行和等价性分析的时间数据
"""

import os
import glob
import re
from pathlib import Path

class TimingReportGenerator:
    def __init__(self, base_dir="/root/ardiff/symbolic_analysis"):
        self.base_dir = Path(base_dir)
        
    def extract_se_timing(self, program_dir):
        """从timing报告中提取符号执行时间"""
        timing_files = glob.glob(os.path.join(program_dir, "*_timing_report.txt"))
        
        total_se_time = 0.0
        total_paths = 0
        
        for timing_file in timing_files:
            try:
                with open(timing_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                        
                time_match = re.search(r'总计时间:\s*([\d.]+)\s*秒', content)
                if time_match:
                    total_se_time += float(time_match.group(1))
                
                       
                paths_match = re.search(r'发现路径数:\s*(\d+)', content)
                if paths_match:
                    total_paths += int(paths_match.group(1))
                    
            except Exception as e:
                print(f"Error reading {timing_file}: {e}")
                
        return total_se_time, total_paths
    
    def extract_eq_timing(self, program_dir, eq_type):
        """从等价性分析报告中提取时间"""
        eq_file = os.path.join(program_dir, f"equivalence_analysis_{eq_type}.txt")
        
        if not os.path.exists(eq_file):
            return 0.0, 0, False, "no_file"
            
        try:
            with open(eq_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
                     
            time_match = re.search(r'总分析时间:\s*([\d.]+)\s*秒', content)
            eq_time = float(time_match.group(1)) if time_match else 0.0
            
                     
            result_match = re.search(r'程序等价性:\s*(.*)', content)
            is_equivalent = False
            result_status = "unknown"
            
            if result_match:
                result_text = result_match.group(1).strip()
                if "✅ 等价" in result_text:
                    is_equivalent = True
                    result_status = "equivalent"
                elif "❌ 不等价" in result_text:
                    is_equivalent = False
                    result_status = "not_equivalent"
            
                                
            equivalent_pairs = 0
            partial_pairs = 0
            non_equivalent_pairs = 0
            
            eq_match = re.search(r'完全等价路径对:\s*(\d+)', content)
            if eq_match:
                equivalent_pairs = int(eq_match.group(1))
                
            partial_match = re.search(r'部分等价路径对:\s*(\d+)', content)
            if partial_match:
                partial_pairs = int(partial_match.group(1))
                
            non_eq_match = re.search(r'非等价路径对:\s*(\d+)', content)
            if non_eq_match:
                non_equivalent_pairs = int(non_eq_match.group(1))
            
            total_comparisons = equivalent_pairs + partial_pairs + non_equivalent_pairs
            
            return eq_time, total_comparisons, is_equivalent, result_status
            
        except Exception as e:
            print(f"Error reading {eq_file}: {e}")
            return 0.0, 0, False, "error"
    
    def get_program_category(self, program_dir):
        """获取程序类别"""
        path_parts = Path(program_dir).parts
        if len(path_parts) >= 3:
            return path_parts[1]                           
        return "Unknown"
    
    def collect_all_timing_data(self):
        """收集所有程序的时间数据"""
                     
        eq_reports = glob.glob(str(self.base_dir / "benchmarks" / "**" / "equivalence_analysis_*.txt"), recursive=True)
        
        data = []
        
        for report_file in eq_reports:
            program_dir = os.path.dirname(report_file)
            report_name = os.path.basename(report_file)
            
                             
            if "equivalence_analysis_Eq.txt" in report_name:
                eq_type = "Eq"
            elif "equivalence_analysis_NEq.txt" in report_name:
                eq_type = "NEq"
            else:
                continue
            
                    
            rel_path = os.path.relpath(program_dir, self.base_dir)
            category = self.get_program_category(program_dir)
            
                      
            se_time, se_paths = self.extract_se_timing(program_dir)
            
                       
            eq_time, eq_comparisons, is_equivalent, result_status = self.extract_eq_timing(program_dir, eq_type)
            
                                  
            expected_equivalent = (eq_type == "Eq")
            is_correct = (is_equivalent == expected_equivalent)
            
            data.append({
                'path': rel_path,
                'category': category,
                'type': eq_type,
                'se_time': se_time,
                'se_paths': se_paths,
                'eq_time': eq_time,
                'eq_comparisons': eq_comparisons,
                'total_time': se_time + eq_time,
                'is_equivalent': is_equivalent,
                'result_status': result_status,
                'expected_equivalent': expected_equivalent,
                'is_correct': is_correct
            })
        
        return sorted(data, key=lambda x: (x['category'], x['path'], x['type']))
    
    def generate_markdown_report(self, data, output_file="benchmark_timing_report.md"):
        """生成Markdown格式的详细报告"""
        
                
        total_se_time = sum(d['se_time'] for d in data)
        total_eq_time = sum(d['eq_time'] for d in data)
        total_time = total_se_time + total_eq_time
        total_paths = sum(d['se_paths'] for d in data)
        total_comparisons = sum(d['eq_comparisons'] for d in data)
        
               
        eq_data = [d for d in data if d['type'] == 'Eq']
        neq_data = [d for d in data if d['type'] == 'NEq']
        
        eq_correct = sum(1 for d in eq_data if d['is_correct'])
        neq_correct = sum(1 for d in neq_data if d['is_correct'])
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# Benchmark验证过程完整时间统计报告\n\n")
            
                  
            f.write("## 总体统计\n\n")
            f.write("| 指标 | 数值 | 说明 |\n")
            f.write("|------|------|------|\n")
            f.write(f"| **符号执行总时间** | **{total_se_time:.1f}秒** ({total_se_time/60:.1f}分钟) | 占总时间{total_se_time/total_time*100:.1f}% |\n")
            f.write(f"| **等价性分析总时间** | **{total_eq_time:.1f}秒** | 占总时间{total_eq_time/total_time*100:.1f}% |\n")
            f.write(f"| **总验证时间** | **{total_time:.1f}秒** ({total_time/60:.1f}分钟) | 完整验证流程 |\n")
            f.write(f"| **分析程序对数** | **{len(data)}个** | {len(eq_data)}个Eq + {len(neq_data)}个NEq |\n")
            f.write(f"| **总路径数** | **{total_paths}条** | 符号执行生成 |\n")
            f.write(f"| **总比较次数** | **{total_comparisons}次** | 路径对比较 |\n")
            f.write(f"| **预测准确率** | **{(eq_correct+neq_correct)/len(data)*100:.1f}%** | {eq_correct+neq_correct}/{len(data)}正确 |\n")
            f.write("\n")
            
                   
            f.write("## 分类统计\n\n")
            f.write("| 类型 | 程序数 | 符号执行时间 | 等价性分析时间 | 正确预测 | 准确率 |\n")
            f.write("|------|--------|--------------|----------------|----------|--------|\n")
            
            eq_se_time = sum(d['se_time'] for d in eq_data)
            eq_eq_time = sum(d['eq_time'] for d in eq_data)
            f.write(f"| **Eq (应该等价)** | {len(eq_data)} | {eq_se_time:.1f}s | {eq_eq_time:.1f}s | {eq_correct} | {eq_correct/len(eq_data)*100:.1f}% |\n")
            
            neq_se_time = sum(d['se_time'] for d in neq_data)
            neq_eq_time = sum(d['eq_time'] for d in neq_data)
            f.write(f"| **NEq (应该不等价)** | {len(neq_data)} | {neq_se_time:.1f}s | {neq_eq_time:.1f}s | {neq_correct} | {neq_correct/len(neq_data)*100:.1f}% |\n")
            f.write("\n")
            
                    
            f.write("## 详细时间统计\n\n")
            f.write("| Benchmark | 类型 | 符号执行(s) | 等价性分析(s) | 总时间(s) | 路径数 | 比较次数 | 预测结果 | 准确性 |\n")
            f.write("|-----------|------|-------------|---------------|-----------|--------|----------|----------|--------|\n")
            
            for d in data:
                benchmark_name = d['path'].replace('benchmarks/', '').replace('/', '_')
                result_icon = "✅" if d['is_equivalent'] else "❌"
                accuracy_icon = "✅" if d['is_correct'] else "❌"
                
                f.write(f"| **{benchmark_name}** | {d['type']} | {d['se_time']:.1f} | {d['eq_time']:.1f} | "
                       f"**{d['total_time']:.1f}** | {d['se_paths']} | {d['eq_comparisons']} | "
                       f"{result_icon} | {accuracy_icon} |\n")
            
            f.write("\n")
            
                    
            f.write("## 错误预测分析\n\n")
            
            wrong_eq = [d for d in eq_data if not d['is_correct']]
            wrong_neq = [d for d in neq_data if not d['is_correct']]
            
            if wrong_eq:
                f.write("### Eq程序被错误预测为不等价:\n\n")
                for d in wrong_eq:
                    f.write(f"- `{d['path']}` (符号执行: {d['se_time']:.1f}s, 分析: {d['eq_time']:.1f}s)\n")
                f.write("\n")
            
            if wrong_neq:
                f.write("### NEq程序被错误预测为等价:\n\n")
                for d in wrong_neq:
                    f.write(f"- `{d['path']}` (符号执行: {d['se_time']:.1f}s, 分析: {d['eq_time']:.1f}s)\n")
                f.write("\n")
            
                  
            f.write("## 性能分析\n\n")
            f.write(f"- **平均符号执行时间**: {total_se_time/len(data):.1f}秒/程序对\n")
            f.write(f"- **平均等价性分析时间**: {total_eq_time/len(data):.1f}秒/程序对\n")
            f.write(f"- **平均路径数**: {total_paths/len(data):.1f}条/程序对\n")
            f.write(f"- **平均比较次数**: {total_comparisons/len(data):.1f}次/程序对\n")
            f.write(f"- **符号执行效率**: {total_paths/total_se_time:.1f}路径/秒\n")
            f.write(f"- **等价性分析效率**: {total_comparisons/total_eq_time:.1f}比较/秒\n")
        
        print(f"📄 详细时间统计报告已保存到: {output_file}")
        return output_file

def main():
    print("🔧 生成benchmark时间统计报告...")
    
    generator = TimingReportGenerator()
    
          
    print("📊 收集时间数据...")
    data = generator.collect_all_timing_data()
    
    print(f"✅ 收集到 {len(data)} 个程序的数据")
    
          
    report_file = generator.generate_markdown_report(data)
    
    print("🎯 报告生成完成!")
    return report_file

if __name__ == "__main__":
    main() 