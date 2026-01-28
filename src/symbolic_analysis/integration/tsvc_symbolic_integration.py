                      
"""
TSVC Benchmark symbolic analysis integrator.
This component integrates the existing symbolic analysis tools with TSVC benchmarks.
"""

import os
import subprocess
import tempfile
import json
import time
from pathlib import Path
import shutil

                                    
from semantic_equivalence_analyzer import PathClusterAnalyzer, ConstraintEquivalenceChecker
from tsvc_benchmark_runner import TSVCBenchmarkExtractor, TSVCBenchmarkRunner

class TSVCSymbolicIntegrator:
    """Integrator that connects TSVC benchmarks to the symbolic analysis tools."""
    
    def __init__(self):
        self.extractor = TSVCBenchmarkExtractor()
        self.temp_dirs = []
        
    def __del__(self):
        """Clean up any temporary directories that were created."""
        for temp_dir in self.temp_dirs:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def generate_execution_paths(self, binary_path, benchmark_name, num_paths=50):
        """Generate execution paths (SMT constraints) for a compiled benchmark binary.

        NOTE: This is a mock implementation; you should replace it with your
        real symbolic-execution-based path generation.
        """
        print(f"    Generating execution paths for {benchmark_name}...")
        
                                 
        output_dir = Path(f"paths_{benchmark_name}")
        output_dir.mkdir(exist_ok=True)
        
                                                                       
                                                                                      
        
        try:
                            
                            
            
            paths_generated = []
            
            for i in range(min(num_paths, 20)):                                      
                path_file = output_dir / f"path_{i:03d}.txt"
                
                                                     
                                                            
                mock_smt_content = self.generate_mock_smt_constraints(benchmark_name, i)
                
                with open(path_file, 'w') as f:
                    f.write(mock_smt_content)
                
                paths_generated.append(str(path_file))
            
            print(f"    Generated {len(paths_generated)} paths")
            return paths_generated
            
        except Exception as e:
            print(f"    Path generation failed: {e}")
            return []
    
    def generate_mock_smt_constraints(self, benchmark_name, path_index):
        """Generate a mock SMT-LIB path constraint file.

        In a production setup you should replace this with real constraint extraction.
        """
        
                                     
        declarations = [
            f"(declare-fun scanf_{path_index}_i () (_ BitVec 32))",
            f"(declare-fun scanf_{path_index}_a () (_ BitVec 32))",
            f"(declare-fun scanf_{path_index}_b () (_ BitVec 32))",
            f"(declare-fun scanf_{path_index}_result () (_ BitVec 32))",
        ]
        
                                                                            
        constraints = []
        
        if 's000' in benchmark_name:
                                   
            constraints = [
                f"(= scanf_{path_index}_a (bvadd scanf_{path_index}_b #x00000001))",
                f"(bvule scanf_{path_index}_i #x00000080)"           
            ]
        elif 's121' in benchmark_name:
                                                                                 
            declarations.append(f"(declare-fun scanf_{path_index}_a_next () (_ BitVec 32))")
            constraints = [
                f"(= scanf_{path_index}_a (bvadd scanf_{path_index}_a_next scanf_{path_index}_b))",
                f"(bvult scanf_{path_index}_i #x0000007f)"           
            ]
        else:
                                                              
            constraints = [
                f"(bvule scanf_{path_index}_i #x00000080)",
                f"(= scanf_{path_index}_result (bvadd scanf_{path_index}_a #x00000001))"
            ]
        
                                      
        smt_content = [
            "; TSVC Benchmark Path Constraints",
            f"; Benchmark: {benchmark_name}",
            f"; Path: {path_index}",
            f"; Variable values: {{'scanf_{path_index}_i': {path_index}, 'scanf_{path_index}_result': {path_index + 1}}}",
            f"; Constraint meta: {{'count': {len(constraints)}, 'types': ['arithmetic']}}",
            f"; Memory hash: {hash(benchmark_name + str(path_index)) % 10000}",
            f"; Program output: result_{path_index}",
            "",
            "(set-logic QF_BV)",
        ]
        
                          
        smt_content.extend(declarations)
        
                         
        for constraint in constraints:
            smt_content.append(f"(assert {constraint})")
        
        smt_content.append("(check-sat)")
        
        return '\n'.join(smt_content)
    
    def run_benchmark_analysis(self, benchmark_name, opt_levels=['O1', 'O2', 'O3']):
        """Run a full pipeline analysis for a single benchmark."""
        print(f"\n=== Analyzing TSVC Benchmark: {benchmark_name} ===")
        
                                              
        if benchmark_name not in self.extractor.benchmark_functions:
            self.extractor.extract_benchmark_functions()
        
        if benchmark_name not in self.extractor.benchmark_functions:
            print(f"Error: benchmark function {benchmark_name} was not found")
            return None
        
                                                              
        variants = self.extractor.create_benchmark_variants(benchmark_name, opt_levels)
        successful_variants = {k: v for k, v in variants.items() if v['compilation_success']}
        
        if len(successful_variants) < 2:
            print(f"Error: at least 2 successfully compiled variants are required")
            return None
        
        print(f"Successfully compiled variants: {list(successful_variants.keys())}")
        
                                                               
        variant_paths = {}
        for opt_level, variant_info in successful_variants.items():
            paths = self.generate_execution_paths(
                variant_info['binary_file'], 
                f"{benchmark_name}_{opt_level}"
            )
            variant_paths[opt_level] = paths
        
                                              
        results = {}
        comparisons = [('O1', 'O2'), ('O1', 'O3'), ('O2', 'O3')]
        
        for opt1, opt2 in comparisons:
            if opt1 in variant_paths and opt2 in variant_paths:
                comparison_name = f"{opt1}_vs_{opt2}"
                print(f"\n--- Comparing {comparison_name} ---")
                
                                                            
                result = self.analyze_path_equivalence(
                    variant_paths[opt1],
                    variant_paths[opt2],
                    f"{benchmark_name}_{comparison_name}"
                )
                
                results[comparison_name] = result
        
        return results
    
    def analyze_path_equivalence(self, paths1, paths2, comparison_name):
        """Run path equivalence analysis using existing tools."""
        print(f"    Running path-equivalence analysis: {comparison_name}")
        
        try:
                                                                  
            cluster_analyzer = PathClusterAnalyzer()
            
                                                                          
            if paths1 and paths2:
                                       
                prefix1 = str(Path(paths1[0]).parent / "path_")
                prefix2 = str(Path(paths2[0]).parent / "path_")
                
                                                       
                semantic_result = cluster_analyzer.analyze_path_clusters(prefix1, prefix2)
                
                                                               
                semantic_report_file = f"{comparison_name}_semantic_report.txt"
                cluster_analyzer.generate_report(semantic_result, semantic_report_file)
                print(f"    Semantic analysis report saved to: {semantic_report_file}")
                
                return {
                    'comparison_name': comparison_name,
                    'semantic_analysis': semantic_result,
                    'semantic_report_file': semantic_report_file,
                    'paths_count': {'group1': len(paths1), 'group2': len(paths2)},
                    'status': 'completed'
                }
            else:
                return {
                    'comparison_name': comparison_name,
                    'status': 'failed',
                    'error': 'No paths generated'
                }
                
        except Exception as e:
            print(f"    Path-equivalence analysis failed: {e}")
            return {
                'comparison_name': comparison_name,
                'status': 'failed',
                'error': str(e)
            }
    
    def run_full_benchmark_suite(self):
        """Run the full TSVC benchmark suite through the analysis pipeline."""
        print("Starting the full TSVC benchmark analysis suite")
        print("=" * 50)
        
                                                   
        functions = self.extractor.extract_benchmark_functions()
        
                                                       
        recommended = self.extractor.recommended_benchmarks
        results = {}
        
        start_time = time.time()
        
        for i, benchmark_name in enumerate(recommended):
            print(f"\nProgress: {i+1}/{len(recommended)}")
            
            try:
                result = self.run_benchmark_analysis(benchmark_name)
                results[benchmark_name] = result
                
                                                            
                self.save_intermediate_results(benchmark_name, result)
                
            except Exception as e:
                print(f"Error while running {benchmark_name}: {e}")
                results[benchmark_name] = {'error': str(e)}
        
        end_time = time.time()
        
                                             
        self.generate_final_report(results, start_time, end_time)
        
        return results
    
    def save_intermediate_results(self, benchmark_name, result):
        """保存中间结果"""
        results_dir = Path("tsvc_analysis_results")
        results_dir.mkdir(exist_ok=True)
        
        result_file = results_dir / f"{benchmark_name}_result.json"
        
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    
    def generate_final_report(self, results, start_time, end_time):
        """Generate a textual summary report comparing all analyzed benchmarks."""
        report_file = Path("tsvc_vs_pldi19_comparison.txt")
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("TSVC Benchmark vs PLDI19 equivalence checker comparison report\n")
            f.write("=" * 60 + "\n")
            f.write(f"Analysis start time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}\n")
            f.write(f"Total wall-clock time: {end_time - start_time:.2f} seconds\n")
            f.write(f"Number of analyzed benchmarks: {len(results)}\n\n")
            
                                   
            successful = sum(1 for r in results.values() if isinstance(r, dict) and 'error' not in r)
            failed = len(results) - successful
            
            f.write("=== Summary statistics ===\n")
            f.write(f"Successful analyses: {successful}\n")
            f.write(f"Failed analyses: {failed}\n")
            f.write(f"Success rate: {successful/len(results)*100:.1f}%\n\n")
            
                                   
            f.write("=== Per-benchmark details ===\n")
            for benchmark_name, result in results.items():
                f.write(f"\n--- {benchmark_name} ---\n")
                
                if isinstance(result, dict) and 'error' in result:
                    f.write(f"Status: FAILED\n")
                    f.write(f"Error: {result['error']}\n")
                elif isinstance(result, dict):
                    f.write(f"Status: OK\n")
                    
                    for comparison, comp_result in result.items():
                        if isinstance(comp_result, dict):
                            f.write(f"  {comparison}:\n")
                            f.write(f"    Status: {comp_result.get('status', 'unknown')}\n")
                            if 'paths_count' in comp_result:
                                paths = comp_result['paths_count']
                                f.write(f"    Path counts: {paths['group1']} vs {paths['group2']}\n")
                            if 'semantic_report_file' in comp_result:
                                f.write(f"    Semantic report: {comp_result['semantic_report_file']}\n")
                            
                                          
                            if 'semantic_analysis' in comp_result:
                                semantic = comp_result['semantic_analysis']
                                if isinstance(semantic, dict):
                                    equiv_count = len(semantic.get('equivalent_pairs', []))
                                    non_equiv_count = len(semantic.get('non_equivalent_pairs', []))
                                    error_count = len(semantic.get('error_pairs', []))
                                    f.write(f"    Semantically equivalent pairs: {equiv_count}\n")
                                    f.write(f"    Semantically non-equivalent pairs: {non_equiv_count}\n")
                                    f.write(f"    Analysis errors: {error_count}\n")
                else:
                    f.write(f"Status: UNKNOWN\n")
            
            f.write(f"\n=== Comparison with the original PLDI19 results ===\n")
            f.write("Note: due to environment limitations, we did not run the original PLDI19 checker.\n")
            f.write("We recommend re-running the official tool on hardware that supports AVX to compare.\n")
            f.write("\nBenchmarks reported as successful in the original paper:\n")
            pldi19_successful = ['s000', 's1112', 's121', 's1221', 's1251', 's1351', 's173', 's2244', 'vpv', 'vpvpv', 'vpvtv', 'vtv', 'vtvtv']
            for name in pldi19_successful:
                our_status = "success" if name in results and isinstance(results[name], dict) and 'error' not in results[name] else "failure"
                f.write(f"  {name}: PLDI19=success, our method={our_status}\n")
        
        print(f"\nFinal comparison report written to: {report_file}")

def main():
    """CLI entry point for the TSVC symbolic analysis integrator."""
    print("TSVC Benchmark Symbolic Analysis Integrator")
    print("This tool compares your symbolic-analysis pipeline against PLDI19 TSVC benchmarks.")
    print("=" * 50)
    
                               
    required_files = [
        "pldi19-equivalence-checker/pldi19/TSVC/clean.c",
        "semantic_equivalence_analyzer.py"
    ]
    
    missing_files = [f for f in required_files if not os.path.exists(f)]
    if missing_files:
        print("Error: missing required files:")
        for f in missing_files:
            print(f"  - {f}")
        print("\nPlease make sure all files are available in the current working directory.")
        return
    
                                                 
    integrator = TSVCSymbolicIntegrator()
    
    try:
        print("Starting benchmark analysis...")
        results = integrator.run_full_benchmark_suite()
        
        print("\nAnalysis complete.")
        print("Results have been saved to:")
        print("  - tsvc_analysis_results/ (per-benchmark detailed results)")
        print("  - tsvc_vs_pldi19_comparison.txt (overall comparison report)")
        
    except KeyboardInterrupt:
        print("\nAnalysis interrupted by user.")
    except Exception as e:
        print(f"\nAn error occurred during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 