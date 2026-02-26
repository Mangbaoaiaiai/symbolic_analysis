                      
"""
Automatically create all TSVC benchmark folders.

Generates O1, O2, O3 variants of all recommended benchmarks from pldi19 TSVC clean.c.
"""

import os
import re
import subprocess
import shutil
from pathlib import Path

class TSVCBenchmarkGenerator:
    def __init__(self, tsvc_source="../pldi19-equivalence-checker/pldi19/TSVC/clean.c"):
        self.tsvc_source = tsvc_source
        self.recommended_benchmarks = [
            's000', 's1112', 's121', 's1221', 's1251', 's1351', 
            's173', 's2244', 'vpv', 'vpvpv', 'vpvtv', 'vtv', 'vtvtv'
        ]
        self.optimization_levels = ['O1', 'O2', 'O3']
        
              
        self.c_template = """
#include <stdlib.h>
#include <stdio.h>  /* for scanf */

#define LEN 128
#define LEN2 16
#define TYPE int

/* Memory segments */
TYPE a[LEN] __attribute__((section ("SEGMENT_A")));
TYPE b[LEN] __attribute__((section ("SEGMENT_B")));
TYPE c[LEN] __attribute__((section ("SEGMENT_C")));
TYPE d[LEN] __attribute__((section ("SEGMENT_D")));
TYPE e[LEN] __attribute__((section ("SEGMENT_E")));
TYPE aa[LEN2][LEN2] __attribute__((section ("SEGMENT_F")));

void init_data() {{
    for(int i = 0; i < LEN; i++) {{
        a[i] = i % 100;
        b[i] = (i * 2) % 100;
        c[i] = (i * 3) % 100;
        d[i] = (i * 4) % 100;
        e[i] = (i * 5) % 100;
    }}
    for(int i = 0; i < LEN2; i++) {{
        for(int j = 0; j < LEN2; j++) {{
            aa[i][j] = (i + j) % 100;
        }}
    }}
}}

{function_definition}

int main() {{
    int count;
    printf("Please enter count parameter: ");
    scanf("%d", &count);
    
    init_data();
    {function_name}(count);
    return 0;
}}
"""

    def read_tsvc_source(self):
        """Read TSVC source code."""
        with open(self.tsvc_source, 'r') as f:
            return f.read()
    
    def extract_function_definition(self, content, function_name):
        """Extract the given function definition from source."""
        pattern = rf'TYPE\s+{function_name}\s*\([^)]*\)\s*\{{'
        match = re.search(pattern, content)
        if not match:
            print(f"Warning: function {function_name} not found")
            return None
        
        start_pos = match.start()
        lines = content[start_pos:].split('\n')
        
                          
        brace_count = 0
        function_lines = []
        
        for line in lines:
            function_lines.append(line)
            brace_count += line.count('{') - line.count('}')
            if brace_count == 0:
                break
        
        return '\n'.join(function_lines)
    
    def create_benchmark_folder(self, function_name, function_definition):
        """Create benchmark folder for the given function."""
        folder_name = f"benchmark_temp_{function_name}"
        folder_path = Path(".") / folder_name
        folder_path.mkdir(exist_ok=True, parents=True)
        print(f"Creating folder: {folder_path}")
        for opt_level in self.optimization_levels:
            source_file = folder_path / f"{function_name}_{opt_level}.c"
            c_code = self.c_template.format(
                function_definition=function_definition,
                function_name=function_name
            )
            with open(source_file, 'w') as f:
                f.write(c_code)
            print(f"  Created source: {source_file}")
            
                       
            binary_file = folder_path / f"{function_name}_{opt_level}"
            self.compile_source(source_file, binary_file, opt_level)
    
    def compile_source(self, source_file, binary_file, opt_level):
        """Compile source to executable."""
        try:
            cmd = [
                'gcc',
                f'-{opt_level}',
                '-o', str(binary_file),
                str(source_file)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"    Compiled: {binary_file}")
            else:
                print(f"    Compilation failed: {binary_file}")
                print(f"    Error: {result.stderr}")
        except Exception as e:
            print(f"    Compilation error: {e}")
    
    def generate_all_benchmarks(self):
        """Generate all recommended benchmarks."""
        print("Generating all TSVC benchmark folders...")
        print(f"Recommended benchmarks: {self.recommended_benchmarks}")
        content = self.read_tsvc_source()
        for func_name in self.recommended_benchmarks:
            print(f"\nProcessing benchmark: {func_name}")
            func_def = self.extract_function_definition(content, func_name)
            if func_def:
                self.create_benchmark_folder(func_name, func_def)
            else:
                print(f"Skipping {func_name}: could not extract function definition")
        print("\nAll benchmarks generated.")
    
    def list_existing_benchmarks(self):
        """List existing benchmark folders."""
        symbolic_path = Path(".")
        existing = []
        
        for item in symbolic_path.iterdir():
            if item.is_dir() and item.name.startswith("benchmark_temp_"):
                existing.append(item.name)
        
        return existing

def main():
    print("TSVC Benchmark folder generator")
    print("=" * 50)
    generator = TSVCBenchmarkGenerator()
    existing = generator.list_existing_benchmarks()
    if existing:
        print(f"Existing benchmark folders: {existing}")
    generator.generate_all_benchmarks()
    final = generator.list_existing_benchmarks()
    print(f"\nTotal benchmark folders: {len(final)}")
    print(f"Folders: {final}")

if __name__ == "__main__":
    main() 