                      
"""
Debug script: analyze path file generation mechanism.
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
    print("❌ angr not installed")
    ANGR_AVAILABLE = False

class DebugPathGenerator:
    """Debug path generation process."""
    
    def __init__(self, tsvc_source="pldi19-equivalence-checker/pldi19/TSVC/clean.c"):
        self.tsvc_source = tsvc_source
        self.temp_dirs = []
        
    def __del__(self):
        """Clean up temporary directories."""
        for temp_dir in self.temp_dirs:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def extract_function_code(self, function_name: str) -> str:
        """Extract a single function from TSVC source."""
        print(f"  Extracting function: {function_name}")
        
        with open(self.tsvc_source, 'r') as f:
            content = f.read()
        
                
        pattern = rf'TYPE\s+{function_name}\s*\([^)]*\)\s*\{{'
        match = re.search(pattern, content)
        
        if not match:
            raise ValueError(f"Function {function_name} not found")
        
                      
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
            raise ValueError(f"Brace mismatch in function {function_name}")
        
        function_code = content[start_pos:i+1]
        return function_code
    
    def create_test_program(self, function_name: str) -> Path:
        """Create test program from extracted function."""
        print(f"  Creating test program: {function_name}")
        
                
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

// Initialization function
void init_arrays() {{
    for (int i = 0; i < LEN; i++) {{
        a[i] = i;
        b[i] = i * 2;
        c[i] = i * 3;
    }}
}}

// Extracted benchmark function
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
        print(f"    Compiled successfully: {binary_file}")
        return binary_file
    
    def debug_angr_exploration(self, binary_path: Path, max_paths: int = 20) -> List[Dict]:
        """Debug angr exploration in detail."""
        if not ANGR_AVAILABLE:
            print("❌ angr not available")
            return []
        
        print(f"🔍 Starting angr exploration debug: {binary_path}")
        
                  
        project = angr.Project(str(binary_path), auto_load_libs=False)
        print(f"  ✅ Created angr project")
        
        state = project.factory.entry_state()
        print(f"  ✅ Created entry state")
        
        count_sym = claripy.BVS('count', 32)
        state.solver.add(count_sym >= 1)
        state.solver.add(count_sym <= 4)
        print(f"  ✅ Added symbolic constraints")
        
        simgr = project.factory.simulation_manager(state)
        print(f"  ✅ Created simulation manager")
        print(f"  📊 Initial state count: active={len(simgr.active)}, found={len(simgr.found)}")
        
        print(f"  🚀 Starting path exploration (max_paths={max_paths})...")
        
                 
        step = 0
        while simgr.active and len(simgr.found) < max_paths and step < 50:
            step += 1
            print(f"    Step {step}: active={len(simgr.active)}, found={len(simgr.found)}, deadended={len(simgr.deadended)}")
            
            simgr.step()
        
        print(f"  🏁 Exploration complete!")
        print(f"    Final state: active={len(simgr.active)}, found={len(simgr.found)}, deadended={len(simgr.deadended)}")
        
        paths = []
        
        print(f"  📋 Processing found states ({len(simgr.found)})...")
        for i, found_state in enumerate(simgr.found[:max_paths]):
            print(f"    Processing found state {i}")
            path_info = self._debug_extract_constraints(found_state, len(paths))
            paths.append(path_info)
        
                    
        print(f"  📋 Processing active states ({len(simgr.active)})...")
        for i, active_state in enumerate(simgr.active[:max_paths-len(paths)]):
            if len(paths) >= max_paths:
                break
            print(f"    Processing active state {i}")
            path_info = self._debug_extract_constraints(active_state, len(paths))
            paths.append(path_info)
        
        print(f"  ✅ Extracted {len(paths)} paths in total")
        return paths
    
    def _debug_extract_constraints(self, state, path_index: int) -> Dict:
        """Debug constraint extraction for a path."""
        print(f"      Extracting constraints for path {path_index}...")
        
        try:
            constraints = state.solver.constraints
            print(f"        Raw constraint count: {len(constraints)}")
            
                          
            smt_constraints = []
            variable_declarations = set()
            
            for j, constraint in enumerate(constraints):
                print(f"        Processing constraint {j}: {str(constraint)[:100]}...")
                
                try:
                    variables = constraint.variables
                    print(f"          Variable count: {len(variables)}")
                    
                    for var in variables:
                        var_name = str(var)
                        if hasattr(var, 'size') and var.size() % 8 == 0:
                            bit_size = var.size()
                            variable_declarations.add(f"(declare-fun {var_name} () (_ BitVec {bit_size}))")
                except Exception as e:
                    print(f"          Variable extraction failed: {e}")
                
                try:
                    smt_constraint = state.solver._solver.converter.convert(constraint)
                    smt_constraints.append(f"(assert {smt_constraint})")
                except Exception as e:
                    print(f"          Constraint conversion failed: {e}")
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
            
            print(f"        ✅ Path {path_index}: {len(variable_declarations)} variables, {len(smt_constraints)} constraints, hash={memory_hash}")
            return path_info
            
        except Exception as e:
            print(f"        ❌ Constraint extraction failed: {e}")
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
    """Run debug session."""
    print("🔍 Starting path generation debug")
    print("=" * 50)
    
    if not ANGR_AVAILABLE:
        print("❌ angr not available, cannot debug")
        return
    
    debugger = DebugPathGenerator()
    
    function_name = 's000'
    try:
        binary_path = debugger.create_test_program(function_name)
        paths = debugger.debug_angr_exploration(binary_path, max_paths=20)
        
        print(f"\n📊 Final result:")
        print(f"   Generated {len(paths)} paths")
        for i, path in enumerate(paths):
            print(f"   Path {i}: {path['variable_count']} variables, {path['constraint_count']} constraints, hash={path['memory_hash']}")
            
    except Exception as e:
        print(f"❌ Debug failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main() 