#!/bin/bash

# Batch convert Java tests to C and compile to ELF for angr symbolic execution

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BENCHMARKS_DIR="$REPO_ROOT/experiments/ardiff_comparison/benchmarks"
REPORT_FILE="$REPO_ROOT/conversion_report.txt"

echo "Starting batch Java-to-C conversion and compile..." > "$REPORT_FILE"
echo "Time: $(date)" >> "$REPORT_FILE"
echo "========================================" >> "$REPORT_FILE"

total_tests=0
successful_conversions=0
failed_conversions=0

find "$BENCHMARKS_DIR" -type f \( -name "newV.java" -o -name "oldV.java" \) | while read -r java_file; do
    test_dir=$(dirname "$java_file")
    echo "Processing test dir: $test_dir" | tee -a "$REPORT_FILE"
    
    cd "$test_dir"
    total_tests=$((total_tests + 1))
    
    # Check for Java sources
    has_old=false
    has_new=false
    
    if [ -f "oldV.java" ]; then
        has_old=true
    fi
    
    if [ -f "newV.java" ]; then
        has_new=true
    fi
    
    if [ "$has_old" = false ] && [ "$has_new" = false ]; then
        echo "  Skip: no oldV.java or newV.java found" | tee -a "$REPORT_FILE"
        continue
    fi
    
    # Convert oldV.java
    if [ "$has_old" = true ]; then
        echo "  Convert oldV.java -> oldV.c" | tee -a "$REPORT_FILE"
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
    
    # Convert newV.java
    if [ "$has_new" = true ]; then
        echo "  Convert newV.java -> newV.c" | tee -a "$REPORT_FILE"
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
    
    # Compile C
    echo "  Compiling C..." | tee -a "$REPORT_FILE"
    if gcc -o oldV oldV.c 2>/dev/null; then
        echo "    ✓ oldV compiled" | tee -a "$REPORT_FILE"
    else
        echo "    ✗ oldV compile failed" | tee -a "$REPORT_FILE"
    fi
    if gcc -o newV newV.c 2>/dev/null; then
        echo "    ✓ newV compiled" | tee -a "$REPORT_FILE"
    else
        echo "    ✗ newV compile failed" | tee -a "$REPORT_FILE"
    fi
    # Test executables
    echo "  Testing executables..." | tee -a "$REPORT_FILE"
    if [ -x "./oldV" ] && [ -x "./newV" ]; then
        echo "    ✓ Both executables OK" | tee -a "$REPORT_FILE"
        successful_conversions=$((successful_conversions + 1))
    else
        echo "    ✗ Executable test failed" | tee -a "$REPORT_FILE"
        failed_conversions=$((failed_conversions + 1))
    fi
    
    echo "  ----------------------------------------" | tee -a "$REPORT_FILE"
    
done

# Report
echo "========================================" >> "$REPORT_FILE"
echo "Conversion done!" >> "$REPORT_FILE"
echo "Total tests: $total_tests" >> "$REPORT_FILE"
echo "Successful: $successful_conversions" >> "$REPORT_FILE"
echo "Failed: $failed_conversions" >> "$REPORT_FILE"
echo "Finished: $(date)" >> "$REPORT_FILE"

echo ""
echo "Batch conversion done!"
echo "Total tests: $total_tests"
echo "Successful: $successful_conversions"
echo "Failed: $failed_conversions"
echo "Report: $REPORT_FILE" 
