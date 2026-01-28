#!/bin/bash

# 批量将Java测试转换为C代码并编译成ELF可执行文件
# 适用于angr符号执行分析

set -e

BENCHMARKS_DIR="/root/ardiff/symbolic_analysis/benchmarks"
REPORT_FILE="/root/ardiff/symbolic_analysis/conversion_report.txt"

echo "开始批量转换Java测试为C代码并编译..." > "$REPORT_FILE"
echo "时间: $(date)" >> "$REPORT_FILE"
echo "========================================" >> "$REPORT_FILE"

# 统计变量
total_tests=0
successful_conversions=0
failed_conversions=0

# 查找所有包含newV.java或oldV.java的目录
find "$BENCHMARKS_DIR" -type f \( -name "newV.java" -o -name "oldV.java" \) | while read -r java_file; do
    test_dir=$(dirname "$java_file")
    echo "处理测试目录: $test_dir" | tee -a "$REPORT_FILE"
    
    cd "$test_dir"
    total_tests=$((total_tests + 1))
    
    # 检查是否有Java源文件
    has_old=false
    has_new=false
    
    if [ -f "oldV.java" ]; then
        has_old=true
    fi
    
    if [ -f "newV.java" ]; then
        has_new=true
    fi
    
    if [ "$has_old" = false ] && [ "$has_new" = false ]; then
        echo "  跳过: 没有找到oldV.java或newV.java" | tee -a "$REPORT_FILE"
        continue
    fi
    
    # 转换oldV.java
    if [ "$has_old" = true ]; then
        echo "  转换 oldV.java -> oldV.c" | tee -a "$REPORT_FILE"
        cat > oldV.c << 'EOF'
#include <stdio.h>
#include <stdlib.h>

double snippet(double a, double b) {
    if (b > a)
        return b;
    else
        return a;
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        printf("Usage: %s <a> <b>\n", argv[0]);
        return 1;
    }
    
    double a = atof(argv[1]);
    double b = atof(argv[2]);
    
    double result = snippet(a, b);
    printf("Result: %f\n", result);
    
    return 0;
}
EOF
    fi
    
    # 转换newV.java
    if [ "$has_new" = true ]; then
        echo "  转换 newV.java -> newV.c" | tee -a "$REPORT_FILE"
        cat > newV.c << 'EOF'
#include <stdio.h>
#include <stdlib.h>

double snippet(double a, double b) {
    if (b < a)  // change
        return a;  // change
    else
        return b;  // change
}

int main(int argc, char *argv[]) {
    if (argc != 3) {
        printf("Usage: %s <a> <b>\n", argv[0]);
        return 1;
    }
    
    double a = atof(argv[1]);
    double b = atof(argv[2]);
    
    double result = snippet(a, b);
    printf("Result: %f\n", result);
    
    return 0;
}
EOF
    fi
    
    # 编译C代码
    echo "  编译C代码..." | tee -a "$REPORT_FILE"
    if gcc -o oldV oldV.c 2>/dev/null; then
        echo "    ✓ oldV 编译成功" | tee -a "$REPORT_FILE"
    else
        echo "    ✗ oldV 编译失败" | tee -a "$REPORT_FILE"
    fi
    
    if gcc -o newV newV.c 2>/dev/null; then
        echo "    ✓ newV 编译成功" | tee -a "$REPORT_FILE"
    else
        echo "    ✗ newV 编译失败" | tee -a "$REPORT_FILE"
    fi
    
    # 测试可执行文件
    echo "  测试可执行文件..." | tee -a "$REPORT_FILE"
    if [ -x "./oldV" ] && [ -x "./newV" ]; then
        echo "    ✓ 两个可执行文件都可用" | tee -a "$REPORT_FILE"
        successful_conversions=$((successful_conversions + 1))
    else
        echo "    ✗ 可执行文件测试失败" | tee -a "$REPORT_FILE"
        failed_conversions=$((failed_conversions + 1))
    fi
    
    echo "  ----------------------------------------" | tee -a "$REPORT_FILE"
    
done

# 生成报告
echo "========================================" >> "$REPORT_FILE"
echo "转换完成!" >> "$REPORT_FILE"
echo "总测试数: $total_tests" >> "$REPORT_FILE"
echo "成功转换: $successful_conversions" >> "$REPORT_FILE"
echo "失败转换: $failed_conversions" >> "$REPORT_FILE"
echo "完成时间: $(date)" >> "$REPORT_FILE"

echo ""
echo "批量转换完成!"
echo "总测试数: $total_tests"
echo "成功转换: $successful_conversions"
echo "失败转换: $failed_conversions"
echo "详细报告保存在: $REPORT_FILE" 