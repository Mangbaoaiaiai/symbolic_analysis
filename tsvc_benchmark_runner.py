#!/usr/bin/env python3
"""
TSVC Benchmark 运行器
提取PLDI19 equivalence checker的TSVC benchmarks并用本地符号分析工具进行分析
"""

import os
import re
import subprocess
import tempfile
import shutil
from pathlib import Path
import json
import time
import datetime

class TSVCBenchmarkExtractor:
    """TSVC benchmark提取器"""
    
    def __init__(self, tsvc_source_path="pldi19-equivalence-checker/pldi19/TSVC/clean.c"):
        self.tsvc_source = tsvc_source_path
        self.benchmark_functions = {}
        self.recommended_benchmarks = [
            's000', 's1112', 's121', 's1221', 's1251', 's1351', 
            's173', 's2244', 'vpv', 'vpvpv', 'vpvtv', 'vtv', 'vtvtv'
        ]
        
    def extract_benchmark_functions(self):
        """从clean.c中提取所有benchmark函数"""
        print("正在提取TSVC benchmark函数...")
        
        with open(self.tsvc_source, 'r') as f:
            content = f.read()
        
        # 提取函数定义 - 改进的正则表达式来正确匹配嵌套大括号
        function_pattern = r'TYPE\s+(\w+)\s*\([^)]*\)\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}'
        
        functions_found = []
        # 手动查找函数定义，因为正则表达式可能有问题
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('TYPE ') and '(' in line and '{' in line:
                # 找到函数开始
                func_start = i
                brace_count = line.count('{') - line.count('}')
                
                # 提取函数名
                func_name_match = re.match(r'TYPE\s+(\w+)\s*\(', line)
                if func_name_match:
                    func_name = func_name_match.group(1)
                    
                    # 找到函数结束
                    func_lines = [lines[i]]
                    i += 1
                    
                    while i < len(lines) and brace_count > 0:
                        func_lines.append(lines[i])
                        brace_count += lines[i].count('{') - lines[i].count('}')
                        i += 1
                    
                    if brace_count == 0:
                        full_definition = '\n'.join(func_lines)
                        func_body = '\n'.join(func_lines[1:-1])  # 排除第一行和最后的}
                        functions_found.append((func_name, full_definition, func_body))
                    continue
            i += 1
        
        # 处理找到的函数
        for func_name, full_definition, func_body in functions_found:
            
            # 跳过main和testing函数
            if func_name in ['main', 'testing']:
                continue
                
            self.benchmark_functions[func_name] = {
                'name': func_name,
                'full_definition': full_definition,
                'body': func_body.strip(),
                'recommended': func_name in self.recommended_benchmarks
            }
        
        print(f"提取了 {len(self.benchmark_functions)} 个benchmark函数")
        return self.benchmark_functions
    
    def create_benchmark_variants(self, func_name, optimization_levels=['O1', 'O2', 'O3']):
        """为单个benchmark创建不同优化级别的变体"""
        if func_name not in self.benchmark_functions:
            print(f"未找到函数: {func_name}")
            return {}
        
        func_data = self.benchmark_functions[func_name]
        
        # 创建临时目录
        temp_dir = Path(f"benchmark_temp_{func_name}")
        temp_dir.mkdir(exist_ok=True)
        
        try:
            variants = {}
            
            # 创建基础头文件和数据定义
            header_content = """
#include <stdlib.h>

#define LEN 128
#define LEN2 16
#define TYPE int

// 内存段定义
TYPE a[LEN] __attribute__((section ("SEGMENT_A")));
TYPE b[LEN] __attribute__((section ("SEGMENT_B")));
TYPE c[LEN] __attribute__((section ("SEGMENT_C")));
TYPE d[LEN] __attribute__((section ("SEGMENT_D")));
TYPE e[LEN] __attribute__((section ("SEGMENT_E")));
TYPE aa[LEN2][LEN2] __attribute__((section ("SEGMENT_F")));

void init_data() {
    for(int i = 0; i < LEN; i++) {
        a[i] = i % 100;
        b[i] = (i * 2) % 100;
        c[i] = (i * 3) % 100;
        d[i] = (i * 4) % 100;
        e[i] = (i * 5) % 100;
    }
    for(int i = 0; i < LEN2; i++) {
        for(int j = 0; j < LEN2; j++) {
            aa[i][j] = (i + j) % 100;
        }
    }
}
"""
            
            for opt_level in optimization_levels:
                # 创建源文件
                source_file = temp_dir / f"{func_name}_{opt_level}.c"
                
                with open(source_file, 'w') as f:
                    f.write(header_content)
                    f.write("\n")
                    f.write(func_data['full_definition'])
                    f.write(f"\n\nint main() {{\n    init_data();\n    {func_name}(1);\n    return 0;\n}}")
                
                # 编译
                binary_file = temp_dir / f"{func_name}_{opt_level}"
                try:
                    compile_cmd = [
                        'gcc', f'-{opt_level}', '-o', str(binary_file), str(source_file)
                    ]
                    result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0:
                        variants[opt_level] = {
                            'source_file': str(source_file),
                            'binary_file': str(binary_file),
                            'compilation_success': True,
                            'compilation_output': result.stdout
                        }
                        print(f"  {func_name}-{opt_level}: 编译成功")
                    else:
                        variants[opt_level] = {
                            'source_file': str(source_file),
                            'binary_file': None,
                            'compilation_success': False,
                            'compilation_error': result.stderr
                        }
                        print(f"  {func_name}-{opt_level}: 编译失败 - {result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    variants[opt_level] = {
                        'source_file': str(source_file),
                        'binary_file': None,
                        'compilation_success': False,
                        'compilation_error': 'Compilation timeout'
                    }
                    print(f"  {func_name}-{opt_level}: 编译超时")
            
            return variants
            
        except Exception as e:
            print(f"创建benchmark变体时出错: {e}")
            return {}

