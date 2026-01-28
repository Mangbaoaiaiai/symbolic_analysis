                      
"""
增强的批量等价性分析脚本
支持四类判断流程：
1. 路径约束等价且程序输出相同 → 等价
2. 路径约束不等价但程序输出相同 → 疑似不等价（约束）
3. 路径约束等价但程序输出不等价 → 疑似不等价（输出）
4. 路径约束不等价且程序输出不等价 → 不等价

对所有成功生成约束文件的程序进行等价性分析
分别分析Eq（等价）和NEq（不等价）程序对
"""

import os
import glob
import subprocess
import time
from pathlib import Path

class EnhancedBatchEquivalenceAnalyzer:
    def __init__(self, base_dir="/root/ardiff/symbolic_analysis"):
        self.base_dir = Path(base_dir)
        
    def find_program_pairs(self):
        """查找所有有约束文件的程序对"""
                  
        constraint_files = glob.glob(str(self.base_dir / "benchmarks" / "**" / "*_path_*.txt"), recursive=True)
        
                   
        program_dirs = set()
        for cf in constraint_files:
            program_dir = os.path.dirname(cf)
            program_dirs.add(program_dir)
        
        print(f"🔍 发现 {len(program_dirs)} 个有约束文件的程序目录")
        
                      
        eq_pairs = []
        neq_pairs = []
        skipped_dirs = []
        
        for prog_dir in sorted(program_dirs):
                                 
            newv_files = glob.glob(os.path.join(prog_dir, "symbolic_newV_path_*.txt"))
            oldv_files = glob.glob(os.path.join(prog_dir, "symbolic_oldV_path_*.txt"))
            
            if newv_files and oldv_files:
                            
                if "/Eq/" in prog_dir or prog_dir.endswith("/Eq"):
                    eq_pairs.append({
                        'dir': prog_dir,
                        'newV_prefix': os.path.join(prog_dir, "symbolic_newV_path_"),
                        'oldV_prefix': os.path.join(prog_dir, "symbolic_oldV_path_"),
                        'newV_count': len(newv_files),
                        'oldV_count': len(oldv_files)
                    })
                elif "/NEq/" in prog_dir or prog_dir.endswith("/NEq"):
                    neq_pairs.append({
                        'dir': prog_dir,
                        'newV_prefix': os.path.join(prog_dir, "symbolic_newV_path_"),
                        'oldV_prefix': os.path.join(prog_dir, "symbolic_oldV_path_"),
                        'newV_count': len(newv_files),
                        'oldV_count': len(oldv_files)
                    })
                else:
                                       
                    print(f"  🔍 跳过非Eq/NEq目录: {os.path.relpath(prog_dir, self.base_dir)}")
                    skipped_dirs.append(prog_dir)
            else:
                                  
                missing = []
                if not newv_files:
                    missing.append("newV")
                if not oldv_files:
                    missing.append("oldV")
                print(f"  ⚠️  缺少约束文件: {os.path.relpath(prog_dir, self.base_dir)} (缺少: {', '.join(missing)})")
                skipped_dirs.append(prog_dir)
        
        print(f"🎯 分类结果:")
        print(f"  Eq程序对: {len(eq_pairs)}")
        print(f"  NEq程序对: {len(neq_pairs)}")
        print(f"  跳过的目录: {len(skipped_dirs)}")
        
        return eq_pairs, neq_pairs
    
    def parse_enhanced_results(self, output_lines):
        """解析增强版分析结果"""
        result = {
            "equivalent_pairs": 0,
            "suspicious_constraint_pairs": 0,
            "suspicious_output_pairs": 0,
            "non_equivalent_pairs": 0,
            "program_equivalent": False,
            "total_analysis_pairs": 0
        }
        
        for line in output_lines:
            line = line.strip()
            
                    
            if "✅ 等价路径对:" in line:
                try:
                    result["equivalent_pairs"] = int(line.split(":")[1].strip())
                except:
                    pass
            elif "⚠️  疑似不等价-约束:" in line:
                try:
                    result["suspicious_constraint_pairs"] = int(line.split(":")[1].strip())
                except:
                    pass
            elif "⚠️  疑似不等价-输出:" in line:
                try:
                    result["suspicious_output_pairs"] = int(line.split(":")[1].strip())
                except:
                    pass
            elif "❌ 不等价路径对:" in line:
                try:
                    result["non_equivalent_pairs"] = int(line.split(":")[1].strip())
                except:
                    pass
            elif "程序等价性:" in line:
                result["program_equivalent"] = "✅ 等价" in line
            elif "总分析路径对:" in line:
                try:
                    result["total_analysis_pairs"] = int(line.split(":")[1].strip())
                except:
                    pass
        
        return result
    
    def run_equivalence_analysis(self, program_dir, program_type):
        """对单个程序对运行增强版等价性分析"""
                
        newv_prefix = os.path.join(program_dir, "symbolic_newV_path_")
        oldv_prefix = os.path.join(program_dir, "symbolic_oldV_path_")
        
              
        output_file = os.path.join(program_dir, f"equivalence_analysis_{program_type}.txt")
        
        print(f"  🔍 分析: {os.path.relpath(program_dir, self.base_dir)}")
        print(f"      输出: {os.path.relpath(output_file, self.base_dir)}")
        
              
        cmd = [
            "python3", "semantic_equivalence_analyzer.py",
            newv_prefix,                  
            oldv_prefix,                  
            "--output", output_file,
            "--timeout", "30000"         
        ]
        
        try:
            start_time = time.time()
            result = subprocess.run(
                cmd,
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                timeout=120          
            )
            elapsed_time = time.time() - start_time
            
            if result.returncode == 0:
                         
                output_lines = result.stdout.split('\n')
                enhanced_results = self.parse_enhanced_results(output_lines)
                
                         
                if enhanced_results["program_equivalent"]:
                    equivalence_status = "equivalent"
                elif enhanced_results["suspicious_constraint_pairs"] > 0:
                    equivalence_status = "suspicious_constraint"
                elif enhanced_results["suspicious_output_pairs"] > 0:
                    equivalence_status = "suspicious_output"
                else:
                    equivalence_status = "not_equivalent"
                
                print(f"      ✅ 成功 - {equivalence_status} ({elapsed_time:.1f}s)")
                print(f"        等价: {enhanced_results['equivalent_pairs']}, "
                      f"疑似约束: {enhanced_results['suspicious_constraint_pairs']}, "
                      f"疑似输出: {enhanced_results['suspicious_output_pairs']}, "
                      f"不等价: {enhanced_results['non_equivalent_pairs']}")
                
                return {
                    "status": "success", 
                    "equivalence_status": equivalence_status,
                    "enhanced_results": enhanced_results,
                    "time": elapsed_time,
                    "output_file": output_file
                }
            else:
                print(f"      ❌ 失败 - 错误码: {result.returncode} ({elapsed_time:.1f}s)")
                if result.stderr:
                    print(f"      错误: {result.stderr[:100]}...")
                return {
                    "status": "failed", 
                    "error": result.stderr, 
                    "time": elapsed_time
                }
                
        except subprocess.TimeoutExpired:
            print(f"      ⏰ 超时 (120s)")
            return {"status": "timeout", "time": 120}
        except Exception as e:
            print(f"      💥 异常: {str(e)}")
            return {"status": "exception", "error": str(e), "time": 0}
    
    def analyze_all_programs(self):
        """分析所有程序"""
        print("🧠 开始增强的批量等价性分析...")
        print("=" * 60)
        print("四类判断流程:")
        print("  1️⃣  约束等价且输出相同 → 等价")
        print("  2️⃣  约束不等价但输出相同 → 疑似不等价（约束）")
        print("  3️⃣  约束等价但输出不同 → 疑似不等价（输出）")
        print("  4️⃣  约束不等价且输出不同 → 不等价")
        print("=" * 60)
        
               
        eq_pairs, neq_pairs = self.find_program_pairs()
        
        print(f"\n📊 发现程序对:")
        print(f"  Eq (应该等价): {len(eq_pairs)} 个")
        print(f"  NEq (应该不等价): {len(neq_pairs)} 个")
        print(f"  总计: {len(eq_pairs) + len(neq_pairs)} 个")
        
        if len(eq_pairs) == 0 and len(neq_pairs) == 0:
            print("❌ 未找到任何有约束文件的程序对")
            return
        
                 
        results = {
            "eq_results": {
                "success": 0, "failed": 0, "timeout": 0, "exception": 0,
                "equivalent": 0, "suspicious_constraint": 0, "suspicious_output": 0, "not_equivalent": 0,
                "correct_predictions": 0, "wrong_predictions": 0, "total_time": 0,
                "detailed_results": []
            },
            "neq_results": {
                "success": 0, "failed": 0, "timeout": 0, "exception": 0,
                "equivalent": 0, "suspicious_constraint": 0, "suspicious_output": 0, "not_equivalent": 0,
                "correct_predictions": 0, "wrong_predictions": 0, "total_time": 0,
                "detailed_results": []
            }
        }
        
                 
        if eq_pairs:
            print(f"\n🟢 分析Eq程序对 (期望：等价)")
            print("-" * 40)
            
            for i, pair in enumerate(eq_pairs, 1):
                print(f"[{i}/{len(eq_pairs)}] ", end="")
                result = self.run_equivalence_analysis(pair['dir'], "Eq")
                
                results["eq_results"]["total_time"] += result["time"]
                
                        
                detail = {
                    "dir": pair['dir'],
                    "result": result,
                    "expected": "equivalent",
                    "actual": result.get("equivalence_status", "unknown")
                }
                results["eq_results"]["detailed_results"].append(detail)
                
                if result["status"] == "success":
                    results["eq_results"]["success"] += 1
                    
                            
                    eq_status = result.get("equivalence_status", "unknown")
                    if eq_status in results["eq_results"]:
                        results["eq_results"][eq_status] += 1
                    
                             
                    if eq_status == "equivalent":               
                        results["eq_results"]["correct_predictions"] += 1
                    else:                   
                        results["eq_results"]["wrong_predictions"] += 1
                        
                elif result["status"] == "failed":
                    results["eq_results"]["failed"] += 1
                elif result["status"] == "timeout":
                    results["eq_results"]["timeout"] += 1
                else:
                    results["eq_results"]["exception"] += 1
        
                  
        if neq_pairs:
            print(f"\n🔴 分析NEq程序对 (期望：不等价)")
            print("-" * 40)
            
            for i, pair in enumerate(neq_pairs, 1):
                print(f"[{i}/{len(neq_pairs)}] ", end="")
                result = self.run_equivalence_analysis(pair['dir'], "NEq")
                
                results["neq_results"]["total_time"] += result["time"]
                
                        
                detail = {
                    "dir": pair['dir'],
                    "result": result,
                    "expected": "not_equivalent",
                    "actual": result.get("equivalence_status", "unknown")
                }
                results["neq_results"]["detailed_results"].append(detail)
                
                if result["status"] == "success":
                    results["neq_results"]["success"] += 1
                    
                            
                    neq_status = result.get("equivalence_status", "unknown")
                    if neq_status in results["neq_results"]:
                        results["neq_results"][neq_status] += 1
                    
                             
                    if neq_status in ["not_equivalent", "suspicious_constraint", "suspicious_output"]:                    
                        results["neq_results"]["correct_predictions"] += 1
                    else:                
                        results["neq_results"]["wrong_predictions"] += 1
                        
                elif result["status"] == "failed":
                    results["neq_results"]["failed"] += 1
                elif result["status"] == "timeout":
                    results["neq_results"]["timeout"] += 1
                else:
                    results["neq_results"]["exception"] += 1
        
                   
        self.generate_enhanced_summary_report(results, eq_pairs, neq_pairs)
        
        return results
    
    def generate_enhanced_summary_report(self, results, eq_pairs, neq_pairs):
        """生成增强的总结报告"""
        print(f"\n" + "=" * 60)
        print("🎯 增强的批量等价性分析完成统计:")
        
                 
        eq_stats = results["eq_results"]
        print(f"\n🟢 Eq程序对 (期望等价，共{len(eq_pairs)}个):")
        print(f"  成功分析: {eq_stats['success']}")
        print(f"  分析失败: {eq_stats['failed']}")
        print(f"  分析超时: {eq_stats['timeout']}")
        print(f"  发生异常: {eq_stats['exception']}")
        if eq_stats['success'] > 0:
            print(f"  📊 四类结果分布:")
            print(f"    ✅ 等价: {eq_stats['equivalent']}")
            print(f"    ⚠️  疑似不等价-约束: {eq_stats['suspicious_constraint']}")
            print(f"    ⚠️  疑似不等价-输出: {eq_stats['suspicious_output']}")
            print(f"    ❌ 不等价: {eq_stats['not_equivalent']}")
            print(f"  正确预测: {eq_stats['correct_predictions']} (准确率: {eq_stats['correct_predictions']/eq_stats['success']*100:.1f}%)")
            print(f"  错误预测: {eq_stats['wrong_predictions']}")
        print(f"  总用时: {eq_stats['total_time']:.1f}s")
        
                  
        neq_stats = results["neq_results"]
        print(f"\n🔴 NEq程序对 (期望不等价，共{len(neq_pairs)}个):")
        print(f"  成功分析: {neq_stats['success']}")
        print(f"  分析失败: {neq_stats['failed']}")
        print(f"  分析超时: {neq_stats['timeout']}")
        print(f"  发生异常: {neq_stats['exception']}")
        if neq_stats['success'] > 0:
            print(f"  📊 四类结果分布:")
            print(f"    ✅ 等价: {neq_stats['equivalent']}")
            print(f"    ⚠️  疑似不等价-约束: {neq_stats['suspicious_constraint']}")
            print(f"    ⚠️  疑似不等价-输出: {neq_stats['suspicious_output']}")
            print(f"    ❌ 不等价: {neq_stats['not_equivalent']}")
            print(f"  正确预测: {neq_stats['correct_predictions']} (准确率: {neq_stats['correct_predictions']/neq_stats['success']*100:.1f}%)")
            print(f"  错误预测: {neq_stats['wrong_predictions']}")
        print(f"  总用时: {neq_stats['total_time']:.1f}s")
        
              
        total_programs = len(eq_pairs) + len(neq_pairs)
        total_success = eq_stats['success'] + neq_stats['success']
        total_correct = eq_stats['correct_predictions'] + neq_stats['correct_predictions']
        total_time = eq_stats['total_time'] + neq_stats['total_time']
        
        print(f"\n📊 总体统计:")
        print(f"  总程序对: {total_programs}")
        print(f"  成功分析: {total_success} (成功率: {total_success/total_programs*100:.1f}%)")
        if total_success > 0:
            print(f"  预测准确: {total_correct} (准确率: {total_correct/total_success*100:.1f}%)")
        print(f"  总分析时间: {total_time:.1f}s")
        print(f"  平均分析时间: {total_time/max(1, total_success):.1f}s")
        
                  
        report_file = "enhanced_batch_equivalence_analysis_report.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("增强的批量等价性分析报告\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"分析时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write("四类判断流程:\n")
            f.write("  1️⃣  约束等价且输出相同 → 等价\n")
            f.write("  2️⃣  约束不等价但输出相同 → 疑似不等价（约束）\n")
            f.write("  3️⃣  约束等价但输出不同 → 疑似不等价（输出）\n")
            f.write("  4️⃣  约束不等价且输出不同 → 不等价\n\n")
            
            f.write("总体统计:\n")
            f.write(f"  Eq程序对: {len(eq_pairs)} 个\n")
            f.write(f"  NEq程序对: {len(neq_pairs)} 个\n")
            f.write(f"  总程序对: {total_programs} 个\n")
            f.write(f"  成功分析: {total_success} 个 ({total_success/total_programs*100:.1f}%)\n")
            if total_success > 0:
                f.write(f"  预测准确: {total_correct} 个 ({total_correct/total_success*100:.1f}%)\n")
            f.write(f"  总分析时间: {total_time:.1f} 秒\n\n")
            
                      
            f.write("Eq程序四类结果详情:\n")
            f.write("-" * 30 + "\n")
            for detail in eq_stats['detailed_results']:
                if detail['result']['status'] == 'success':
                    f.write(f"  {os.path.relpath(detail['dir'], self.base_dir)}: {detail['actual']}\n")
            f.write("\n")
            
            f.write("NEq程序四类结果详情:\n")
            f.write("-" * 30 + "\n")
            for detail in neq_stats['detailed_results']:
                if detail['result']['status'] == 'success':
                    f.write(f"  {os.path.relpath(detail['dir'], self.base_dir)}: {detail['actual']}\n")
            f.write("\n")
            
            f.write("详细结果请查看各个程序目录下的 equivalence_analysis_*.txt 文件\n")
        
        print(f"\n📄 增强的总结报告已保存到: {report_file}")

def main():
    """主函数"""
    print("🔧 启动增强的批量等价性分析（全部benchmark）...")
    
    analyzer = EnhancedBatchEquivalenceAnalyzer()
    
            
    results = analyzer.analyze_all_programs()
    
    print(f"\n✅ 增强的批量等价性分析完成!")

if __name__ == "__main__":
    main()
