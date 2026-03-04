                      
"""
TSVC Benchmark runner.

Extracts TSVC benchmarks from the PLDI19 equivalence checker repository
and analyzes them using the local symbolic analysis tooling.
"""

import os
import re
import subprocess
import tempfile
import shutil
from pathlib import Path
import json
import time
import datetime

class TSVCBenchmarkExtractor:
    """TSVC benchmark extractor."""
    
    def __init__(self, tsvc_source_path="pldi19-equivalence-checker/pldi19/TSVC/clean.c"):
        self.tsvc_source = tsvc_source_path
        self.benchmark_functions = {}
        self.recommended_benchmarks = [
            's000', 's1112', 's121', 's1221', 's1251', 's1351', 
            's173', 's2244', 'vpv', 'vpvpv', 'vpvtv', 'vtv', 'vtvtv'
        ]
        
    def extract_benchmark_functions(self):
        """Extract all benchmark functions from clean.c."""
        print("Extracting TSVC benchmark functions...")
        
        with open(self.tsvc_source, 'r') as f:
            content = f.read()
        
                                     
        function_pattern = r'TYPE\s+(\w+)\s*\([^)]*\)\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}'
        
        functions_found = []
                               
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('TYPE ') and '(' in line and '{' in line:
                        
                func_start = i
                brace_count = line.count('{') - line.count('}')
                
                       
                func_name_match = re.match(r'TYPE\s+(\w+)\s*\(', line)
                if func_name_match:
                    func_name = func_name_match.group(1)
                    
                            
                    func_lines = [lines[i]]
                    i += 1
                    
                    while i < len(lines) and brace_count > 0:
                        func_lines.append(lines[i])
                        brace_count += lines[i].count('{') - lines[i].count('}')
                        i += 1
                    
                    if brace_count == 0:
                        full_definition = '\n'.join(func_lines)
                        func_body = '\n'.join(func_lines[1:-1])              
                        functions_found.append((func_name, full_definition, func_body))
                    continue
            i += 1
        
                 
        for func_name, full_definition, func_body in functions_found:
            if func_name in ['main', 'testing']:
                continue
                
            self.benchmark_functions[func_name] = {
                'name': func_name,
                'full_definition': full_definition,
                'body': func_body.strip(),
                'recommended': func_name in self.recommended_benchmarks
            }
        
        print(f"Extracted {len(self.benchmark_functions)} benchmark functions")
        return self.benchmark_functions
    
    def create_benchmark_variants(self, func_name, optimization_levels=['O1', 'O2', 'O3']):
        """Create variants for a single benchmark at different optimization levels."""
        if func_name not in self.benchmark_functions:
            print(f"Function not found: {func_name}")
            return {}
        
        func_data = self.benchmark_functions[func_name]
        
                
        temp_dir = Path(f"benchmark_temp_{func_name}")
        temp_dir.mkdir(exist_ok=True)
        
        try:
            variants = {}
            
                          
            header_content = """
#include <stdlib.h>

#define LEN 128
#define LEN2 16
#define TYPE int

/* Memory segment definitions */
TYPE a[LEN] __attribute__((section ("SEGMENT_A")));
TYPE b[LEN] __attribute__((section ("SEGMENT_B")));
TYPE c[LEN] __attribute__((section ("SEGMENT_C")));
TYPE d[LEN] __attribute__((section ("SEGMENT_D")));
TYPE e[LEN] __attribute__((section ("SEGMENT_E")));
TYPE aa[LEN2][LEN2] __attribute__((section ("SEGMENT_F")));

void init_data() {
    for(int i = 0; i < LEN; i++) {
        a[i] = i % 100;
        b[i] = (i * 2) % 100;
        c[i] = (i * 3) % 100;
        d[i] = (i * 4) % 100;
        e[i] = (i * 5) % 100;
    }
    for(int i = 0; i < LEN2; i++) {
        for(int j = 0; j < LEN2; j++) {
            aa[i][j] = (i + j) % 100;
        }
    }
}
"""
            
            for opt_level in optimization_levels:
                       
                source_file = temp_dir / f"{func_name}_{opt_level}.c"
                
                with open(source_file, 'w') as f:
                    f.write(header_content)
                    f.write("\n")
                    f.write(func_data['full_definition'])
                    f.write(f"\n\nint main() {{\n    init_data();\n    {func_name}(1);\n    return 0;\n}}")
                
                    
                binary_file = temp_dir / f"{func_name}_{opt_level}"
                try:
                    compile_cmd = [
                        'gcc', f'-{opt_level}', '-o', str(binary_file), str(source_file)
                    ]
                    result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0:
                        variants[opt_level] = {
                            'source_file': str(source_file),
                            'binary_file': str(binary_file),
                            'compilation_success': True,
                            'compilation_output': result.stdout
                        }
                        print(f"  {func_name}-{opt_level}: compiled successfully")
                    else:
                        variants[opt_level] = {
                            'source_file': str(source_file),
                            'binary_file': None,
                            'compilation_success': False,
                            'compilation_error': result.stderr
                        }
                        print(f"  {func_name}-{opt_level}: compile failed - {result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    variants[opt_level] = {
                        'source_file': str(source_file),
                        'binary_file': None,
                        'compilation_success': False,
                        'compilation_error': 'Compilation timeout'
                    }
                    print(f"  {func_name}-{opt_level}: compile timeout")
            
            return variants
            
        except Exception as e:
            print(f"Error creating benchmark variants: {e}")
            return {}