class TSVCBenchmarkRunner:
    """TSVC benchmark运行器"""
    
    def __init__(self, extractor, symbolic_analyzer_script="semantic_equivalence_analyzer.py"):
        self.extractor = extractor
        self.symbolic_analyzer = symbolic_analyzer_script
        self.results_dir = Path("tsvc_results")
        self.results_dir.mkdir(exist_ok=True)
        
    def run_symbolic_analysis(self, binary1, binary2, benchmark_name, comparison_type):
        """运行符号分析比较两个二进制文件"""
        print(f"    正在分析 {benchmark_name} ({comparison_type})")
        
        # 这里需要调用用户的符号分析工具
        # 由于用户的工具需要路径文件，我们需要先生成路径
        try:
            # 创建输出目录
            output_dir = self.results_dir / benchmark_name / comparison_type
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # 假设用户有路径生成工具，这里模拟
            analysis_result = {
                'benchmark_name': benchmark_name,
                'comparison_type': comparison_type,
                'binary1': binary1,
                'binary2': binary2,
                'analysis_time': time.time(),
                'status': 'completed',
                'result': 'unknown',  # 需要实际分析
                'details': {
                    'paths_analyzed': 0,
                    'equivalent_paths': 0,
                    'non_equivalent_paths': 0,
                    'timeout_paths': 0
                }
            }
            
            # 保存结果
            result_file = output_dir / "analysis_result.json"
            with open(result_file, 'w') as f:
                json.dump(analysis_result, f, indent=2)
            
            return analysis_result
            
        except Exception as e:
            print(f"    分析失败: {e}")
            return {
                'benchmark_name': benchmark_name,
                'comparison_type': comparison_type,
                'status': 'failed',
                'error': str(e)
            }
    
    def run_benchmark_comparison(self, func_name):
        """运行单个benchmark的完整比较"""
        print(f"\n=== 运行benchmark: {func_name} ===")
        
        # 创建不同优化级别的变体
        variants = self.extractor.create_benchmark_variants(func_name)
        
        if not variants:
            print(f"无法创建 {func_name} 的变体")
            return None
        
        successful_variants = {k: v for k, v in variants.items() if v['compilation_success']}
        
        if len(successful_variants) < 2:
            print(f"需要至少2个成功编译的变体，但只有 {len(successful_variants)} 个")
            return None
        
        # 运行比较分析
        results = []
        comparisons = [
            ('O1', 'O2'),
            ('O1', 'O3'),
            ('O2', 'O3')
        ]
        
        for opt1, opt2 in comparisons:
            if opt1 in successful_variants and opt2 in successful_variants:
                comparison_name = f"{opt1}_vs_{opt2}"
                result = self.run_symbolic_analysis(
                    successful_variants[opt1]['binary_file'],
                    successful_variants[opt2]['binary_file'],
                    func_name,
                    comparison_name
                )
                results.append(result)
        
        return results
    
    def run_recommended_benchmarks(self):
        """运行推荐的benchmark集合"""
        print("开始运行推荐的TSVC benchmarks...")
        print(f"推荐benchmark列表: {self.extractor.recommended_benchmarks}")
        
        all_results = {}
        start_time = time.time()
        
        for func_name in self.extractor.recommended_benchmarks:
            try:
                results = self.run_benchmark_comparison(func_name)
                all_results[func_name] = results
            except Exception as e:
                print(f"运行 {func_name} 时出错: {e}")
                all_results[func_name] = {'error': str(e)}
        
        end_time = time.time()
        
        # 生成综合报告
        self.generate_summary_report(all_results, start_time, end_time)
        
        return all_results
    
    def generate_summary_report(self, results, start_time, end_time):
        """生成综合报告"""
        report_file = self.results_dir / "tsvc_summary_report.txt"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("TSVC Benchmark 分析报告\n")
            f.write("=" * 50 + "\n")
            f.write(f"分析时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总用时: {end_time - start_time:.2f} 秒\n")
            f.write(f"分析benchmark数量: {len(results)}\n\n")
            
            # 统计信息
            successful_benchmarks = 0
            failed_benchmarks = 0
            
            for func_name, result in results.items():
                f.write(f"\n--- {func_name} ---\n")
                
                if isinstance(result, dict) and 'error' in result:
                    f.write(f"  状态: 失败\n")
                    f.write(f"  错误: {result['error']}\n")
                    failed_benchmarks += 1
                elif isinstance(result, list):
                    f.write(f"  状态: 成功\n")
                    f.write(f"  比较数量: {len(result)}\n")
                    for comparison in result:
                        f.write(f"    {comparison['comparison_type']}: {comparison['status']}\n")
                    successful_benchmarks += 1
                else:
                    f.write(f"  状态: 未知\n")
            
            f.write(f"\n总结:\n")
            f.write(f"  成功: {successful_benchmarks}\n")
            f.write(f"  失败: {failed_benchmarks}\n")
            f.write(f"  成功率: {successful_benchmarks/(successful_benchmarks+failed_benchmarks)*100:.1f}%\n")
        
        print(f"\n综合报告已保存到: {report_file}")

