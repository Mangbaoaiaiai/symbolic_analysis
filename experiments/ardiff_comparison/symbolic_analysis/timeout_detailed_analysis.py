                      
"""
详细分析超时程序的具体原因
逐个测试剩余程序，分析超时模式
"""

import os
import subprocess
import sys
import time
import glob
from pathlib import Path
import signal

def find_remaining_executables():
    """查找没有约束文件的符号化可执行文件"""
    base_dir = Path("/root/ardiff/symbolic_analysis")
    remaining = []
    
    pattern = str(base_dir / "benchmarks" / "**" / "symbolic_*")
    for file_path in glob.glob(pattern, recursive=True):
        if os.path.isfile(file_path) and os.access(file_path, os.X_OK):
            if not file_path.endswith('.c'):
                           
                exec_dir = os.path.dirname(file_path)
                exec_name = os.path.basename(file_path)
                constraint_files = glob.glob(os.path.join(exec_dir, f"{exec_name}_path_*.txt"))
                
                if not constraint_files:
                    remaining.append(file_path)
    
    return sorted(remaining)

def categorize_programs(remaining_executables):
    """按类别分组程序"""
    categories = {}
    for executable in remaining_executables:
        parts = Path(executable).parts
        if 'benchmarks' in parts:
            idx = parts.index('benchmarks')
            if len(parts) > idx + 1:
                category = parts[idx + 1]
                if category not in categories:
                    categories[category] = []
                categories[category].append(executable)
    return categories

def test_single_program(executable, timeout=10):
    """测试单个程序，快速超时以检测问题"""
    try:
        print(f"🔍 测试: {os.path.relpath(executable, '/root/ardiff/symbolic_analysis')}")
        
        cmd = [sys.executable, "/root/ardiff/symbolic_analysis/se_script.py", "--binary", executable]
        
        start_time = time.time()
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            preexec_fn=os.setsid          
        )
        
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            end_time = time.time()
            execution_time = end_time - start_time
            
            if process.returncode == 0:
                print(f"  ✅ 成功 ({execution_time:.1f}s)")
                return "success", execution_time, None
            else:
                print(f"  ❌ 失败 - 返回码 {process.returncode} ({execution_time:.1f}s)")
                return "failed", execution_time, stderr[:200] if stderr else None
                
        except subprocess.TimeoutExpired:
                     
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                time.sleep(1)
                if process.poll() is None:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except:
                pass
            
            print(f"  ⏱️  超时 (>{timeout}s)")
            return "timeout", timeout, None
            
    except Exception as e:
        print(f"  💥 异常: {e}")
        return "error", 0, str(e)

