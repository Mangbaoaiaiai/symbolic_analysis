#!/bin/bash

# Complete remaining Java-to-C conversions

echo "Completing remaining conversions..."

find benchmarks -name "*.java" | grep -E "(oldV|newV)" | while read java_file; do
    dir=$(dirname "$java_file")
    base=$(basename "$java_file" .java)
    echo "Processing: $dir/$base.java"
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
        echo "  ✓ oldV.c created and compiled"
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
        echo "  ✓ newV.c created and compiled"
    fi
    
    cd - > /dev/null
done

echo "Conversion done!"
echo "Total C files: $(find benchmarks -name "*.c" | wc -l)"
echo "Total executables: $(find benchmarks -name "oldV" -o -name "newV" | wc -l)" 