                      
"""
调试脚本：分析path文件生成机制
"""

import os
import re
import subprocess
import tempfile
import shutil
from pathlib import Path
import time
from typing import List, Dict, Tuple, Any

try:
    import angr
    import claripy
    ANGR_AVAILABLE = True
except ImportError:
    print("❌ angr未安装")
    ANGR_AVAILABLE = False

class DebugPathGenerator:
    """调试路径生成过程"""
    
    def __init__(self, tsvc_source="pldi19-equivalence-checker/pldi19/TSVC/clean.c"):
        self.tsvc_source = tsvc_source
        self.temp_dirs = []
        
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
    
    def create_test_program(self, function_name: str) -> Path:
        """创建测试程序"""
        print(f"  创建测试程序: {function_name}")
        
                
        function_code = self.extract_function_code(function_name)
        
                  
        program_template = f'''
#include <stdlib.h>
#include <stdio.h>

#define LEN 128
#define LEN2 16
#define TYPE int

TYPE a[LEN];
TYPE b[LEN];
TYPE c[LEN];

// 初始化函数
void init_arrays() {{
    for (int i = 0; i < LEN; i++) {{
        a[i] = i;
        b[i] = i * 2;
        c[i] = i * 3;
    }}
}}

// 提取的benchmark函数
{function_code}

int main(int argc, char* argv[]) {{
    init_arrays();
    
    int count = 1;
    if (argc > 1) {{
        count = atoi(argv[1]);
    }}
    
    TYPE result = {function_name}(count);
    printf("Result: %d\\n", result);
    return 0;
}}
'''
        
                
        temp_dir = tempfile.mkdtemp(prefix=f"debug_{function_name}_")
        self.temp_dirs.append(temp_dir)
        
               
        source_file = Path(temp_dir) / f"{function_name}.c"
        with open(source_file, 'w') as f:
            f.write(program_template)
        
              
        binary_file = Path(temp_dir) / f"{function_name}"
        compile_cmd = ['gcc', '-O1', '-g', '-o', str(binary_file), str(source_file)]
        
        subprocess.run(compile_cmd, capture_output=True, text=True, check=True)
        print(f"    编译成功: {binary_file}")
        return binary_file
    
    def debug_angr_exploration(self, binary_path: Path, max_paths: int = 20) -> List[Dict]:
        """详细调试angr探索过程"""
        if not ANGR_AVAILABLE:
            print("❌ angr不可用")
            return []
        
        print(f"🔍 开始调试angr探索: {binary_path}")
        
                  
        project = angr.Project(str(binary_path), auto_load_libs=False)
        print(f"  ✅ 创建了angr项目")
        
                 
        state = project.factory.entry_state()
        print(f"  ✅ 创建了入口状态")
        
                  
        count_sym = claripy.BVS('count', 32)
        state.solver.add(count_sym >= 1)
        state.solver.add(count_sym <= 4)
        print(f"  ✅ 添加了符号化约束")
        
                              
        simgr = project.factory.simulation_manager(state)
        print(f"  ✅ 创建了simulation manager")
        print(f"  📊 初始状态数量: active={len(simgr.active)}, found={len(simgr.found)}")
        
              
        print(f"  🚀 开始探索路径 (max_paths={max_paths})...")
        
                 
        step = 0
        while simgr.active and len(simgr.found) < max_paths and step < 50:
            step += 1
            print(f"    步骤 {step}: active={len(simgr.active)}, found={len(simgr.found)}, deadended={len(simgr.deadended)}")
            
                  
            simgr.step()
        
        print(f"  🏁 探索完成!")
        print(f"    最终状态: active={len(simgr.active)}, found={len(simgr.found)}, deadended={len(simgr.deadended)}")
        
        paths = []
        
                   
        print(f"  📋 处理found状态 ({len(simgr.found)} 个)...")
        for i, found_state in enumerate(simgr.found[:max_paths]):
            print(f"    处理found状态 {i}")
            path_info = self._debug_extract_constraints(found_state, len(paths))
            paths.append(path_info)
        
                    
        print(f"  📋 处理active状态 ({len(simgr.active)} 个)...")
        for i, active_state in enumerate(simgr.active[:max_paths-len(paths)]):
            if len(paths) >= max_paths:
                break
            print(f"    处理active状态 {i}")
            path_info = self._debug_extract_constraints(active_state, len(paths))
            paths.append(path_info)
        
        print(f"  ✅ 总共提取了 {len(paths)} 条路径")
        return paths
    
    def _debug_extract_constraints(self, state, path_index: int) -> Dict:
        """调试约束提取过程"""
        print(f"      提取路径 {path_index} 的约束...")
        
        try:
                    
            constraints = state.solver.constraints
            print(f"        原始约束数量: {len(constraints)}")
            
                          
            smt_constraints = []
            variable_declarations = set()
            
            for j, constraint in enumerate(constraints):
                print(f"        处理约束 {j}: {str(constraint)[:100]}...")
                
                      
                try:
                    variables = constraint.variables
                    print(f"          变量数量: {len(variables)}")
                    
                    for var in variables:
                        var_name = str(var)
                        if hasattr(var, 'size') and var.size() % 8 == 0:
                            bit_size = var.size()
                            variable_declarations.add(f"(declare-fun {var_name} () (_ BitVec {bit_size}))")
                except Exception as e:
                    print(f"          变量提取失败: {e}")
                
                      
                try:
                    smt_constraint = state.solver._solver.converter.convert(constraint)
                    smt_constraints.append(f"(assert {smt_constraint})")
                except Exception as e:
                    print(f"          约束转换失败: {e}")
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
            
            print(f"        ✅ 路径 {path_index}: {len(variable_declarations)} 变量, {len(smt_constraints)} 约束, 哈希={memory_hash}")
            return path_info
            
        except Exception as e:
            print(f"        ❌ 约束提取失败: {e}")
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


def main():
    """运行调试"""
    print("🔍 开始调试路径生成过程")
    print("=" * 50)
    
    if not ANGR_AVAILABLE:
        print("❌ angr不可用，无法进行调试")
        return
    
    debugger = DebugPathGenerator()
    
              
    function_name = 's000'
    try:
        binary_path = debugger.create_test_program(function_name)
        paths = debugger.debug_angr_exploration(binary_path, max_paths=20)
        
        print(f"\n📊 最终结果:")
        print(f"   生成了 {len(paths)} 条路径")
        for i, path in enumerate(paths):
            print(f"   路径 {i}: {path['variable_count']} 变量, {path['constraint_count']} 约束, 哈希={path['memory_hash']}")
            
    except Exception as e:
        print(f"❌ 调试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main() 