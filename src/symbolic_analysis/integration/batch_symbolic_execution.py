                      
"""
Batch symbolic-execution script.

Uses the enhanced ``se_script.py`` to run symbolic execution over all benchmarks.

Features:
1. Automatically discover all ``benchmark_temp_*`` directories
2. Run symbolic execution on every binary found in each directory
3. Record detailed timing information
4. Generate a comprehensive analysis report
"""

import os
import sys
import glob
import time
import datetime
import subprocess
import json
from pathlib import Path
import argparse

class BatchSymbolicExecutor:
    """Manager for batched symbolic-execution runs."""
    
    def __init__(self, root_dir=".", timeout=60, se_script="se_script.py"):
        self.root_dir = root_dir
        self.timeout = timeout
        self.se_script = se_script
        self.results = {}
        self.total_start_time = None
        self.total_end_time = None
        self.failed_analyses = []
        self.successful_analyses = []
        
    def find_benchmark_directories(self):
        """Find all benchmark directories under the root directory."""
        pattern = os.path.join(self.root_dir, "benchmark_temp_*")
        benchmark_dirs = glob.glob(pattern)
        benchmark_dirs = [d for d in benchmark_dirs if os.path.isdir(d)]
        return sorted(benchmark_dirs)
    
    def find_binary_files(self, benchmark_dir):
        """Find candidate binary files within a benchmark directory."""
                       
        patterns = [
            "*_O0", "*_O1", "*_O2", "*_O3",
            "*_Ofast", "*_Os", "*_Oz"
        ]
        
        binary_files = []
        for pattern in patterns:
            matches = glob.glob(os.path.join(benchmark_dir, pattern))
                            
            matches = [f for f in matches if not f.endswith(('.c', '.h', '.txt', '.md'))]
            binary_files.extend(matches)
        
                  
        executable_files = []
        for file_path in binary_files:
            if os.access(file_path, os.X_OK) or self.is_binary_file(file_path):
                executable_files.append(file_path)
                
        return sorted(executable_files)
    
    def is_binary_file(self, file_path):
        """Heuristically check whether a file is a binary (non-text) file."""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                             
                if chunk.startswith(b'\x7fELF'):
                    return True
                              
                text_ratio = sum(1 for byte in chunk if 32 <= byte <= 126) / len(chunk)
                return text_ratio < 0.7
        except:
            return False
    
    def run_symbolic_execution(self, binary_path, output_dir=None):
        """Run symbolic execution on a single binary."""
        binary_name = os.path.basename(binary_path)
        print(f"  Analyzing: {binary_name}")
        
        start_time = time.time()
        
        try:
                           
            abs_binary_path = os.path.abspath(binary_path)
            abs_se_script = os.path.abspath(self.se_script)
            
            cmd = [
                "python", abs_se_script,
                "--binary", abs_binary_path,
                "--timeout", str(self.timeout)
            ]
            
            print(f"    Command: {' '.join(cmd)}")
            
                                             
            result = subprocess.run(
                cmd,
                cwd=os.getcwd(),            
                capture_output=True,
                text=True,
                timeout=self.timeout + 30             
            )
            
            end_time = time.time()
            execution_time = end_time - start_time
            
                  
            stdout_lines = result.stdout.split('\n')
            stderr_lines = result.stderr.split('\n')
            
                    
            paths_found = 0
            exploration_time = 0
            setup_time = 0
            analysis_time = 0
            
            for line in stdout_lines:
                if "Analysis complete! Found" in line and "paths" in line:
                    try:
                        # Expect format like: "Analysis complete! Found N paths"
                        parts = line.split("Found", 1)[1].split("paths", 1)[0]
                        paths_found = int(parts.strip())
                    except Exception:
                        pass
                elif "Path exploration:" in line and "seconds" in line:
                    try:
                        exploration_time = float(line.split("Path exploration:")[1].split("seconds")[0].strip())
                    except Exception:
                        pass
                elif "Setup:" in line and "seconds" in line:
                    try:
                        setup_time = float(line.split("Setup:")[1].split("seconds")[0].strip())
                    except Exception:
                        pass
                elif "State analysis:" in line and "seconds" in line:
                    try:
                        analysis_time = float(line.split("State analysis:")[1].split("seconds")[0].strip())
                    except Exception:
                        pass
            
            analysis_result = {
                'binary_path': binary_path,
                'binary_name': binary_name,
                'success': result.returncode == 0,
                'execution_time': execution_time,
                'paths_found': paths_found,
                'setup_time': setup_time,
                'exploration_time': exploration_time,
                'analysis_time': analysis_time,
                'return_code': result.returncode,
                'stdout_lines': len(stdout_lines),
                'stderr_lines': len(stderr_lines),
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            if result.returncode == 0:
                print(f"    ✅ Success: found {paths_found} paths (time: {execution_time:.1f}s)")
                self.successful_analyses.append(analysis_result)
            else:
                print(f"    ❌ Failed: return code {result.returncode} (time: {execution_time:.1f}s)")
                analysis_result['error_output'] = result.stderr[:500]
                self.failed_analyses.append(analysis_result)
            
            return analysis_result
            
        except subprocess.TimeoutExpired:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"    ⏰ Timeout: {execution_time:.1f}s")
            
            timeout_result = {
                'binary_path': binary_path,
                'binary_name': binary_name,
                'success': False,
                'execution_time': execution_time,
                'paths_found': 0,
                'return_code': -1,
                'error': 'timeout',
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.failed_analyses.append(timeout_result)
            return timeout_result
            
        except Exception as e:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"    💥 Exception: {str(e)} (time: {execution_time:.1f}s)")
            
            exception_result = {
                'binary_path': binary_path,
                'binary_name': binary_name,
                'success': False,
                'execution_time': execution_time,
                'paths_found': 0,
                'return_code': -2,
                'error': str(e),
                'timestamp': datetime.datetime.now().isoformat()
            }
            self.failed_analyses.append(exception_result)
            return exception_result
    
    def analyze_benchmark(self, benchmark_dir):
        """Analyze all binaries under a single benchmark directory."""
        benchmark_name = os.path.basename(benchmark_dir)
        print(f"\n📁 Analyzing benchmark: {benchmark_name}")
        print("=" * 60)
        
                 
        binary_files = self.find_binary_files(benchmark_dir)
        
        if not binary_files:
            print(f"  ⚠️  No binary files found")
            return []
        
        print(f"  Found {len(binary_files)} binary files:")
        for binary in binary_files:
            print(f"    - {os.path.basename(binary)}")
        
                   
        benchmark_results = []
        for binary_path in binary_files:
            result = self.run_symbolic_execution(binary_path)
            benchmark_results.append(result)
        
        self.results[benchmark_name] = benchmark_results
        return benchmark_results
    
    def preview_analysis(self):
        """Preview which files will be analyzed, without executing them."""
        print("🔍 Preview mode - scanning binaries to be analyzed")
        print("=" * 60)
        
                           
        benchmark_dirs = self.find_benchmark_directories()
        
        if not benchmark_dirs:
            print("❌ No benchmark directories found")
            return
        
        print(f"📋 Found {len(benchmark_dirs)} benchmark directories:")
        
        total_files = 0
        total_estimated_time = 0
        
        for i, benchmark_dir in enumerate(benchmark_dirs, 1):
            benchmark_name = os.path.basename(benchmark_dir)
            print(f"\n{i}. 📁 {benchmark_name}")
            
                     
            binary_files = self.find_binary_files(benchmark_dir)
            
            if not binary_files:
                print(f"    ⚠️  No binary files found")
                continue
            
            print(f"    Found {len(binary_files)} binary files:")
            for binary in binary_files:
                binary_name = os.path.basename(binary)
                file_size = os.path.getsize(binary)
                print(f"      - {binary_name} ({file_size/1024:.1f} KB)")
            
            total_files += len(binary_files)
                            
            estimated_time = len(binary_files) * 30
            total_estimated_time += estimated_time
            print(f"    Estimated analysis time: {estimated_time/60:.1f} minutes")
        
        print(f"\n📊 Overall preview:")
        print(f"  Total benchmarks: {len(benchmark_dirs)}")
        print(f"  Total binaries: {total_files}")
        print(f"  Estimated total time: {total_estimated_time/60:.1f} minutes ({total_estimated_time/3600:.1f} hours)")
        print(f"  Timeout setting: {self.timeout} seconds/file")
        print(f"  Symbolic-execution script: {self.se_script}")
        
        print(f"\n💡 To start the actual analysis, run:")
        print(f"   python batch_symbolic_execution.py --timeout {self.timeout}")
        
        if total_estimated_time > 3600:
            print(f"\n⚠️  Long estimated time; consider running in the background:")
            print(f"   nohup python batch_symbolic_execution.py --timeout {self.timeout} > batch_analysis.log 2>&1 &")
    
    def run_batch_analysis(self):
        """Run the full batch symbolic-execution analysis."""
        print("🚀 Starting batch symbolic-execution analysis")
        print("=" * 60)
        
        self.total_start_time = time.time()
        start_datetime = datetime.datetime.now()
        print(f"Start time: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
                           
        benchmark_dirs = self.find_benchmark_directories()
        
        if not benchmark_dirs:
            print("❌ No benchmark directories found")
            return
        
        print(f"📋 Found {len(benchmark_dirs)} benchmark directories:")
        for i, benchmark_dir in enumerate(benchmark_dirs, 1):
            print(f"  {i}. {os.path.basename(benchmark_dir)}")
        
        for i, benchmark_dir in enumerate(benchmark_dirs, 1):
            print(f"\n🔄 Progress: {i}/{len(benchmark_dirs)}")
            self.analyze_benchmark(benchmark_dir)
        
        self.total_end_time = time.time()
        total_time = self.total_end_time - self.total_start_time
        end_datetime = datetime.datetime.now()
        
        print(f"\n🎉 Batch symbolic-execution analysis complete!")
        print(f"Total time: {total_time:.1f} s ({total_time/60:.1f} min)")
        print(f"End time: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        
              
        self.generate_comprehensive_report()
    
    def generate_comprehensive_report(self):
        """Generate a comprehensive report for batch symbolic execution."""
        report_file = "batch_symbolic_execution_report.txt"
        
        total_time = self.total_end_time - self.total_start_time if self.total_end_time else 0
        successful_count = len(self.successful_analyses)
        failed_count = len(self.failed_analyses)
        total_count = successful_count + failed_count
        
              
        total_paths = sum(result['paths_found'] for result in self.successful_analyses)
        total_exploration_time = sum(result.get('exploration_time', 0) for result in self.successful_analyses)
        total_setup_time = sum(result.get('setup_time', 0) for result in self.successful_analyses)
        total_analysis_time = sum(result.get('analysis_time', 0) for result in self.successful_analyses)
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("Batch symbolic-execution analysis report\n")
            f.write("=" * 60 + "\n\n")
            
                  
            f.write("📊 Overall statistics:\n")
            f.write("-" * 30 + "\n")
            f.write(f"Start time: {datetime.datetime.fromtimestamp(self.total_start_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"End time:   {datetime.datetime.fromtimestamp(self.total_end_time).strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total time: {total_time:.1f} s ({total_time/60:.1f} min)\n")
            f.write(f"Benchmarks analyzed: {len(self.results)}\n")
            f.write(f"Binaries analyzed: {total_count}\n")
            f.write(f"Successful analyses: {successful_count}\n")
            f.write(f"Failed analyses: {failed_count}\n")
            f.write(f"Success rate: {successful_count/total_count*100:.1f}%\n")
            f.write(f"Total paths found: {total_paths}\n")
            if successful_count > 0:
                f.write(f"Average paths per binary: {total_paths/successful_count:.1f}\n")
            f.write(f"Total exploration time: {total_exploration_time:.1f} s\n")
            f.write(f"Total setup time: {total_setup_time:.1f} s\n")
            f.write(f"Total analysis time: {total_analysis_time:.1f} s\n")
            if total_exploration_time > 0:
                f.write(f"Overall exploration throughput: {total_paths/total_exploration_time:.2f} paths/s\n")
            f.write("\n")
            
                          
            f.write("📋 Per-benchmark analysis details:\n")
            f.write("-" * 50 + "\n")
            
            for benchmark_name, results in self.results.items():
                f.write(f"\n🔹 {benchmark_name}:\n")
                f.write(f"  Binary count: {len(results)}\n")
                
                successful_in_benchmark = [r for r in results if r['success']]
                failed_in_benchmark = [r for r in results if not r['success']]
                
                f.write(f"  Successful: {len(successful_in_benchmark)}\n")
                f.write(f"  Failed: {len(failed_in_benchmark)}\n")
                
                if successful_in_benchmark:
                    benchmark_paths = sum(r['paths_found'] for r in successful_in_benchmark)
                    benchmark_time = sum(r['execution_time'] for r in successful_in_benchmark)
                    f.write(f"  Total paths: {benchmark_paths}\n")
                    f.write(f"  Total time: {benchmark_time:.1f} s\n")
                    f.write(f"  Average time: {benchmark_time/len(successful_in_benchmark):.1f} s/binary\n")
                
                      
                for result in results:
                    status = "✅" if result['success'] else "❌"
                    f.write(f"    {status} {result['binary_name']}: ")
                    if result['success']:
                        f.write(f"{result['paths_found']} paths, {result['execution_time']:.1f}s\n")
                    else:
                        error_type = result.get('error', f"return code {result['return_code']}")
                        f.write(f"Failed ({error_type}), {result['execution_time']:.1f}s\n")
            
                    
            if self.failed_analyses:
                f.write(f"\n❌ Failed-analysis summary:\n")
                f.write("-" * 30 + "\n")
                
                error_types = {}
                for failure in self.failed_analyses:
                    error_type = failure.get('error', f"return code {failure['return_code']}")
                    if error_type not in error_types:
                        error_types[error_type] = []
                    error_types[error_type].append(failure)
                
                for error_type, failures in error_types.items():
                    f.write(f"  {error_type}: {len(failures)} files\n")
                    for failure in failures[:3]:
                        f.write(f"    - {failure['binary_name']}\n")
                    if len(failures) > 3:
                        f.write(f"    - ... and {len(failures)-3} more\n")
            
                  
            if successful_count >= 3:
                f.write(f"\n🏆 Performance ranking:\n")
                f.write("-" * 30 + "\n")
                
                top_paths = sorted(self.successful_analyses, key=lambda x: x['paths_found'], reverse=True)[:5]
                f.write("Top-5 binaries by path count:\n")
                for i, result in enumerate(top_paths, 1):
                    f.write(f"  {i}. {result['binary_name']}: {result['paths_found']} paths\n")
                
                speed_analyses = [r for r in self.successful_analyses if r.get('exploration_time', 0) > 0]
                if speed_analyses:
                    top_speed = sorted(
                        speed_analyses,
                        key=lambda x: x['paths_found']/max(x.get('exploration_time', 1), 0.1),
                        reverse=True
                    )[:5]
                    f.write("\nTop-5 binaries by exploration throughput:\n")
                    for i, result in enumerate(top_speed, 1):
                        efficiency = result['paths_found']/max(result.get('exploration_time', 1), 0.1)
                        f.write(f"  {i}. {result['binary_name']}: {efficiency:.2f} paths/s\n")
        
        print(f"📄 Comprehensive report written to: {report_file}")
        
                     
        json_file = "batch_symbolic_execution_data.json"
        detailed_data = {
            'summary': {
                'start_time': self.total_start_time,
                'end_time': self.total_end_time,
                'total_time': total_time,
                'successful_count': successful_count,
                'failed_count': failed_count,
                'total_paths': total_paths
            },
            'results': self.results,
            'successful_analyses': self.successful_analyses,
            'failed_analyses': self.failed_analyses
        }
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(detailed_data, f, indent=2, ensure_ascii=False)
        
        print(f"📊 Detailed batch data written to: {json_file}")

def main():
    """CLI entry point for the batch symbolic-execution tool."""
    parser = argparse.ArgumentParser(description='Batch symbolic-execution analysis tool')
    parser.add_argument('--root-dir', default='.', help='Root directory containing benchmark_temp_* subdirectories')
    parser.add_argument('--timeout', type=int, default=60, help='Timeout per symbolic-execution run (seconds)')
    parser.add_argument('--se-script', default='se_script.py', help='Path to symbolic-execution script')
    parser.add_argument('--benchmarks', nargs='*', help='Restrict analysis to specific benchmark names')
    parser.add_argument('--dry-run', action='store_true', help='Preview mode: list planned binaries without executing')
    
    args = parser.parse_args()
    
                     
    if not args.dry_run and not os.path.exists(args.se_script):
        print(f"❌ Symbolic-execution script not found: {args.se_script}")
        sys.exit(1)
    
             
    executor = BatchSymbolicExecutor(
        root_dir=args.root_dir,
        timeout=args.timeout,
        se_script=args.se_script
    )
    
    if args.benchmarks:
        print(f"🎯 Target benchmarks: {', '.join(args.benchmarks)}")
    
    if args.dry_run:
        executor.preview_analysis()
    else:
        executor.run_batch_analysis()

if __name__ == "__main__":
    main() 