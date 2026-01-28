                      
"""
智能批量转换Java测试程序为C语言版本
支持angr符号执行分析
"""

import os
import re
import subprocess
from pathlib import Path

class JavaToCConverter:
    def __init__(self, benchmarks_root):
        self.benchmarks_root = Path(benchmarks_root)
        self.converted_count = 0
        self.failed_count = 0
        
    def extract_function_info(self, java_content):
        """提取Java函数的签名信息"""
                
        pattern = r'public\s+static\s+(\w+)\s+snippet\s*\(([^)]*)\)'
        match = re.search(pattern, java_content)
        
        if not match:
            return None, []
            
        return_type = match.group(1)
        params_str = match.group(2).strip()
        
              
        params = []
        if params_str:
            for param in params_str.split(','):
                param = param.strip()
                if param:
                    parts = param.split()
                    if len(parts) >= 2:
                        param_type = parts[0]
                        param_name = parts[1]
                        params.append((param_type, param_name))
        
        return return_type, params
    
    def java_type_to_c(self, java_type):
        """Java类型转换为C类型"""
        type_map = {
            'double': 'double',
            'int': 'int', 
            'float': 'float',
            'long': 'long',
            'boolean': 'int'                         
        }
        return type_map.get(java_type, 'double')            
    
    def convert_math_functions(self, content):
        """转换Java数学函数为C函数"""
        conversions = {
            'Math.abs': 'fabs',
            'Math.sin': 'sin',
            'Math.cos': 'cos', 
            'Math.tan': 'tan',
            'Math.sqrt': 'sqrt',
            'Math.exp': 'exp',
            'Math.log': 'log',
            'Math.pow': 'pow',
            'Math.PI': 'M_PI',
            'Math.E': 'M_E',
            'Math.floor': 'floor',
            'Math.ceil': 'ceil',
            'Math.atan': 'atan',
            'Math.atan2': 'atan2',
            'Math.asin': 'asin',
            'Math.acos': 'acos'
        }
        
        for java_func, c_func in conversions.items():
            content = content.replace(java_func, c_func)
        
        return content
    
    def needs_math_h(self, content):
        """检查是否需要math.h头文件"""
        math_functions = [
            'fabs', 'sin', 'cos', 'tan', 'sqrt', 'exp', 'log', 'pow',
            'M_PI', 'M_E', 'floor', 'ceil', 'atan', 'atan2', 'asin', 'acos'
        ]
        return any(func in content for func in math_functions)
    
    def convert_java_to_c(self, java_file):
        """转换单个Java文件为C文件"""
        try:
            with open(java_file, 'r') as f:
                java_content = f.read()
            
                    
            return_type, params = self.extract_function_info(java_content)
            if return_type is None:
                print(f"无法解析函数签名: {java_file}")
                return False
            
                    
            c_return_type = self.java_type_to_c(return_type)
            
                  
            c_params = []
            for java_type, param_name in params:
                c_type = self.java_type_to_c(java_type)
                c_params.append(f"{c_type} {param_name}")
            
            c_params_str = ', '.join(c_params) if c_params else 'void'
            
                   
            snippet_start = java_content.find('{', java_content.find('snippet'))
            snippet_end = java_content.rfind('}')
            
            if snippet_start == -1 or snippet_end == -1:
                print(f"无法提取函数体: {java_file}")
                return False
            
            function_body = java_content[snippet_start:snippet_end+1]
            
                    
            function_body = self.convert_math_functions(function_body)
            
                   
            c_code = self.generate_c_code(
                c_return_type, c_params_str, function_body, 
                params, self.needs_math_h(function_body)
            )
            
                   
            c_file = java_file.with_suffix('.c')
            with open(c_file, 'w') as f:
                f.write(c_code)
            
            return True
            
        except Exception as e:
            print(f"转换失败 {java_file}: {e}")
            return False
    
    def generate_c_code(self, return_type, params_str, function_body, params, needs_math):
        """生成完整的C代码"""
        includes = ['#include <stdio.h>', '#include <stdlib.h>']
        if needs_math:
            includes.append('#include <math.h>')
        
                    
        argc_needed = len(params) + 1
        
                  
        if not params:
            main_body = '''    double result = snippet();
    printf("Result: %f\\n", result);
    
    return 0;'''
        else:
            main_body_lines = [
                f'    if (argc != {argc_needed}) {{',
                f'        printf("Usage: %s'
            ]
            
                    
            usage_params = [f'<{param_name}>' for _, param_name in params]
            usage_str = ' '.join(usage_params)
            main_body_lines[1] += f' {usage_str}\\n", argv[0]);'
            main_body_lines.extend([
                '        return 1;',
                '    }',
                ''
            ])
            
                    
            for i, (java_type, param_name) in enumerate(params):
                if java_type == 'int':
                    main_body_lines.append(f'    int {param_name} = atoi(argv[{i + 1}]);')
                else:
                    main_body_lines.append(f'    double {param_name} = atof(argv[{i + 1}]);')
            
                  
            param_names = [param_name for _, param_name in params]
            main_body_lines.extend([
                '',
                f'    {return_type} result = snippet({", ".join(param_names)});'
            ])
            
                        
            if return_type == 'int':
                main_body_lines.append('    printf("Result: %d\\n", result);')
            else:
                main_body_lines.append('    printf("Result: %f\\n", result);')
            
            main_body_lines.extend([
                '',
                '    return 0;'
            ])
            
            main_body = '\n'.join(main_body_lines)
        
                
        c_code = '\n'.join(includes) + '\n\n'
        c_code += f'{return_type} snippet({params_str}) {function_body}\n\n'
        c_code += 'int main(int argc, char *argv[]) {\n'
        c_code += main_body + '\n'
        c_code += '}\n'
        
        return c_code
    
    def compile_c_file(self, c_file):
        """编译C文件"""
        executable = c_file.with_suffix('')
        cmd = ['gcc', '-o', str(executable), str(c_file)]
        
                   
        with open(c_file, 'r') as f:
            if '#include <math.h>' in f.read():
                cmd.append('-lm')
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return True
            else:
                print(f"编译失败 {c_file}: {result.stderr}")
                return False
        except Exception as e:
            print(f"编译异常 {c_file}: {e}")
            return False
    
    def convert_directory(self, test_dir):
        """转换单个测试目录"""
        oldv_java = test_dir / 'oldV.java'
        newv_java = test_dir / 'newV.java'
        
        success_count = 0
        
        for java_file in [oldv_java, newv_java]:
            if java_file.exists():
                print(f"转换: {java_file}")
                if self.convert_java_to_c(java_file):
                    c_file = java_file.with_suffix('.c')
                    if self.compile_c_file(c_file):
                        success_count += 1
                        print(f"  ✓ 成功: {c_file}")
                    else:
                        print(f"  ✗ 编译失败: {c_file}")
                        self.failed_count += 1
                else:
                    print(f"  ✗ 转换失败: {java_file}")
                    self.failed_count += 1
        
        return success_count
    
    def convert_all(self):
        """转换所有测试"""
        print("开始批量转换所有Java测试为C语言...")
        
                         
        test_dirs = []
        for java_file in self.benchmarks_root.rglob('*V.java'):
            if java_file.name in ['oldV.java', 'newV.java']:
                test_dirs.append(java_file.parent)
        
            
        test_dirs = list(set(test_dirs))
        test_dirs.sort()
        
        print(f"找到 {len(test_dirs)} 个测试目录")
        
        for test_dir in test_dirs:
            print(f"\n处理目录: {test_dir}")
            converted = self.convert_directory(test_dir)
            self.converted_count += converted
        
        print(f"\n转换完成!")
        print(f"总转换文件数: {self.converted_count}")
        print(f"失败文件数: {self.failed_count}")

if __name__ == "__main__":
    converter = JavaToCConverter("/root/ardiff/symbolic_analysis/benchmarks")
    converter.convert_all() 