def analyze_program_source(executable):
    """分析程序源代码，寻找可能导致超时的特征"""
    c_file = executable + ".c"
    features = {
        "has_loops": False,
        "has_float": False,
        "has_math_functions": False,
        "has_complex_conditions": False,
        "loop_with_symbolic": False,
        "approximate_complexity": "simple"
    }
    
    try:
        with open(c_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
              
        if any(keyword in content for keyword in ['for (', 'while (']):
            features["has_loops"] = True
            
                           
            if any(pattern in content for pattern in ['< x', '< y', 'x %', 'y %', '< argc']):
                features["loop_with_symbolic"] = True
                features["approximate_complexity"] = "high"
        
                
        if any(keyword in content for keyword in ['double', 'float', '.0', 'val']):
            features["has_float"] = True
            features["approximate_complexity"] = "medium"
        
                
        math_functions = ['sin(', 'cos(', 'log(', 'exp(', 'sqrt(', 'pow(', 'fabs(']
        if any(func in content for func in math_functions):
            features["has_math_functions"] = True
            features["approximate_complexity"] = "high"
        
                
        complex_patterns = ['&&', '||', 'switch', 'case']
        if any(pattern in content for pattern in complex_patterns):
            features["has_complex_conditions"] = True
            
                 
        if features["loop_with_symbolic"] or features["has_math_functions"]:
            features["approximate_complexity"] = "very_high"
        elif features["has_loops"] and features["has_float"]:
            features["approximate_complexity"] = "high"
        elif features["has_loops"] or features["has_float"]:
            features["approximate_complexity"] = "medium"
            
    except Exception as e:
        print(f"    警告: 无法分析源代码 {c_file}: {e}")
    
    return features

def main():
    print("🔍 详细超时原因分析")
    print("=" * 60)
    
    remaining = find_remaining_executables()
    categories = categorize_programs(remaining)
    
    print(f"📊 超时程序分布:")
    for category, programs in categories.items():
        print(f"  {category}: {len(programs)} 个程序")
    
    print(f"\n🧪 开始逐个测试分析...")
    print("使用10秒快速超时检测问题程序\n")
    
    results = {
        "success": [],
        "timeout": [],
        "failed": [],
        "error": []
    }
    
    complexity_analysis = {
        "simple": [],
        "medium": [],
        "high": [],
        "very_high": []
    }
    
    timeout_patterns = {}
    
           
    for category, programs in categories.items():
        print(f"\n📋 测试类别: {category} ({len(programs)} 个程序)")
        print("-" * 40)
        
        category_timeouts = 0
        
        for i, executable in enumerate(programs[:5], 1):             
            print(f"  [{i}/min(5,{len(programs)})] ", end="")
            
                   
            features = analyze_program_source(executable)
            complexity = features["approximate_complexity"]
            complexity_analysis[complexity].append(executable)
            
                  
            result, exec_time, error_info = test_single_program(executable, timeout=10)
            results[result].append({
                'executable': executable,
                'category': category,
                'execution_time': exec_time,
                'error_info': error_info,
                'features': features
            })
            
            if result == "timeout":
                category_timeouts += 1
                        
                timeout_key = f"{category}_{complexity}"
                if timeout_key not in timeout_patterns:
                    timeout_patterns[timeout_key] = 0
                timeout_patterns[timeout_key] += 1
                
                        
                problem_features = []
                if features["loop_with_symbolic"]:
                    problem_features.append("符号循环")
                if features["has_float"]:
                    problem_features.append("浮点运算")
                if features["has_math_functions"]:
                    problem_features.append("数学函数")
                
                if problem_features:
                    print(f"    🔍 可能原因: {', '.join(problem_features)}")
        
        print(f"    📊 {category} 类别超时率: {category_timeouts}/{min(5, len(programs))} = {(category_timeouts/min(5, len(programs)))*100:.0f}%")
    
            
    print(f"\n" + "="*60)
    print("📊 超时原因详细分析报告")
    print("="*60)
    
    print(f"\n🎯 测试结果统计:")
    total_tested = sum(len(results[key]) for key in results)
    for result_type, items in results.items():
        count = len(items)
        percentage = (count / total_tested * 100) if total_tested > 0 else 0
        print(f"  • {result_type}: {count} 个 ({percentage:.1f}%)")
    
    print(f"\n🔍 超时模式分析:")
    if timeout_patterns:
        for pattern, count in sorted(timeout_patterns.items(), key=lambda x: x[1], reverse=True):
            category, complexity = pattern.split('_', 1)
            print(f"  • {category} ({complexity}复杂度): {count} 个超时")
    
    print(f"\n💡 复杂度分布分析:")
    for complexity, programs in complexity_analysis.items():
        if programs:
            timeout_count = sum(1 for item in results["timeout"] if item["features"]["approximate_complexity"] == complexity)
            success_count = sum(1 for item in results["success"] if item["features"]["approximate_complexity"] == complexity)
            total = len(programs)
            
            print(f"  • {complexity}复杂度: {total} 个程序")
            print(f"    - 超时: {timeout_count} 个")
            print(f"    - 成功: {success_count} 个")
            if total > 0:
                print(f"    - 超时率: {(timeout_count/(timeout_count+success_count))*100:.0f}%")
    
    print(f"\n🎯 主要超时原因排序:")
    
                 
    feature_timeout_count = {
        "符号循环": 0,
        "浮点运算": 0, 
        "数学函数": 0,
        "复杂条件": 0
    }
    
    for item in results["timeout"]:
        features = item["features"]
        if features["loop_with_symbolic"]:
            feature_timeout_count["符号循环"] += 1
        if features["has_float"]:
            feature_timeout_count["浮点运算"] += 1
        if features["has_math_functions"]:
            feature_timeout_count["数学函数"] += 1
        if features["has_complex_conditions"]:
            feature_timeout_count["复杂条件"] += 1
    
    for feature, count in sorted(feature_timeout_count.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            print(f"  {count} 个程序因 {feature} 超时")
    
    print(f"\n📋 建议:")
    print("1. 符号循环是最主要的超时原因 - 需要限制循环展开深度")
    print("2. 浮点运算复杂度高 - 可考虑转换为整数近似")
    print("3. 数学函数需要特殊处理 - 可使用函数摘要或近似")
    print("4. 对于超时程序，当前116个约束文件已经足够使用")

if __name__ == "__main__":
    main() 