                      
"""
正确的符号化转换脚本
保持原始程序的逻辑和差异性，只是将输入方式从命令行参数改为scanf
将所有浮点参数改为整数类型以适配符号执行脚本
"""

import os
import re
import glob
import shutil
from pathlib import Path

class CorrectSymbolicConverter:
    def __init__(self, base_dir="/root/ardiff/symbolic_analysis"):
        self.base_dir = Path(base_dir)
        
    def extract_snippet_function(self, content):
        """提取snippet函数"""
                         
        lines = content.split('\n')
        snippet_start = -1
        snippet_end = -1
        
                        
        for i, line in enumerate(lines):
            if 'snippet(' in line and (line.strip().startswith('double') or line.strip().startswith('int') or line.strip().startswith('float')):
                snippet_start = i
                break
        
        if snippet_start == -1:
            return None
        
                 
        brace_count = 0
        in_function = False
        
        for i in range(snippet_start, len(lines)):
            line = lines[i]
            for char in line:
                if char == '{':
                    brace_count += 1
                    in_function = True
                elif char == '}':
                    brace_count -= 1
                    if in_function and brace_count == 0:
                        snippet_end = i
                        break
            if snippet_end != -1:
                break
        
        if snippet_end != -1:
            return '\n'.join(lines[snippet_start:snippet_end + 1])
        
        return None
    
    def convert_float_params_to_int(self, snippet_function):
        """将浮点参数转换为整数参数"""
                                  
        converted = re.sub(r'\bdouble\b', 'int', snippet_function)
        converted = re.sub(r'\bfloat\b', 'int', converted)
        return converted
    
    def analyze_original_program(self, file_path):
        """分析原始程序的结构"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        info = {
            'snippet_function': None,
            'parameters': [],
            'parameter_types': [],
            'includes': [],
            'return_type': 'int',
            'has_void_params': False
        }
        
                
        includes = re.findall(r'#include\s*[<"][^>"]+[>"]', content)
        info['includes'] = includes
        
                     
        snippet_func = self.extract_snippet_function(content)
        if snippet_func:
                        
            snippet_func = self.convert_float_params_to_int(snippet_func)
            info['snippet_function'] = snippet_func
            
                       
            func_line = snippet_func.split('\n')[0]
            
                             
            info['return_type'] = 'int'
            
                  
            param_match = re.search(r'snippet\s*\(([^)]*)\)', func_line)
            if param_match:
                params_str = param_match.group(1).strip()
                if params_str == 'void' or params_str == '':
                    info['has_void_params'] = True
                elif params_str:
                                     
                    params = [p.strip() for p in params_str.split(',')]
                    for param in params:
                        param_parts = param.strip().split()
                        if len(param_parts) >= 2:
                                       
                            param_type = 'int'
                            param_name = param_parts[-1]
                            info['parameters'].append(param_name)
                            info['parameter_types'].append(param_type)
                else:
                    info['has_void_params'] = True
        
        return info
    
    def generate_symbolic_version(self, original_info, original_path):
        """生成符号化版本，保持原始逻辑"""
        
                 
        lines = []
        
                
        for include in original_info['includes']:
            lines.append(include)
        
                    
        if '#include <stdio.h>' not in '\n'.join(lines):
            lines.insert(0, '#include <stdio.h>')
        if '#include <stdlib.h>' not in '\n'.join(lines):
            lines.insert(1, '#include <stdlib.h>')
                            
        if any('#include <math.h>' in include for include in original_info['includes']):
            if '#include <math.h>' not in '\n'.join(lines):
                lines.append('#include <math.h>')
        
        lines.append('')
        
                                
        if original_info['snippet_function']:
            lines.append(original_info['snippet_function'])
        
        lines.append('')
        
                    
        lines.append('int main() {')
        lines.append('    // 符号化输入 - angr会自动处理这些scanf调用')
        
                
        if original_info['has_void_params']:
                                 
            lines.append('    int result = snippet();')
        elif original_info['parameters'] and original_info['parameter_types']:
                           
            for param_type, param_name in zip(original_info['parameter_types'], original_info['parameters']):
                lines.append(f'    {param_type} {param_name};')
            
                               
            scanf_format = []
            scanf_vars = []
            
            for param_name in original_info['parameters']:
                scanf_format.append('%d')
                scanf_vars.append(f'&{param_name}')
            
            format_str = ' '.join(scanf_format)
            vars_str = ', '.join(scanf_vars)
            lines.append(f'    scanf("{format_str}", {vars_str});')
            
                         
            params_str = ', '.join(original_info['parameters'])
            lines.append(f'    int result = snippet({params_str});')
        else:
                            
            lines.append('    int x;')
            lines.append('    scanf("%d", &x);')
            lines.append('    int result = snippet(x);')
        
              
        lines.append('    printf("Result: %d\\n", result);')
        lines.append('    return 0;')
        lines.append('}')
        
        return '\n'.join(lines)
    
    def convert_program_pair(self, newv_path, oldv_path):
        """转换一对程序"""
        print(f"🔄 转换程序对:")
        print(f"  newV: {os.path.relpath(newv_path, self.base_dir)}")
        print(f"  oldV: {os.path.relpath(oldv_path, self.base_dir)}")
        
                
        newv_info = self.analyze_original_program(newv_path)
        oldv_info = self.analyze_original_program(oldv_path)
        
                           
        if not newv_info['snippet_function'] or not oldv_info['snippet_function']:
            print(f"  ❌ 无法提取snippet函数")
            return None, None
        
                 
        newv_symbolic = self.generate_symbolic_version(newv_info, newv_path)
        oldv_symbolic = self.generate_symbolic_version(oldv_info, oldv_path)
        
                 
        program_dir = os.path.dirname(newv_path)
        symbolic_newv_path = os.path.join(program_dir, 'symbolic_newV.c')
        symbolic_oldv_path = os.path.join(program_dir, 'symbolic_oldV.c')
        
              
        with open(symbolic_newv_path, 'w', encoding='utf-8') as f:
            f.write(newv_symbolic)
        
        with open(symbolic_oldv_path, 'w', encoding='utf-8') as f:
            f.write(oldv_symbolic)
        
        print(f"  ✅ 生成: {os.path.relpath(symbolic_newv_path, self.base_dir)}")
        print(f"  ✅ 生成: {os.path.relpath(symbolic_oldv_path, self.base_dir)}")
        
        return symbolic_newv_path, symbolic_oldv_path
    
    def find_all_program_pairs(self):
        """查找所有原始程序对"""
        newv_files = glob.glob(str(self.base_dir / "benchmarks" / "**" / "newV.c"), recursive=True)
        pairs = []
        
        for newv_path in newv_files:
            program_dir = os.path.dirname(newv_path)
            oldv_path = os.path.join(program_dir, 'oldV.c')
            
            if os.path.exists(oldv_path):
                pairs.append((newv_path, oldv_path))
        
        return pairs
    
    def clean_old_symbolic_files(self):
        """清理旧的符号化文件"""
        print("🧹 清理旧的符号化文件...")
        
        files_deleted = 0
        
                            
        old_symbolic_files = glob.glob(str(self.base_dir / "benchmarks" / "**" / "symbolic_*.c"), recursive=True)
        for file_path in old_symbolic_files:
            try:
                os.remove(file_path)
                files_deleted += 1
            except Exception as e:
                print(f"  ❌ 删除失败: {file_path}, 错误: {e}")
        
                   
        old_executables = glob.glob(str(self.base_dir / "benchmarks" / "**" / "symbolic_*"), recursive=True)
        old_executables = [f for f in old_executables if not f.endswith('.c') and not f.endswith('.txt') and os.path.isfile(f)]
        for file_path in old_executables:
            try:
                os.remove(file_path)
                files_deleted += 1
            except Exception as e:
                print(f"  ❌ 删除失败: {file_path}, 错误: {e}")
        
                  
        old_constraint_files = glob.glob(str(self.base_dir / "benchmarks" / "**" / "*_path_*.txt"), recursive=True)
        for file_path in old_constraint_files:
            try:
                os.remove(file_path)
                files_deleted += 1
            except Exception as e:
                print(f"  ❌ 删除失败: {file_path}, 错误: {e}")
        
        print(f"✅ 清理完成，删除了 {files_deleted} 个文件")
    
    def convert_all_programs(self):
        """转换所有程序"""
        print("🚀 开始正确的符号化转换...")
        print("=" * 60)
        
               
        self.clean_old_symbolic_files()
        
                 
        pairs = self.find_all_program_pairs()
        
        print(f"📊 发现 {len(pairs)} 个程序对需要转换")
        print()
        
        successful_conversions = 0
        failed_conversions = 0
        
        for i, (newv_path, oldv_path) in enumerate(pairs, 1):
            print(f"[{i}/{len(pairs)}] ", end="")
            
            try:
                result = self.convert_program_pair(newv_path, oldv_path)
                if result[0] is not None:
                    successful_conversions += 1
                else:
                    failed_conversions += 1
            except Exception as e:
                print(f"❌ 转换失败: {e}")
                failed_conversions += 1
            print()
        
        print("=" * 60)
        print("🎯 转换完成统计:")
        print(f"  成功转换: {successful_conversions} 个程序对")
        print(f"  转换失败: {failed_conversions} 个程序对")
        print(f"  成功率: {successful_conversions/len(pairs)*100:.1f}%")
        
        return successful_conversions, failed_conversions
    
    def compile_symbolic_programs(self):
        """编译符号化程序"""
        print("🔨 开始编译符号化程序...")
        
        symbolic_files = glob.glob(str(self.base_dir / "benchmarks" / "**" / "symbolic_*.c"), recursive=True)
        
        successful_compilations = 0
        failed_compilations = 0
        compilation_errors = []
        
        for i, c_file in enumerate(symbolic_files, 1):
            if i <= 5 or i % 10 == 0:                  
                print(f"[{i}/{len(symbolic_files)}] 编译: {os.path.relpath(c_file, self.base_dir)}")
            elif i == 6:
                print(f"  ... (省略输出，继续编译中)")
            
                               
            executable = c_file[:-2]
            
                         
            compile_cmd = f"gcc -o '{executable}' '{c_file}' -lm"
            
            try:
                result = os.system(f"{compile_cmd} 2>/dev/null")
                if result == 0:
                    successful_compilations += 1
                    if i <= 5:
                        print(f"  ✅ 编译成功")
                else:
                    failed_compilations += 1
                    compilation_errors.append(os.path.relpath(c_file, self.base_dir))
                    if i <= 5:
                        print(f"  ❌ 编译失败 (返回码: {result})")
            except Exception as e:
                failed_compilations += 1
                compilation_errors.append(f"{os.path.relpath(c_file, self.base_dir)} - 异常: {e}")
                if i <= 5:
                    print(f"  ❌ 编译异常: {e}")
        
        print(f"\n📊 编译统计:")
        print(f"  成功编译: {successful_compilations}")
        print(f"  编译失败: {failed_compilations}")
        print(f"  成功率: {successful_compilations/len(symbolic_files)*100:.1f}%")
        
        if compilation_errors:
            print(f"\n❌ 编译失败的文件:")
            for error in compilation_errors[:10]:             
                print(f"  - {error}")
            if len(compilation_errors) > 10:
                print(f"  ... 还有 {len(compilation_errors) - 10} 个文件编译失败")
        
        return successful_compilations, failed_compilations

def main():
    """主函数"""
    print("🔧 启动正确的符号化转换器（整数参数版本）...")
    
    converter = CorrectSymbolicConverter()
    
          
    success_conv, fail_conv = converter.convert_all_programs()
    
    if success_conv > 0:
        print(f"\n🔨 开始编译转换后的程序...")
        success_comp, fail_comp = converter.compile_symbolic_programs()
    
    print(f"\n✅ 符号化转换和编译完成!")
    print(f"📄 现在可以重新运行符号执行和等价性分析")

if __name__ == "__main__":
    main() 