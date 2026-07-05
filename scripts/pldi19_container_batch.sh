#!/usr/bin/env bash
set -u

export PATH=/home/equivalence/equivalence-checker/bin:/home/equivalence/SageMath:$PATH

work_root="${1:-/work/ardiff_typed}"
log_root="${2:-/work/ardiff_logs}"
case_timeout="${CASE_TIMEOUT:-180s}"
tcgen_timeout="${TCGEN_TIMEOUT:-180s}"
make_timeout="${MAKE_TIMEOUT:-60s}"

mkdir -p "$log_root"
summary="$log_root/summary.tsv"
progress="$log_root/progress.log"

printf "case\tstatus\tprediction\telapsed_s\terror\n" > "$summary"
printf "Starting PLDI19 batch at %s\n" "$(date -Is)" > "$progress"

total="$(find "$work_root" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
index=0

find "$work_root" -mindepth 1 -maxdepth 1 -type d | sort | while IFS= read -r case_dir; do
  index=$((index + 1))
  name="$(basename "$case_dir")"
  case_log="$log_root/$name"
  mkdir -p "$case_log"

  printf "[%s/%s] %s start %s\n" "$index" "$total" "$name" "$(date -Is)" | tee -a "$progress"
  start="$(date +%s)"
  status="ok"
  error=""
  prediction="unknown"

  (
    cd "$case_dir" || exit 97
    make clean
  ) > "$case_log/clean.stdout.txt" 2> "$case_log/clean.stderr.txt"

  if [ "$status" = "ok" ]; then
    (
      cd "$case_dir" || exit 97
      timeout "$make_timeout" make
    ) > "$case_log/make.stdout.txt" 2> "$case_log/make.stderr.txt"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      status="failed"
      error="make_exit_$rc"
    fi
  fi

  if [ "$status" = "ok" ]; then
    (
      cd "$case_dir" || exit 97
      timeout "$tcgen_timeout" make tcgen
    ) > "$case_log/tcgen.stdout.txt" 2> "$case_log/tcgen.stderr.txt"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      status="failed"
      error="tcgen_exit_$rc"
    fi
  fi

  if [ "$status" = "ok" ]; then
    (
      cd "$case_dir" || exit 97
      timeout "$case_timeout" bash ./demo.sh
    ) > "$case_log/verify.stdout.txt" 2> "$case_log/verify.stderr.txt"
    rc=$?
    if [ "$rc" -ne 0 ]; then
      status="failed"
      error="verify_exit_$rc"
    fi
  fi

  if grep -Eiq "Equivalent:[[:space:]]*yes" "$case_log"/verify.stdout.txt "$case_log"/verify.stderr.txt 2>/dev/null; then
    prediction="true"
  elif grep -Eiq "Equivalent:[[:space:]]*no" "$case_log"/verify.stdout.txt "$case_log"/verify.stderr.txt 2>/dev/null; then
    prediction="false"
  fi

  end="$(date +%s)"
  elapsed=$((end - start))
  printf "%s\t%s\t%s\t%s\t%s\n" "$name" "$status" "$prediction" "$elapsed" "$error" >> "$summary"
  printf "[%s/%s] %s done status=%s prediction=%s elapsed=%ss error=%s\n" "$index" "$total" "$name" "$status" "$prediction" "$elapsed" "$error" | tee -a "$progress"
done

printf "Finished PLDI19 batch at %s\n" "$(date -Is)" | tee -a "$progress"
