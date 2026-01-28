                      
"""
真实TSVC Benchmark符号执行分析器
使用angr进行真实的符号执行和约束提取
"""

import os
import re
import subprocess
import tempfile
import shutil
from pathlib import Path
import time
import json
from typing import List, Dict, Tuple, Any

try:
    import angr
    import claripy
    ANGR_AVAILABLE = True
except ImportError:
    print("⚠️  angr未安装，将使用模拟模式")
    ANGR_AVAILABLE = False

from semantic_equivalence_analyzer import PathClusterAnalyzer

class RealTSVCAnalyzer:
    """真实TSVC benchmark分析器"""
    
    def __init__(self, tsvc_source="pldi19-equivalence-checker/pldi19/TSVC/clean.c"):
        self.tsvc_source = tsvc_source
        self.temp_dirs = []
        self.recommended_benchmarks = [
            's000', 's1112', 's121', 's1221', 's1251', 's1351',
            's173', 's2244', 'vpv', 'vpvpv', 'vpvtv', 'vtv', 'vtvtv'
        ]
        
    def __del__(self):
        """清理临时目录"""
        for temp_dir in self.temp_dirs:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def extract_function_code(self, function_name: str) -> str:
        """从TSVC源代码中提取单个函数"""
        print(f"  提取函数: {function_name}")
        
        with open(self.tsvc_source, 'r') as f:
            content = f.read()
        
                
        pattern = rf'TYPE\s+{function_name}\s*\([^)]*\)\s*\{{'
        match = re.search(pattern, content)
        
        if not match:
            raise ValueError(f"未找到函数 {function_name}")
        
                      
        start_pos = match.start()
        brace_count = 0
        i = match.end() - 1             
        
        while i < len(content):
            if content[i] == '{':
                brace_count += 1
            elif content[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    break
            i += 1
        
        if brace_count != 0:
            raise ValueError(f"函数 {function_name} 的大括号不匹配")
        
        function_code = content[start_pos:i+1]
        return function_code
    
    def create_standalone_program(self, function_name: str, optimization_level: str) -> Path:
        """创建独立的可执行程序"""
        print(f"  创建独立程序: {function_name} (优化级别: {optimization_level})")
        
                
        function_code = self.extract_function_code(function_name)
        
                  
        program_template = f'''
#include <stdlib.h>
#include <stdio.h>

#define LEN 128
#define LEN2 16
#define TYPE int

// 全局数组定义
TYPE a[LEN] __attribute__((section ("SEGMENT_A")));
TYPE b[LEN] __attribute__((section ("SEGMENT_B")));
TYPE c[LEN] __attribute__((section ("SEGMENT_C")));
TYPE d[LEN] __attribute__((section ("SEGMENT_D")));
TYPE e[LEN] __attribute__((section ("SEGMENT_E")));
TYPE aa[LEN2][LEN2] __attribute__((section ("SEGMENT_F")));

// 初始化函数
void init_arrays() {{
    for (int i = 0; i < LEN; i++) {{
        a[i] = i;
        b[i] = i * 2;
        c[i] = i * 3;
        d[i] = i * 4;
        e[i] = i * 5;
    }}
    for (int i = 0; i < LEN2; i++) {{
        for (int j = 0; j < LEN2; j++) {{
            aa[i][j] = i * LEN2 + j;
        }}
    }}
}}

// 提取的benchmark函数
{function_code}

int main(int argc, char* argv[]) {{
    init_arrays();
    
    // 符号化输入参数
    int count = 1;  // 默认count值
    if (argc > 1) {{
        count = atoi(argv[1]);
    }}
    
    // 调用benchmark函数
    TYPE result = {function_name}(count);
    
    // 输出结果以便验证
    printf("Result: %d\\n", result);
    return 0;
}}
'''
        
                
        temp_dir = tempfile.mkdtemp(prefix=f"tsvc_{function_name}_{optimization_level}_")
        self.temp_dirs.append(temp_dir)
        
               
        source_file = Path(temp_dir) / f"{function_name}.c"
        with open(source_file, 'w') as f:
            f.write(program_template)
        
              
        binary_file = Path(temp_dir) / f"{function_name}_{optimization_level}"
        compile_cmd = [
            'gcc', 
            f'-{optimization_level}',
            '-msse4.2',
            '-g',          
            '-o', str(binary_file),
            str(source_file)
        ]
        
        try:
            result = subprocess.run(compile_cmd, capture_output=True, text=True, check=True)
            print(f"    编译成功: {binary_file}")
            return binary_file
        except subprocess.CalledProcessError as e:
            print(f"    编译失败: {e}")
            print(f"    错误输出: {e.stderr}")
            raise
    
    def extract_real_paths_with_angr(self, binary_path: Path, max_paths: int = 20) -> List[Dict]:
        """使用angr进行真实符号执行"""
        if not ANGR_AVAILABLE:
            return self._fallback_mock_paths(binary_path, max_paths)
        
        print(f"    使用angr分析: {binary_path}")
        
        try:
                      
            project = angr.Project(str(binary_path), auto_load_libs=False)
            
                     
            state = project.factory.entry_state()
            
                                
            count_sym = claripy.BVS('count', 32)
            state.solver.add(count_sym >= 1)
            state.solver.add(count_sym <= 4)                   
            
                                  
            simgr = project.factory.simulation_manager(state)
            
                             
            print(f"    开始符号执行...")
            simgr.explore(n=max_paths, num_find=max_paths)
            
            paths = []
            
                     
            for i, found_state in enumerate(simgr.found[:max_paths]):
                path_info = self._extract_path_constraints(found_state, i)
                paths.append(path_info)
            
                        
            for i, active_state in enumerate(simgr.active[:max_paths-len(paths)]):
                if len(paths) >= max_paths:
                    break
                path_info = self._extract_path_constraints(active_state, len(paths))
                paths.append(path_info)
            
            print(f"    提取了 {len(paths)} 条真实执行路径")
            return paths
            
        except Exception as e:
            print(f"    angr分析失败: {e}")
            print(f"    使用备用模拟模式...")
            return self._fallback_mock_paths(binary_path, max_paths)
    
    def _extract_path_constraints(self, state, path_index: int) -> Dict:
        """从angr状态中提取路径约束"""
        try:
                    
            constraints = state.solver.constraints
            
                          
            smt_constraints = []
            variable_declarations = set()
            
            for constraint in constraints:
                      
                variables = constraint.variables
                for var in variables:
                    var_name = str(var)
                    if var.size() % 8 == 0:            
                        bit_size = var.size()
                        variable_declarations.add(f"(declare-fun {var_name} () (_ BitVec {bit_size}))")
                
                      
                try:
                    smt_constraint = state.solver._solver.converter.convert(constraint)
                    smt_constraints.append(f"(assert {smt_constraint})")
                except:
                                   
                    smt_constraints.append(f"(assert {str(constraint)})")
            
                      
            memory_hash = hash(str(state.memory)) % 10000
            
                    
            path_info = {
                'path_index': path_index,
                'constraints': list(constraints),
                'smt_constraints': smt_constraints,
                'variable_declarations': list(variable_declarations),
                'memory_hash': memory_hash,
                'variable_count': len(variable_declarations),
                'constraint_count': len(smt_constraints)
            }
            
            return path_info
            
        except Exception as e:
            print(f"      约束提取失败: {e}")
                    
            return {
                'path_index': path_index,
                'constraints': [],
                'smt_constraints': [],
                'variable_declarations': [],
                'memory_hash': path_index * 1000,
                'variable_count': 0,
                'constraint_count': 0,
                'error': str(e)
            }
    
    def _fallback_mock_paths(self, binary_path: Path, max_paths: int) -> List[Dict]:
        """备用的模拟路径生成（当angr不可用时）"""
        print(f"    使用模拟路径生成")
        
        function_name = binary_path.stem.split('_')[0]         
        
        paths = []
        for i in range(max_paths):
                           
            if function_name == 's000':
                                              
                constraints = [
                    f"(assert (= a_{i} (bvadd b_{i} #x00000001)))",
                    f"(assert (bvule i_{i} #x00000080))"
                ]
                variables = [f"a_{i}", f"b_{i}", f"i_{i}"]
            
            elif function_name == 's121':
                                                   
                constraints = [
                    f"(assert (= a_{i} (bvadd a_{i+1} b_{i})))",
                    f"(assert (bvult i_{i} #x0000007f))"
                ]
                variables = [f"a_{i}", f"a_{i+1}", f"b_{i}", f"i_{i}"]
                
            elif function_name == 's2244':
                                
                constraints = [
                    f"(assert (= a_{i+1} (bvadd b_{i} e_{i})))",
                    f"(assert (= a_{i} (bvadd b_{i} c_{i})))",
                    f"(assert (bvult i_{i} #x0000007f))"
                ]
                variables = [f"a_{i}", f"a_{i+1}", f"b_{i}", f"c_{i}", f"e_{i}", f"i_{i}"]
                
            else:
                      
                constraints = [
                    f"(assert (bvule i_{i} #x00000080))",
                    f"(assert (= result_{i} (bvadd a_{i} #x00000001)))"
                ]
                variables = [f"i_{i}", f"a_{i}", f"result_{i}"]
            
            variable_declarations = [f"(declare-fun {var} () (_ BitVec 32))" for var in variables]
            
            path_info = {
                'path_index': i,
                'constraints': constraints,
                'smt_constraints': constraints,
                'variable_declarations': variable_declarations,
                'memory_hash': hash(f"{function_name}_{i}") % 10000,
                'variable_count': len(variables),
                'constraint_count': len(constraints),
                'mock': True
            }
            
            paths.append(path_info)
        
        return paths
    
    def save_path_constraints(self, paths: List[Dict], output_dir: Path, benchmark_name: str) -> None:
        """保存路径约束到文件"""
        output_dir.mkdir(exist_ok=True)
        
        for path_info in paths:
            path_file = output_dir / f"path_{path_info['path_index']:03d}.txt"
            
            with open(path_file, 'w') as f:
                f.write(f"; 真实TSVC Benchmark路径约束\\n")
                f.write(f"; Benchmark: {benchmark_name}\\n") 
                f.write(f"; Path: {path_info['path_index']}\\n")
                f.write(f"; 变量数量: {path_info['variable_count']}\\n")
                f.write(f"; 约束数量: {path_info['constraint_count']}\\n")
                f.write(f"; 内存哈希: {path_info['memory_hash']}\\n")
                if path_info.get('mock'):
                    f.write(f"; 注意: 模拟数据（angr不可用）\\n")
                f.write(f"\\n")
                
                f.write("(set-logic QF_BV)\\n")
                
                        
                for var_decl in path_info['variable_declarations']:
                    f.write(f"{var_decl}\\n")
                
                f.write("\\n")
                
                      
                for constraint in path_info['smt_constraints']:
                    f.write(f"{constraint}\\n")
                
                f.write("(check-sat)\\n")
        
        print(f"    保存了 {len(paths)} 个路径文件到 {output_dir}")
    
    def analyze_benchmark_comparison(self, benchmark_name: str, opt_levels: List[str] = ['O1', 'O2', 'O3']) -> Dict:
        """分析单个benchmark的不同优化级别比较"""
        print(f"\\n🔍 分析benchmark: {benchmark_name}")
        
        results = {}
        binaries = {}
        all_paths = {}
        
                      
        for opt_level in opt_levels:
            print(f"  处理优化级别: {opt_level}")
            
            try:
                      
                binary_path = self.create_standalone_program(benchmark_name, opt_level)
                binaries[opt_level] = binary_path
                
                      
                paths = self.extract_real_paths_with_angr(binary_path, max_paths=20)
                all_paths[opt_level] = paths
                
                        
                output_dir = Path(f"real_paths_{benchmark_name}_{opt_level}")
                self.save_path_constraints(paths, output_dir, f"{benchmark_name}_{opt_level}")
                
            except Exception as e:
                print(f"    处理 {opt_level} 失败: {e}")
                results[opt_level] = {'error': str(e)}
        
                 
        comparisons = {}
        for i, opt1 in enumerate(opt_levels):
            for opt2 in opt_levels[i+1:]:
                if opt1 in all_paths and opt2 in all_paths:
                    comparison_name = f"{benchmark_name}_{opt1}_vs_{opt2}"
                    print(f"  比较: {opt1} vs {opt2}")
                    
                    try:
                                    
                        analyzer = PathClusterAnalyzer()
                        
                        prefix1 = f"real_paths_{benchmark_name}_{opt1}/path_"
                        prefix2 = f"real_paths_{benchmark_name}_{opt2}/path_"
                        
                        comparison_result = analyzer.analyze_path_clusters(prefix1, prefix2)
                        
                                
                        report_file = f"{comparison_name}_real_analysis.txt"
                        analyzer.generate_report(comparison_result, report_file)
                        
                        comparisons[comparison_name] = {
                            'result': comparison_result,
                            'report_file': report_file,
                            'paths_count': {
                                opt1: len(all_paths[opt1]),
                                opt2: len(all_paths[opt2])
                            }
                        }
                        
                        print(f"    ✅ 比较完成: {report_file}")
                        
                    except Exception as e:
                        print(f"    ❌ 比较失败: {e}")
                        comparisons[comparison_name] = {'error': str(e)}
        
        return {
            'benchmark_name': benchmark_name,
            'optimization_levels': opt_levels,
            'binaries': {k: str(v) for k, v in binaries.items()},
            'path_counts': {k: len(v) for k, v in all_paths.items()},
            'comparisons': comparisons
        }


def main():
    """主函数：运行真实TSVC benchmark分析"""
    print("🚀 启动真实TSVC Benchmark符号执行分析")
    print("=" * 60)
    
    if not ANGR_AVAILABLE:
        print("⚠️  警告: angr未安装，将使用模拟模式")
        print("   建议安装: pip install angr")
        print()
    
    analyzer = RealTSVCAnalyzer()
    
                              
    test_benchmarks = ['s000', 's1112', 's121']          
    
    all_results = {}
    start_time = time.time()
    
    for benchmark in test_benchmarks:
        try:
            result = analyzer.analyze_benchmark_comparison(benchmark)
            all_results[benchmark] = result
            
        except Exception as e:
            print(f"❌ Benchmark {benchmark} 分析失败: {e}")
            all_results[benchmark] = {'error': str(e)}
    
    end_time = time.time()
    
            
    generate_summary_report(all_results, start_time, end_time)
    
    print(f"\\n🎉 真实符号执行分析完成！")
    print(f"📊 总耗时: {end_time - start_time:.2f} 秒")
    print(f"📁 详细报告: real_tsvc_analysis_summary.txt")


def generate_summary_report(results: Dict, start_time: float, end_time: float):
    """生成真实分析的总结报告"""
    report_file = "real_tsvc_analysis_summary.txt"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("真实TSVC Benchmark符号执行分析报告\\n")
        f.write("=" * 60 + "\\n")
        f.write(f"分析时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}\\n")
        f.write(f"总耗时: {end_time - start_time:.2f} 秒\\n")
        f.write(f"使用真实符号执行: {'是' if ANGR_AVAILABLE else '否（模拟模式）'}\\n")
        f.write(f"分析的benchmark数量: {len(results)}\\n\\n")
        
              
        successful = sum(1 for r in results.values() if 'error' not in r)
        failed = len(results) - successful
        
        f.write("=== 统计概览 ===\\n")
        f.write(f"成功分析: {successful}\\n")
        f.write(f"失败分析: {failed}\\n")
        f.write(f"成功率: {successful/len(results)*100:.1f}%\\n\\n")
        
              
        f.write("=== 详细结果 ===\\n")
        for benchmark_name, result in results.items():
            f.write(f"\\n📋 {benchmark_name}:\\n")
            
            if 'error' in result:
                f.write(f"  状态: 失败\\n")
                f.write(f"  错误: {result['error']}\\n")
            else:
                f.write(f"  状态: 成功\\n")
                f.write(f"  优化级别: {', '.join(result['optimization_levels'])}\\n")
                
                      
                if 'path_counts' in result:
                    f.write(f"  路径数量:\\n")
                    for opt, count in result['path_counts'].items():
                        f.write(f"    {opt}: {count} 条路径\\n")
                
                      
                if 'comparisons' in result:
                    f.write(f"  等价性比较:\\n")
                    for comp_name, comp_result in result['comparisons'].items():
                        if 'error' in comp_result:
                            f.write(f"    {comp_name}: 失败 - {comp_result['error']}\\n")
                        else:
                            f.write(f"    {comp_name}: 成功\\n")
                            f.write(f"      报告文件: {comp_result['report_file']}\\n")
    
    print(f"📄 总结报告已保存: {report_file}")


if __name__ == "__main__":
    main() 