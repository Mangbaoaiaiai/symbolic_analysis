                      
"""
变量名快速匹配路径

修复版的路径分析器
直接从路径签名信息中提取数据，避免SMT解析问题
"""

import re
import glob
import ast

def extract_path_signature_from_file(file_path):
    """从文件注释中提取路径签名信息"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
               
        var_match = re.search(r'; 变量值: (.+)', content)
        if var_match:
            var_str = var_match.group(1)
            try:
                variable_values = ast.literal_eval(var_str)
            except:
                variable_values = {}
        else:
            variable_values = {}
        
                
        constraint_match = re.search(r'; 约束信息: (.+)', content)
        if constraint_match:
            constraint_str = constraint_match.group(1)
            try:
                constraint_info = ast.literal_eval(constraint_str)
            except:
                constraint_info = {'count': 0, 'types': []}
        else:
            constraint_info = {'count': 0, 'types': []}
        
                
        hash_match = re.search(r'; 内存哈希: (.+)', content)
        if hash_match:
            try:
                memory_hash = int(hash_match.group(1))
            except:
                memory_hash = 0
        else:
            memory_hash = 0
        
                
        output_pattern = r'; 程序输出:\s*(.+?)(?:\n|$)'
        output_match = re.search(output_pattern, content, re.DOTALL)
        if output_match:
            program_output = output_match.group(1).strip()
        else:
            program_output = ""
        
        return {
            'file_path': file_path,
            'variable_values': variable_values,
            'constraint_info': constraint_info,
            'memory_hash': memory_hash,
            'program_output': program_output
        }
    
    except Exception as e:
        print(f"解析文件 {file_path} 失败: {e}")
        return None

def compute_path_distance_fixed(path1, path2):
    """计算两个路径之间的距离"""
    if not path1 or not path2:
        return {
            'total': float('inf'),
            'variable': float('inf'),
            'constraint_count': float('inf'),
            'hash': float('inf'),
            'output': float('inf')
        }
    
                  
    var_distance = 0
    all_vars = set(path1['variable_values'].keys()) | set(path2['variable_values'].keys())
    
    for var in all_vars:
        val1 = path1['variable_values'].get(var, 0)
        val2 = path2['variable_values'].get(var, 0)
        if val1 is not None and val2 is not None:
            var_distance += abs(val1 - val2)
        else:
            var_distance += 1000             
    
                   
    count1 = path1['constraint_info'].get('count', 0)
    count2 = path2['constraint_info'].get('count', 0)
    constraint_distance = abs(count1 - count2)
    
                   
    hash1 = path1['memory_hash']
    hash2 = path2['memory_hash']
    hash_distance = 0 if hash1 == hash2 else 1
    
                    
    output1 = path1['program_output']
    output2 = path2['program_output']
    output_distance = 0 if output1 == output2 else 1
    
          
    total_distance = var_distance + constraint_distance * 10 + hash_distance * 50 + output_distance * 100
    
    return {
        'total': total_distance,
        'variable': var_distance,
        'constraint_count': constraint_distance,
        'hash': hash_distance,
        'output': output_distance
    }

def find_path_matches_fixed(paths1, paths2):
    """寻找路径匹配"""
    print(f"比较 {len(paths1)} 条路径与 {len(paths2)} 条路径...")
    
    matches = {
        'exact_variable_matches': [],             
        'exact_output_matches': [],                
        'similar_constraint_matches': [],         
        'approximate_matches': [],               
        'no_matches': []                     
    }
    
    used_paths2 = set()
    
    for i, path1 in enumerate(paths1):
        if path1 is None:
            continue
            
        best_match = None
        best_match_type = None
        best_distance = float('inf')
        
        for j, path2 in enumerate(paths2):
            if path2 is None or j in used_paths2:
                continue
            
                  
            distance = compute_path_distance_fixed(path1, path2)
            
                          
            if distance['variable'] == 0:
                matches['exact_variable_matches'].append((i, j, distance))
                used_paths2.add(j)
                best_match = j
                best_match_type = 'exact_variable'
                break
            
                           
            if distance['output'] == 0 and path1['program_output'] != "":
                if best_match_type != 'exact_variable':
                    best_match = j
                    best_match_type = 'exact_output'
                    best_distance = distance['total']
            
                         
            elif distance['constraint_count'] <= 1:              
                if best_match_type not in ['exact_variable', 'exact_output']:
                    if distance['total'] < best_distance:
                        best_match = j
                        best_match_type = 'similar_constraint'
                        best_distance = distance['total']
            
                       
            elif distance['total'] < best_distance:
                if best_match_type not in ['exact_variable', 'exact_output', 'similar_constraint']:
                    best_match = j
                    best_match_type = 'approximate'
                    best_distance = distance['total']
        
                       
        if best_match_type == 'exact_output':
            matches['exact_output_matches'].append((i, best_match, compute_path_distance_fixed(path1, paths2[best_match])))
            used_paths2.add(best_match)
        elif best_match_type == 'similar_constraint':
            matches['similar_constraint_matches'].append((i, best_match, compute_path_distance_fixed(path1, paths2[best_match])))
            used_paths2.add(best_match)
        elif best_match_type == 'approximate' and best_distance < 200:      
            matches['approximate_matches'].append((i, best_match, compute_path_distance_fixed(path1, paths2[best_match])))
            used_paths2.add(best_match)
        else:
            matches['no_matches'].append(i)
    
    return matches

def analyze_and_compare_fixed(prefix1, prefix2, output_file="fixed_comparison.txt"):
    """修复版的路径比较分析"""
    print("开始修复版路径比较分析...")
    
          
    files1 = sorted(glob.glob(f"{prefix1}*.txt"))
    files2 = sorted(glob.glob(f"{prefix2}*.txt"))
    
    print(f"找到文件: {len(files1)} vs {len(files2)}")
    
          
    paths1 = [extract_path_signature_from_file(f) for f in files1]
    paths2 = [extract_path_signature_from_file(f) for f in files2]
    
            
    paths1 = [p for p in paths1 if p is not None]
    paths2 = [p for p in paths2 if p is not None]
    
    print(f"有效路径: {len(paths1)} vs {len(paths2)}")
    
    if len(paths1) == 0 or len(paths2) == 0:
        print("❌ 没有有效路径进行比较")
        return
    
          
    matches = find_path_matches_fixed(paths1, paths2)
    
          
    with open(output_file, "w", encoding='utf-8') as f:
        f.write("修复版路径等价性分析报告\n")
        f.write("=" * 50 + "\n\n")
        
        f.write(f"数据源:\n")
        f.write(f"  集合1: {prefix1}* ({len(paths1)} 有效路径)\n")
        f.write(f"  集合2: {prefix2}* ({len(paths2)} 有效路径)\n\n")
        
        f.write(f"匹配统计:\n")
        f.write(f"  精确变量匹配: {len(matches['exact_variable_matches'])} 对\n")
        f.write(f"  精确输出匹配: {len(matches['exact_output_matches'])} 对\n")
        f.write(f"  约束结构匹配: {len(matches['similar_constraint_matches'])} 对\n")
        f.write(f"  近似匹配: {len(matches['approximate_matches'])} 对\n")
        f.write(f"  无匹配路径: {len(matches['no_matches'])} 个\n\n")
        
                
        if matches['exact_variable_matches']:
            f.write("精确变量匹配:\n")
            f.write("-" * 30 + "\n")
            for i, j, dist in matches['exact_variable_matches']:
                f.write(f"路径 {i+1} <-> 路径 {j+1} (变量完全相同)\n")
                f.write(f"  变量值: {paths1[i]['variable_values']}\n")
                f.write(f"  输出1: {paths1[i]['program_output']}\n")
                f.write(f"  输出2: {paths2[j]['program_output']}\n\n")
        
        if matches['exact_output_matches']:
            f.write("精确输出匹配:\n")
            f.write("-" * 30 + "\n")
            for i, j, dist in matches['exact_output_matches']:
                f.write(f"路径 {i+1} <-> 路径 {j+1} (输出完全相同)\n")
                f.write(f"  变量值1: {paths1[i]['variable_values']}\n")
                f.write(f"  变量值2: {paths2[j]['variable_values']}\n")
                f.write(f"  共同输出: {paths1[i]['program_output']}\n")
                f.write(f"  距离: {dist['total']}\n\n")
        
        if matches['similar_constraint_matches']:
            f.write("约束结构匹配:\n")
            f.write("-" * 30 + "\n")
            for i, j, dist in matches['similar_constraint_matches']:
                f.write(f"路径 {i+1} <-> 路径 {j+1} (约束结构相似)\n")
                f.write(f"  约束数1: {paths1[i]['constraint_info']['count']}\n")
                f.write(f"  约束数2: {paths2[j]['constraint_info']['count']}\n")
                f.write(f"  距离: {dist['total']}\n\n")
        
        if matches['no_matches']:
            f.write("无匹配的路径:\n")
            f.write("-" * 30 + "\n")
            for i in matches['no_matches']:
                f.write(f"路径 {i+1}: {paths1[i]['program_output']}\n")
    
    print(f"修复版分析完成，报告保存到: {output_file}")
    
          
    total_matched = (len(matches['exact_variable_matches']) + 
                    len(matches['exact_output_matches']) + 
                    len(matches['similar_constraint_matches']) + 
                    len(matches['approximate_matches']))
    
    print(f"\n总结:")
    print(f"  总路径数: {len(paths1)} vs {len(paths2)}")
    print(f"  成功匹配: {total_matched}")
    print(f"  匹配率: {total_matched/len(paths1)*100:.1f}%")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='修复版路径等价性分析')
    parser.add_argument('prefix1', help='第一组路径文件的前缀')
    parser.add_argument('prefix2', help='第二组路径文件的前缀')
    parser.add_argument('--output', default='fixed_comparison.txt', help='输出报告文件')
    
    args = parser.parse_args()
    
    analyze_and_compare_fixed(args.prefix1, args.prefix2, args.output)

if __name__ == "__main__":
    main() 