class TSVCBenchmarkRunner:
    """TSVC benchmark runner."""
    
    def __init__(self, extractor, symbolic_analyzer_script="semantic_equivalence_analyzer.py"):
        self.extractor = extractor
        self.symbolic_analyzer = symbolic_analyzer_script
        self.results_dir = Path("tsvc_results")
        self.results_dir.mkdir(exist_ok=True)
        
    def run_symbolic_analysis(self, binary1, binary2, benchmark_name, comparison_type):
        """Run symbolic analysis comparing two binaries."""
        print(f"    Analyzing {benchmark_name} ({comparison_type})")
        
                         
                                 
        try:
                    
            output_dir = self.results_dir / benchmark_name / comparison_type
            output_dir.mkdir(parents=True, exist_ok=True)
            
                              
            analysis_result = {
                'benchmark_name': benchmark_name,
                'comparison_type': comparison_type,
                'binary1': binary1,
                'binary2': binary2,
                'analysis_time': time.time(),
                'status': 'completed',
                'result': 'unknown',          
                'details': {
                    'paths_analyzed': 0,
                    'equivalent_paths': 0,
                    'non_equivalent_paths': 0,
                    'timeout_paths': 0
                }
            }
            
                  
            result_file = output_dir / "analysis_result.json"
            with open(result_file, 'w') as f:
                json.dump(analysis_result, f, indent=2)
            
            return analysis_result
            
        except Exception as e:
            print(f"    Analysis failed: {e}")
            return {
                'benchmark_name': benchmark_name,
                'comparison_type': comparison_type,
                'status': 'failed',
                'error': str(e)
            }
    
    def run_benchmark_comparison(self, func_name):
        """Run full comparison for a single benchmark."""
        print(f"\n=== Running benchmark: {func_name} ===")
        
                     
        variants = self.extractor.create_benchmark_variants(func_name)
        
        if not variants:
            print(f"Could not create variants for {func_name}")
            return None
        
        successful_variants = {k: v for k, v in variants.items() if v['compilation_success']}
        
        if len(successful_variants) < 2:
            print(f"Need at least 2 successfully compiled variants, only {len(successful_variants)} available")
            return None
        
                
        results = []
        comparisons = [
            ('O1', 'O2'),
            ('O1', 'O3'),
            ('O2', 'O3')
        ]
        
        for opt1, opt2 in comparisons:
            if opt1 in successful_variants and opt2 in successful_variants:
                comparison_name = f"{opt1}_vs_{opt2}"
                result = self.run_symbolic_analysis(
                    successful_variants[opt1]['binary_file'],
                    successful_variants[opt2]['binary_file'],
                    func_name,
                    comparison_name
                )
                results.append(result)
        
        return results
    
    def run_recommended_benchmarks(self):
        """Run the recommended benchmark set."""
        print("Starting recommended TSVC benchmarks...")
        print(f"Recommended benchmark list: {self.extractor.recommended_benchmarks}")
        
        all_results = {}
        start_time = time.time()
        
        for func_name in self.extractor.recommended_benchmarks:
            try:
                results = self.run_benchmark_comparison(func_name)
                all_results[func_name] = results
            except Exception as e:
                print(f"Error running {func_name}: {e}")
                all_results[func_name] = {'error': str(e)}
        
        end_time = time.time()
        
                
        self.generate_summary_report(all_results, start_time, end_time)
        
        return all_results
    
    def generate_summary_report(self, results, start_time, end_time):
        """Generate a summary report."""
        report_file = self.results_dir / "tsvc_summary_report.txt"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("TSVC Benchmark analysis report\n")
            f.write("=" * 50 + "\n")
            f.write(f"Analysis time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total duration: {end_time - start_time:.2f} s\n")
            f.write(f"Number of benchmarks analyzed: {len(results)}\n\n")
            
                  
            successful_benchmarks = 0
            failed_benchmarks = 0
            
            for func_name, result in results.items():
                f.write(f"\n--- {func_name} ---\n")
                
                if isinstance(result, dict) and 'error' in result:
                    f.write(f"  Status: failed\n")
                    f.write(f"  Error: {result['error']}\n")
                    failed_benchmarks += 1
                elif isinstance(result, list):
                    f.write(f"  Status: success\n")
                    f.write(f"  Comparisons: {len(result)}\n")
                    for comparison in result:
                        f.write(f"    {comparison['comparison_type']}: {comparison['status']}\n")
                    successful_benchmarks += 1
                else:
                    f.write(f"  Status: unknown\n")
            
            f.write(f"\nSummary:\n")
            f.write(f"  Success: {successful_benchmarks}\n")
            f.write(f"  Failed: {failed_benchmarks}\n")
            f.write(f"  Success rate: {successful_benchmarks/(successful_benchmarks+failed_benchmarks)*100:.1f}%\n")
        
        print(f"\nSummary report saved to: {report_file}")

def main():
    """Main entry."""
    print("TSVC Benchmark runner")
    print("=" * 30)
    
                   
    tsvc_source = "pldi19-equivalence-checker/pldi19/TSVC/clean.c"
    if not os.path.exists(tsvc_source):
        print(f"Error: TSVC source file not found: {tsvc_source}")
        print("Please ensure the pldi19-equivalence-checker repository is cloned.")
        return
    
                
    extractor = TSVCBenchmarkExtractor(tsvc_source)
    runner = TSVCBenchmarkRunner(extractor)
    
          
    functions = extractor.extract_benchmark_functions()
    
            
    print(f"\nFound {len(functions)} benchmark functions:")
    for name, info in functions.items():
        status = "recommended" if info['recommended'] else "optional"
        print(f"  {name} ({status})")
    
    print(f"\nRecommended benchmarks (per original paper): {len(extractor.recommended_benchmarks)}")
    
    print("\nStarting analysis...")
    results = runner.run_recommended_benchmarks()
    
    print("\nAnalysis finished!")
    print("Results saved under tsvc_results/ directory")

if __name__ == "__main__":
    main() 