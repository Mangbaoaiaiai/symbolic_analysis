                      
"""
Benchmark source fixer script.

Batch-modify benchmark sources: replace fixed inputs with scanf so that
symbolic execution analysis can run effectively.
"""

import os
import re
import glob
from pathlib import Path

class BenchmarkSourceFixer:
    """Benchmark source fixer."""
    
    def __init__(self):
        self.fixed_count = 0
        self.total_count = 0
        
    def find_all_benchmark_directories(self):
        """Find all benchmark directories."""
        benchmark_dirs = []
        pattern = "benchmark_temp_*"
        
        for dir_path in glob.glob(pattern):
            if os.path.isdir(dir_path):
                benchmark_dirs.append(dir_path)
        
        return sorted(benchmark_dirs)
    
    def find_c_files_in_directory(self, directory):
        """Find all C source files in a directory."""
        c_files = []
        pattern = os.path.join(directory, "*.c")
        
        for file_path in glob.glob(pattern):
            c_files.append(file_path)
        
        return sorted(c_files)
    
    def analyze_source_file(self, file_path):
        """Analyze source file and determine required changes."""
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
        """Extract function name from file path."""
        basename = os.path.basename(file_path)
                               
        match = re.match(r'(\w+)_O[0-3]\.c', basename)
        if match:
            return match.group(1)
        return None
    
    def fix_source_file(self, file_path):
        """Fix a single source file."""
        print(f"Fixing: {file_path}")
        
        analysis = self.analyze_source_file(file_path)
        content = analysis['content']
        
        if analysis['has_scanf']:
            print(f"  ✓ Already has scanf, skipping")
            return False
        
        if not analysis['has_stdio']:
            content = content.replace(
                '#include <stdlib.h>',
                '#include <stdlib.h>\n#include <stdio.h>  // for scanf'
            )
            print(f"  + Added stdio.h")
        
        function_name = self.extract_function_name_from_filename(file_path)
        if not function_name:
            print(f"  ❌ Could not extract function name")
            return False
        
        new_main = self.create_new_main_function(function_name, content)
        if new_main:
            main_pattern = r'int main\(\)[^{]*\{[^}]*\}'
            content = re.sub(main_pattern, new_main, content, flags=re.DOTALL)
            print(f"  + Modified main to use scanf")
        else:
            print(f"  ❌ Could not modify main")
            return False
        
        with open(file_path, 'w') as f:
            f.write(content)
        
        print(f"  ✅ Fix complete")
        return True
    
    def create_new_main_function(self, function_name, content):
        """Create new main function."""
                          
        main_match = re.search(r'int main\(\)[^{]*\{([^}]*)\}', content, re.DOTALL)
        if not main_match:
            return None
        
        main_body = main_match.group(1)
        
                  
        function_call_pattern = rf'{function_name}\(([^)]+)\)'
        match = re.search(function_call_pattern, main_body)
        
        if match:
            new_main = f'''int main() {{
    int count;
    printf("Enter count: ");
    scanf("%d", &count);
    
    init_data();
    {function_name}(count);
    return 0;
}}'''
        else:
            new_main = f'''int main() {{
    int count;
    printf("Enter count: ");
    scanf("%d", &count);
    
    init_data();
    {function_name}(count);
    return 0;
}}'''
        
        return new_main
    
    def fix_benchmark_directory(self, directory):
        """Fix all files in a benchmark directory."""
        print(f"\n📁 Fixing directory: {directory}")
        
        c_files = self.find_c_files_in_directory(directory)
        if not c_files:
            print(f"  ❌ No C files found in directory")
            return 0
        
        fixed_files = 0
        for c_file in c_files:
            self.total_count += 1
            if self.fix_source_file(c_file):
                fixed_files += 1
                self.fixed_count += 1
        
        print(f"  📊 Fixed {fixed_files}/{len(c_files)} files")
        return fixed_files
    
    def recompile_directory_binaries(self, directory):
        """Recompile binaries in directory."""
        print(f"\n🔨 Recompiling: {directory}")
        
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
                
                print(f"  Compile: {compile_cmd}")
                result = os.system(compile_cmd + " 2>/dev/null")
                
                if result == 0:
                    compiled_count += 1
                    print(f"    ✅ Compiled: {output_name}")
                else:
                    print(f"    ❌ Compile failed: {output_name}")
        
        print(f"  📊 Compiled {compiled_count}/{len(c_files)} binaries")
        return compiled_count
    
    def run_batch_fix(self):
        """Run batch fix."""
        print("🚀 Starting batch fix of benchmark sources")
        print("=" * 60)
        
        benchmark_dirs = self.find_all_benchmark_directories()
        
        if not benchmark_dirs:
            print("❌ No benchmark directories found")
            return
        
        print(f"📋 Found {len(benchmark_dirs)} benchmark directories:")
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
        print("🎯 Batch fix complete!")
        print(f"📊 Fixed {self.fixed_count}/{self.total_count} source files")
        print(f"🔨 Compiled {total_compiled_files} binaries")
        
        if self.fixed_count > 0:
            print("\n💡 Suggestions:")
            print("  1. Remove old path files: rm -f benchmark_temp_*/s*_O*_path_*.txt")  
            print("  2. Re-run symbolic execution tests to verify")
            print("  3. Check that generated constraints include symbolic variables")

def main():
    """Main entry."""
    fixer = BenchmarkSourceFixer()
    fixer.run_batch_fix()

if __name__ == "__main__":
    main() 