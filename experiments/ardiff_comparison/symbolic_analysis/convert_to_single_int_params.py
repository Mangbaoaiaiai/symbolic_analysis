                      
"""
转换所有symbolic程序为单参数整数版本
将浮点数改为整数，多参数改为单参数
"""

import os
import glob
import re
from pathlib import Path

class SymbolicProgramConverter:
    def __init__(self, base_dir="/root/ardiff/symbolic_analysis"):
        self.base_dir = Path(base_dir)
        self.converted_count = 0
        self.failed_count = 0
        
    def find_symbolic_c_files(self):
        """查找所有symbolic_*.c文件"""
        pattern = str(self.base_dir / "benchmarks" / "**" / "symbolic_*.c")
        c_files = glob.glob(pattern, recursive=True)
        return sorted(c_files)
    
    def convert_single_file(self, c_file_path):
        """转换单个C文件为单参数整数版本"""
        try:
            with open(c_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
                         
            snippet_match = re.search(r'(int|double)\s+snippet\s*\([^)]+\)\s*\{[^}]*\}', content, re.DOTALL)
            if not snippet_match:
                print(f"❌ 未找到snippet函数: {c_file_path}")
                return False
            
            snippet_func = snippet_match.group(0)
            
                                        
                                    
            new_snippet = re.sub(r'(int|double)\s+snippet\s*\([^)]+\)', 'int snippet(int x)', snippet_func)
            
                                    
            new_snippet = re.sub(r'return\s+([^;]+);', lambda m: f'return (int)({m.group(1)});', new_snippet)
            
                        
            new_main = '''int main() {
    // 符号化输入 - angr会自动处理这些scanf调用
    int x;
    scanf("%d", &x);
    int result = snippet(x);
    printf("Result: %d\\n", result);
    return 0;
}'''
            
                        
            new_content = '''#include <stdio.h>
#include <stdlib.h>
#include <math.h>

''' + new_snippet + '''

''' + new_main
            
                   
            with open(c_file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            print(f"✅ 转换成功: {os.path.relpath(c_file_path, self.base_dir)}")
            return True
            
        except Exception as e:
            print(f"❌ 转换失败: {c_file_path}, 错误: {e}")
            return False
    
    def recompile_all_symbolic_programs(self):
        """重新编译所有symbolic程序"""
        print("\n🔧 开始重新编译所有symbolic程序...")
        
                             
        pattern = str(self.base_dir / "benchmarks" / "**" / "symbolic_*.c")
        c_files = glob.glob(pattern, recursive=True)
        
        compiled_count = 0
        failed_compile_count = 0
        
        for c_file in c_files:
            try:
                                   
                exe_file = c_file[:-2]        
                
                      
                compile_cmd = f"gcc -o {exe_file} {c_file} -lm"
                
                      
                result = os.system(compile_cmd)
                
                if result == 0:
                    compiled_count += 1
                    print(f"✅ 编译成功: {os.path.basename(exe_file)}")
                else:
                    failed_compile_count += 1
                    print(f"❌ 编译失败: {os.path.basename(exe_file)}")
                    
            except Exception as e:
                failed_compile_count += 1
                print(f"❌ 编译异常: {c_file}, 错误: {e}")
        
        print(f"\n📊 编译统计:")
        print(f"  • 编译成功: {compiled_count}")
        print(f"  • 编译失败: {failed_compile_count}")
        
        return compiled_count, failed_compile_count
    
    def run_conversion(self):
        """运行完整的转换流程"""
        print("🚀 开始转换所有symbolic程序为单参数整数版本...")
        
                
        c_files = self.find_symbolic_c_files()
        print(f"📋 找到 {len(c_files)} 个symbolic C文件")
        
        if not c_files:
            print("❌ 没有找到symbolic C文件")
            return
        
              
        for i, c_file in enumerate(c_files, 1):
            print(f"\n[{i}/{len(c_files)}] 转换: {os.path.relpath(c_file, self.base_dir)}")
            if self.convert_single_file(c_file):
                self.converted_count += 1
            else:
                self.failed_count += 1
        
              
        print(f"\n📊 转换统计:")
        print(f"  • 转换成功: {self.converted_count}")
        print(f"  • 转换失败: {self.failed_count}")
        print(f"  • 成功率: {(self.converted_count/len(c_files)*100):.1f}%")
        
              
        if self.converted_count > 0:
            compiled_count, failed_compile_count = self.recompile_all_symbolic_programs()
            
            print(f"\n🎯 最终结果:")
            print(f"  • 转换+编译成功: {compiled_count}")
            print(f"  • 可用于符号执行的程序数: {compiled_count}")
        
        return self.converted_count, self.failed_count

if __name__ == "__main__":
    converter = SymbolicProgramConverter()
    converter.run_conversion() 