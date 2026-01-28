                      
"""
创建适合符号执行的C程序版本
修改原始程序，使用符号化输入而不是命令行参数
"""

import os
import re
import glob

class SymbolicVersionCreator:
    """符号化版本创建器"""
    
    def __init__(self, benchmark_dir="benchmarks"):
        self.benchmark_dir = benchmark_dir
        self.converted_count = 0
        self.failed_count = 0
    
    def find_all_c_files(self):
        """查找所有C源文件"""
        c_files = []
        for root, dirs, files in os.walk(self.benchmark_dir):
            for file in files:
                if file.endswith('.c') and file in ['oldV.c', 'newV.c']:
                    c_files.append(os.path.join(root, file))
        return sorted(c_files)
    
    def analyze_c_file(self, c_file_path):
        """分析C文件的参数结构"""
        with open(c_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
                     
        main_match = re.search(r'int\s+main\s*\(\s*int\s+argc\s*,\s*char\s*\*\s*argv\[\]\s*\)', content)
        if not main_match:
            return None, None
        
                  
        argc_check = re.search(r'if\s*\(\s*argc\s*[!<>=]+\s*(\d+)', content)
        if argc_check:
            expected_argc = int(argc_check.group(1))
            param_count = expected_argc - 1         
        else:
                        
            atof_calls = re.findall(r'atof\s*\(\s*argv\[(\d+)\]', content)
            if atof_calls:
                param_count = max(int(x) for x in atof_calls)
            else:
                param_count = 2          
        
                     
        snippet_match = re.search(r'(\w+)\s+snippet\s*\([^)]*\)\s*\{', content)
        if snippet_match:
            return_type = snippet_match.group(1)
        else:
            return_type = 'double'      
        
        return param_count, return_type
    
    def create_symbolic_version(self, original_file):
        """创建符号化版本"""
        print(f"处理: {original_file}")
        
        try:
                  
            param_count, return_type = self.analyze_c_file(original_file)
            if param_count is None:
                print(f"  ❌ 无法分析参数结构")
                self.failed_count += 1
                return False
            
            print(f"  检测到 {param_count} 个参数，返回类型: {return_type}")
            
                    
            with open(original_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
                     
            symbolic_content = self.generate_symbolic_c_code(content, param_count, return_type)
            
                     
            base_name = os.path.basename(original_file)
            dir_name = os.path.dirname(original_file)
            symbolic_file = os.path.join(dir_name, f"symbolic_{base_name}")
            
            with open(symbolic_file, 'w', encoding='utf-8') as f:
                f.write(symbolic_content)
            
            print(f"  ✅ 已生成: {symbolic_file}")
            self.converted_count += 1
            return True
            
        except Exception as e:
            print(f"  ❌ 转换失败: {e}")
            self.failed_count += 1
            return False
    
    def generate_symbolic_c_code(self, original_content, param_count, return_type):
        """生成符号化的C代码"""
        
                     
        snippet_match = re.search(r'(\w+\s+snippet\s*\([^}]*\})', original_content, re.DOTALL)
        if not snippet_match:
            raise ValueError("找不到snippet函数")
        
        snippet_function = snippet_match.group(1)
        
                 
        c_code = '''#include <stdio.h>
#include <stdlib.h>
#include <math.h>

'''
        
                     
        c_code += snippet_function + '\n\n'
        
                      
        c_code += 'int main() {\n'
        c_code += '    // 符号化输入 - angr会自动处理这些scanf调用\n'
        
                
        if param_count == 1:
            c_code += '    double x;\n'
            c_code += '    scanf("%lf", &x);\n'
            c_code += f'    {return_type} result = snippet(x);\n'
        elif param_count == 2:
            c_code += '    double a, b;\n'
            c_code += '    scanf("%lf %lf", &a, &b);\n'
            c_code += f'    {return_type} result = snippet(a, b);\n'
        elif param_count == 3:
            c_code += '    double x, y, z;\n'
            c_code += '    scanf("%lf %lf %lf", &x, &y, &z);\n'
            c_code += f'    {return_type} result = snippet(x, y, z);\n'
        else:
                       
            var_names = []
            for i in range(param_count):
                var_name = f'arg{i+1}'
                var_names.append(var_name)
            
            c_code += f'    double {", ".join(var_names)};\n'
            
                          
            format_str = ' '.join(['%lf'] * param_count)
            scanf_args = ', '.join([f'&{var}' for var in var_names])
            c_code += f'    scanf("{format_str}", {scanf_args});\n'
            c_code += f'    {return_type} result = snippet({", ".join(var_names)});\n'
        
              
        if return_type == 'int':
            c_code += '    printf("Result: %d\\n", result);\n'
        else:
            c_code += '    printf("Result: %f\\n", (double)result);\n'
        
        c_code += '    return 0;\n'
        c_code += '}\n'
        
        return c_code
    
    def compile_symbolic_versions(self):
        """编译所有符号化版本"""
        print("\n编译符号化版本...")
        
        symbolic_files = []
        for root, dirs, files in os.walk(self.benchmark_dir):
            for file in files:
                if file.startswith('symbolic_') and file.endswith('.c'):
                    symbolic_files.append(os.path.join(root, file))
        
        compiled_count = 0
        failed_compile_count = 0
        
        for c_file in symbolic_files:
            executable = c_file[:-2]          
            compile_cmd = f"gcc -o {executable} {c_file} -lm"
            
            if os.system(compile_cmd) == 0:
                print(f"  ✅ 编译成功: {executable}")
                compiled_count += 1
            else:
                print(f"  ❌ 编译失败: {c_file}")
                failed_compile_count += 1
        
        print(f"\n编译统计: 成功 {compiled_count}, 失败 {failed_compile_count}")
        return compiled_count, failed_compile_count
    
    def run_conversion(self):
        """运行完整的转换过程"""
        print("🔄 开始创建符号化版本...")
        
        c_files = self.find_all_c_files()
        print(f"发现 {len(c_files)} 个C文件")
        
        for c_file in c_files:
            self.create_symbolic_version(c_file)
        
        print(f"\n转换统计: 成功 {self.converted_count}, 失败 {self.failed_count}")
        
                 
        if self.converted_count > 0:
            compiled, failed_compile = self.compile_symbolic_versions()
            
            print(f"\n🎉 转换和编译完成!")
            print(f"  转换成功: {self.converted_count}")
            print(f"  编译成功: {compiled}")
            print(f"  总失败数: {self.failed_count + failed_compile}")
            
            return compiled
        else:
            print("❌ 没有成功转换任何文件")
            return 0

def main():
    """主函数"""
    creator = SymbolicVersionCreator()
    return creator.run_conversion()

if __name__ == "__main__":
    compiled_count = main()
    print(f"\n符号化版本已准备就绪，共 {compiled_count} 个可执行文件")
    print("现在可以使用原始的se_script.py进行符号执行分析") 