                      
"""
约束质量检查脚本 - 分析所有生成的约束文件的质量
专门检查symbolic_*_path_*.txt文件中的有意义约束
"""

import os
import glob
import re
from pathlib import Path

class ConstraintQualityChecker:
    def __init__(self, base_dir="/root/ardiff/symbolic_analysis"):
        self.base_dir = Path(base_dir)
        self.meaningful_constraints = []
        self.empty_constraints = []
        self.constraint_summary = {}
        
    def analyze_constraint_file(self, file_path):
        """分析单个约束文件的质量"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
                          
            indicators = {
                'has_scanf_vars': 'scanf_' in content,
                'has_smt_assertions': '(assert' in content and content.count('(assert') > 0,
                'non_zero_constraints': 'count: 0' not in content,
                'has_variables': "variables': {}" not in content and "输入变量值: {}" not in content,
                'has_bitvec_declarations': 'declare-fun' in content and 'BitVec' in content,
                'has_program_output': 'Result:' in content and content.split('Result:')[1].strip() != ''
            }
            
                    
            constraint_count_match = re.search(r"count[':]\s*(\d+)", content)
            constraint_count = int(constraint_count_match.group(1)) if constraint_count_match else 0
            
                    
            var_match = re.search(r"输入变量值:\s*({[^}]*})", content)
            variables_info = var_match.group(1) if var_match else "{}"
            
                    
            output_match = re.search(r"Result:\s*([^\n]+)", content)
            program_output = output_match.group(1).strip() if output_match else ""
            
                    
            quality_score = sum(indicators.values())
            is_meaningful = quality_score >= 3            
            
            file_info = {
                'file_path': str(file_path),
                'quality_score': quality_score,
                'is_meaningful': is_meaningful,
                'constraint_count': constraint_count,
                'variables_info': variables_info,
                'program_output': program_output,
                'indicators': indicators,
                'content_preview': content[:200] + "..." if len(content) > 200 else content
            }
            
            if is_meaningful:
                self.meaningful_constraints.append(file_info)
            else:
                self.empty_constraints.append(file_info)
                
            return file_info
            
        except Exception as e:
            print(f"❌ 读取文件失败: {file_path}, 错误: {e}")
            return None
    
    def find_all_constraint_files(self):
        """查找所有约束文件"""
                    
        pattern = str(self.base_dir / "**" / "*_path_*.txt")
        constraint_files = glob.glob(pattern, recursive=True)
        return sorted(constraint_files)
    
    def analyze_all_constraints(self):
        """分析所有约束文件"""
        print("🔍 开始分析所有约束文件...")
        
        constraint_files = self.find_all_constraint_files()
        print(f"📋 找到 {len(constraint_files)} 个约束文件")
        
               
        symbolic_files = [f for f in constraint_files if 'symbolic_' in os.path.basename(f)]
        original_files = [f for f in constraint_files if 'symbolic_' not in os.path.basename(f)]
        
        print(f"  • 符号化版本文件: {len(symbolic_files)}个")
        print(f"  • 原始版本文件: {len(original_files)}个\n")
        
                
        for i, file_path in enumerate(constraint_files, 1):
            print(f"[{i}/{len(constraint_files)}] 分析: {os.path.relpath(file_path, self.base_dir)}")
            self.analyze_constraint_file(file_path)
            
        return len(constraint_files)
    
    def generate_detailed_report(self):
        """生成详细的约束质量报告"""
        total_files = len(self.meaningful_constraints) + len(self.empty_constraints)
        
        if total_files == 0:
            print("❌ 没有找到约束文件进行分析")
            return
        
        meaningful_count = len(self.meaningful_constraints)
        empty_count = len(self.empty_constraints)
        meaningful_rate = (meaningful_count / total_files) * 100
        
        report = f"""
🎯 约束质量分析详细报告
{'='*60}

📊 总体统计:
  • 总约束文件数: {total_files}
  • 有意义约束数: {meaningful_count}
  • 空约束数: {empty_count}
  • 有意义比率: {meaningful_rate:.1f}%

🏆 高质量约束文件详情:
{'='*40}
"""
        
        if self.meaningful_constraints:
            for i, constraint in enumerate(self.meaningful_constraints, 1):
                file_name = os.path.relpath(constraint['file_path'], self.base_dir)
                report += f"""
