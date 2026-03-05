#!/usr/bin/env bash
# Run one ardiff_comparison benchmark: compile, symbolic execution, equivalence analysis.
# Usage: from repo root:
#   ./experiments/ardiff_comparison/run_one_benchmark.sh experiments/ardiff_comparison/benchmarks/Airy/MAX/Eq
# Or: ./experiments/ardiff_comparison/run_one_benchmark.sh benchmarks/Airy/MAX/Eq
# (relative to repo root)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Repo root = symbolic_analysis (parent of experiments)
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCRIPTS="$REPO_ROOT/scripts"
CASE_DIR="${1:-}"

if [ -z "$CASE_DIR" ]; then
  echo "Usage: $0 <benchmark_case_dir>"
  echo "  e.g. $0 benchmarks/Airy/MAX/Eq"
  echo "  or   $0 $REPO_ROOT/experiments/ardiff_comparison/benchmarks/Airy/MAX/Eq"
  exit 1
fi

# Resolve case dir (relative to repo root, or relative to ardiff benchmarks, or absolute)
if [ ! -d "$CASE_DIR" ]; then
  CASE_DIR="$REPO_ROOT/$CASE_DIR"
fi
if [ ! -d "$CASE_DIR" ]; then
  CASE_DIR="$SCRIPT_DIR/benchmarks/$1"
fi
if [ ! -d "$CASE_DIR" ]; then
  echo "Error: directory not found: $1 (tried $CASE_DIR and $SCRIPT_DIR/benchmarks/$1)"
  exit 1
fi

echo "Benchmark case: $CASE_DIR"
echo "Repo root:      $REPO_ROOT"
echo "Scripts:        $SCRIPTS"
echo ""

cd "$CASE_DIR"

if [ ! -f "symbolic_oldV.c" ] || [ ! -f "symbolic_newV.c" ]; then
  echo "Error: symbolic_oldV.c and/or symbolic_newV.c not found in $CASE_DIR"
  exit 1
fi

echo "=== 1. Compiling ==="
gcc -o symbolic_oldV symbolic_oldV.c || { echo "gcc symbolic_oldV.c failed"; exit 1; }
gcc -o symbolic_newV symbolic_newV.c || { echo "gcc symbolic_newV.c failed"; exit 1; }
echo ""

echo "=== 2. Symbolic execution (oldV) ==="
python3 "$SCRIPTS/se_script_improved.py" --binary ./symbolic_oldV
echo ""

echo "=== 3. Symbolic execution (newV) ==="
python3 "$SCRIPTS/se_script_improved.py" --binary ./symbolic_newV
echo ""

echo "=== 4. Equivalence analysis ==="
python3 "$SCRIPTS/ardiff_comparison/semantic_equivalence_analyzer_enhanced.py" \
  symbolic_oldV_path symbolic_newV_path \
  --output enhanced_equivalence_report.txt

echo ""
echo "Done. Report: $CASE_DIR/enhanced_equivalence_report.txt"