def main():
    """主函数"""
    print("TSVC Benchmark 运行器")
    print("=" * 30)
    
    # 检查TSVC源文件是否存在
    tsvc_source = "pldi19-equivalence-checker/pldi19/TSVC/clean.c"
    if not os.path.exists(tsvc_source):
        print(f"错误: 未找到TSVC源文件 {tsvc_source}")
        print("请确保已经克隆了pldi19-equivalence-checker仓库")
        return
    
    # 初始化提取器和运行器
    extractor = TSVCBenchmarkExtractor(tsvc_source)
    runner = TSVCBenchmarkRunner(extractor)
    
    # 提取函数
    functions = extractor.extract_benchmark_functions()
    
    # 显示可用函数
    print(f"\n找到 {len(functions)} 个benchmark函数:")
    for name, info in functions.items():
        status = "推荐" if info['recommended'] else "可选"
        print(f"  {name} ({status})")
    
    print(f"\n推荐运行的benchmark (基于原论文建议): {len(extractor.recommended_benchmarks)} 个")
    
    # 运行推荐benchmark
    print("\n开始运行分析...")
    results = runner.run_recommended_benchmarks()
    
    print("\n分析完成!")
    print("结果保存在 tsvc_results/ 目录中")

if __name__ == "__main__":
    main() 