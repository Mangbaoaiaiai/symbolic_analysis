                      
"""
Benchmark源代码修复脚本

批量修改所有benchmark源代码，将固定输入改为scanf输入，
使其能够进行有效的符号执行分析
"""

import os
import re
import glob
from pathlib import Path

class BenchmarkSourceFixer:
    """Benchmark源代码修复器"""
    
    def __init__(self):
        self.fixed_count = 0
        self.total_count = 0
        
    def find_all_benchmark_directories(self):
        """查找所有benchmark目录"""
        benchmark_dirs = []
        pattern = "benchmark_temp_*"
        
        for dir_path in glob.glob(pattern):
            if os.path.isdir(dir_path):
                benchmark_dirs.append(dir_path)
        
        return sorted(benchmark_dirs)
    
    def find_c_files_in_directory(self, directory):
        """在目录中查找所有C源代码文件"""
        c_files = []
        pattern = os.path.join(directory, "*.c")
        
        for file_path in glob.glob(pattern):
            c_files.append(file_path)
        
        return sorted(c_files)
    
    def analyze_source_file(self, file_path):
        """分析源文件，确定需要的修改"""
        with open(file_path, 'r') as f:
            content = f.read()
        
                       
        has_scanf = 'scanf(' in content
        has_stdio = '#include <stdio.h>' in content
        
                  
        function_calls = []
        
                    
        patterns = [
            r'(\w+)\((\d+)\)',                             
            r'(\w+)\((\d+),\s*(\d+)\)',                          
            r'(\w+)\(\)',                            
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            function_calls.extend(matches)
        
        return {
            'has_scanf': has_scanf,
            'has_stdio': has_stdio,
            'function_calls': function_calls,
            'content': content
        }
    
    def extract_function_name_from_filename(self, file_path):
        """从文件路径提取函数名"""
        basename = os.path.basename(file_path)
                               
        match = re.match(r'(\w+)_O[0-3]\.c', basename)
        if match:
            return match.group(1)
        return None
    
    def fix_source_file(self, file_path):
        """修复单个源文件"""
        print(f"正在修复: {file_path}")
        
              
        analysis = self.analyze_source_file(file_path)
        content = analysis['content']
        
                       
        if analysis['has_scanf']:
            print(f"  ✓ 已包含scanf，跳过")
            return False
        
                      
        if not analysis['has_stdio']:
            content = content.replace(
                '#include <stdlib.h>',
                '#include <stdlib.h>\n#include <stdio.h>  // 添加stdio.h用于scanf'
            )
            print(f"  + 添加了stdio.h头文件")
        
               
        function_name = self.extract_function_name_from_filename(file_path)
        if not function_name:
            print(f"  ❌ 无法提取函数名")
            return False
        
                  
        new_main = self.create_new_main_function(function_name, content)
        if new_main:
                      
            main_pattern = r'int main\(\)[^{]*\{[^}]*\}'
            content = re.sub(main_pattern, new_main, content, flags=re.DOTALL)
            print(f"  + 修改了main函数以使用scanf")
        else:
            print(f"  ❌ 无法修改main函数")
            return False
        
              
        with open(file_path, 'w') as f:
            f.write(content)
        
        print(f"  ✅ 修复完成")
        return True
    
    def create_new_main_function(self, function_name, content):
        """创建新的main函数"""
                          
        main_match = re.search(r'int main\(\)[^{]*\{([^}]*)\}', content, re.DOTALL)
        if not main_match:
            return None
        
        main_body = main_match.group(1)
        
                  
        function_call_pattern = rf'{function_name}\(([^)]+)\)'
        match = re.search(function_call_pattern, main_body)
        
        if match:
                      
            new_main = f'''int main() {{
    int count;
    printf("请输入count参数: ");
    scanf("%d", &count);
    
    init_data();
    {function_name}(count);
    return 0;
}}'''
        else:
                      
            new_main = f'''int main() {{
    int count;
    printf("请输入count参数: ");
    scanf("%d", &count);
    
    init_data();
    {function_name}(count);
    return 0;
}}'''
        
        return new_main
    
    def fix_benchmark_directory(self, directory):
        """修复一个benchmark目录中的所有文件"""
        print(f"\n📁 修复目录: {directory}")
        
        c_files = self.find_c_files_in_directory(directory)
        if not c_files:
            print(f"  ❌ 目录中没有找到C文件")
            return 0
        
        fixed_files = 0
        for c_file in c_files:
            self.total_count += 1
            if self.fix_source_file(c_file):
                fixed_files += 1
                self.fixed_count += 1
        
        print(f"  📊 修复 {fixed_files}/{len(c_files)} 个文件")
        return fixed_files
    
    def recompile_directory_binaries(self, directory):
        """重新编译目录中的二进制文件"""
        print(f"\n🔨 重新编译: {directory}")
        
        c_files = self.find_c_files_in_directory(directory)
        
        compiled_count = 0
        for c_file in c_files:
                          
            basename = os.path.basename(c_file)
            if basename.endswith('.c'):
                output_name = basename[:-2]           
                
                        
                if '_O0' in basename:
                    opt_level = 'O0'
                elif '_O1' in basename:
                    opt_level = 'O1'
                elif '_O2' in basename:
                    opt_level = 'O2'
                elif '_O3' in basename:
                    opt_level = 'O3'
                else:
                    continue
                
                      
                output_path = os.path.join(directory, output_name)
                compile_cmd = f"cd {directory} && gcc -{opt_level} -o {output_name} {basename}"
                
                print(f"  编译: {compile_cmd}")
                result = os.system(compile_cmd + " 2>/dev/null")
                
                if result == 0:
                    compiled_count += 1
                    print(f"    ✅ 编译成功: {output_name}")
                else:
                    print(f"    ❌ 编译失败: {output_name}")
        
        print(f"  📊 编译 {compiled_count}/{len(c_files)} 个二进制文件")
        return compiled_count
    
    def run_batch_fix(self):
        """运行批量修复"""
        print("🚀 开始批量修复benchmark源代码")
        print("=" * 60)
        
                         
        benchmark_dirs = self.find_all_benchmark_directories()
        
        if not benchmark_dirs:
            print("❌ 没有找到任何benchmark目录")
            return
        
        print(f"📋 找到 {len(benchmark_dirs)} 个benchmark目录:")
        for dir_name in benchmark_dirs:
            print(f"  - {dir_name}")
        
        print("\n" + "=" * 60)
        
                
        total_fixed_files = 0
        total_compiled_files = 0
        
        for directory in benchmark_dirs:
                   
            fixed_files = self.fix_benchmark_directory(directory)
            total_fixed_files += fixed_files
            
                           
            if fixed_files > 0:
                compiled_files = self.recompile_directory_binaries(directory)
                total_compiled_files += compiled_files
        
            
        print("\n" + "=" * 60)
        print("🎯 批量修复完成!")
        print(f"📊 总计修复 {self.fixed_count}/{self.total_count} 个源文件")
        print(f"🔨 总计编译 {total_compiled_files} 个二进制文件")
        
        if self.fixed_count > 0:
            print("\n💡 建议:")
            print("  1. 删除旧的路径文件: rm -f benchmark_temp_*/s*_O*_path_*.txt")  
            print("  2. 重新运行符号执行测试，验证修复效果")
            print("  3. 检查生成的约束是否包含符号变量")

def main():
    """主函数"""
    fixer = BenchmarkSourceFixer()
    fixer.run_batch_fix()

if __name__ == "__main__":
    main() 