[{i}] {file_name}
  ✅ 质量分数: {constraint['quality_score']}/6
  📊 约束数量: {constraint['constraint_count']}
  🎲 输入变量: {constraint['variables_info']}
  📤 程序输出: {constraint['program_output']}
  🔍 质量指标:
"""
                for indicator, value in constraint['indicators'].items():
                    status = "✅" if value else "❌"
                    report += f"    {status} {indicator}: {value}\n"
        else:
            report += "  ❌ 暂无高质量约束文件\n"
        
        report += f"""
📁 空约束文件概览:
{'='*40}
"""
        
        if self.empty_constraints:
                          
            empty_by_test = {}
            for constraint in self.empty_constraints:
                test_name = self.extract_test_name(constraint['file_path'])
                if test_name not in empty_by_test:
                    empty_by_test[test_name] = []
                empty_by_test[test_name].append(constraint)
            
            for test_name, constraints in empty_by_test.items():
                report += f"\n🔸 {test_name}: {len(constraints)}个空约束文件\n"
                for constraint in constraints[:2]:            
                    file_name = os.path.basename(constraint['file_path'])
                    report += f"    • {file_name} (质量分数: {constraint['quality_score']}/6)\n"
                if len(constraints) > 2:
                    report += f"    • ... 还有{len(constraints)-2}个文件\n"
        else:
            report += "  🎉 没有空约束文件!\n"
        
        report += f"""
🎯 符号化程序专项分析:
{'='*40}
"""
        
                      
        symbolic_meaningful = [c for c in self.meaningful_constraints if 'symbolic_' in os.path.basename(c['file_path'])]
        symbolic_empty = [c for c in self.empty_constraints if 'symbolic_' in os.path.basename(c['file_path'])]
        symbolic_total = len(symbolic_meaningful) + len(symbolic_empty)
        
        if symbolic_total > 0:
            symbolic_rate = (len(symbolic_meaningful) / symbolic_total) * 100
            report += f"""
  📊 符号化程序约束统计:
    • 总符号化约束: {symbolic_total}个
    • 有意义约束: {len(symbolic_meaningful)}个
    • 空约束: {len(symbolic_empty)}个
    • 成功率: {symbolic_rate:.1f}%
"""
            
            if symbolic_meaningful:
                report += f"\n  🏆 成功的符号化测试用例:\n"
                for constraint in symbolic_meaningful:
                    test_name = self.extract_test_name(constraint['file_path'])
                    file_name = os.path.basename(constraint['file_path'])
                    report += f"    ✅ {test_name}/{file_name}\n"
        else:
            report += "  ❌ 没有找到符号化程序的约束文件\n"
        
        report += f"""
💡 改进建议:
{'='*40}
"""
        
        if meaningful_rate < 50:
            report += """
  🔧 当前约束生成成功率较低，建议：
    1. 检查程序的输入处理逻辑
    2. 优化scanf符号化hook
    3. 调整符号执行超时和路径限制
    4. 改进C程序的浮点数处理
"""
        else:
            report += """
  🎉 约束生成成功率良好！可以考虑：
    1. 扩大符号变量的取值范围
    2. 增加更多路径探索
    3. 优化约束求解器配置
"""
        
        report += f"\n⏱️  分析完成时间: {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}"
        
              
        report_file = self.base_dir / "constraint_quality_analysis_report.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(report)
        print(f"\n📄 详细报告已保存至: {report_file}")
        
        return report
    
    def extract_test_name(self, file_path):
        """从文件路径提取测试名称"""
        path_parts = Path(file_path).parts
        if 'benchmarks' in path_parts:
            idx = path_parts.index('benchmarks')
            if len(path_parts) > idx + 3:
                return '/'.join(path_parts[idx+1:idx+4])                   
        return os.path.dirname(file_path)
    
    def run_analysis(self):
        """运行完整的约束质量分析"""
        print("🚀 启动约束质量分析...")
        
        total_analyzed = self.analyze_all_constraints()
        
        if total_analyzed > 0:
            print("\n" + "="*60)
            print("🎉 约束质量分析完成！")
            self.generate_detailed_report()
        else:
            print("❌ 没有找到约束文件进行分析")
        
        return total_analyzed > 0

if __name__ == "__main__":
    checker = ConstraintQualityChecker()
    checker.run_analysis() 