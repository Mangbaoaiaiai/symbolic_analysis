#!/bin/bash

# 完成剩余的Java到C转换

echo "开始完成剩余的转换..."

# 查找所有还没有C文件的Java文件
find benchmarks -name "*.java" | grep -E "(oldV|newV)" | while read java_file; do
    dir=$(dirname "$java_file")
    base=$(basename "$java_file" .java)
    
    echo "处理: $dir/$base.java"
    cd "$dir"
    
    if [ "$base" = "oldV" ]; then
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
        gcc -o oldV oldV.c
        echo "  ✓ oldV.c 创建并编译"
    elif [ "$base" = "newV" ]; then
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
        gcc -o newV newV.c
        echo "  ✓ newV.c 创建并编译"
    fi
    
    cd - > /dev/null
done

echo "转换完成！"
echo "总共生成了 $(find benchmarks -name "*.c" | wc -l) 个C文件"
echo "总共生成了 $(find benchmarks -name "oldV" -o -name "newV" | wc -l) 个可执行文件" 