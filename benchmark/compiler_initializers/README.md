# TinyCC initializer findings and BOE coverage

Recorded on 2026-11-26 (Asia/Shanghai). This package summarizes the experiment
named compiler_initializer_boe_coverage_20261126 and its preceding source,
mechanism, history, and public-record checks.

## Findings and attribution

| Group | Original source | Adapted BOE entry | Observed error |
|---|---|---|---|
| H1: static whole-aggregate reinitialization | [S1/original.c](S1/original.c) | [S1/adapted.c](S1/adapted.c) | The second whole-element initializer writes a=2 but incorrectly retains b=10; b should be zero. |
| Union member switching | [U1 file-scope reproducer](U1/original.c), [U3 automatic-object variant](U3/original.c) | [U3/adapted.c](U3/adapted.c) | Switching from a to the c array through .c[2] retains 42 in c[0]; the correct array is 0 0 1 0. |

H1 requests a second clearing operation, but init_putz() assumes that static
section storage is already zero. That assumption does not hold after an
earlier initializer has written into the same range. Its original static
object contains 020000000a000000; the diagnostic patch restores
0200000000000000 on the tested little-endian target.

[WG14 DR 253, final Committee Response](https://www.open-std.org/jtc1/sc22/wg14/www/docs/dr_253.htm)
provides the whole-object overriding and implicit-zero semantics. It is a
language-semantics document, not a TinyCC implementation bug report.

The closest public report is
[Savannah #68807](https://savannah.nongnu.org/bugs/?func=detailitem&item_id=68807).
It reports the file-scope union form. U3 is treated as an automatic-storage
extension reproduction of that known behavior and adds no independent new
bug to the count. #68806 is a duplicate submission of #68807.

For H1, seven mechanism-oriented queries plus a reused fourteen-query
historical archive found no clearly matching report or regression test.
The status is **no matching record found in the searched scope**. Neither
exhaustive novelty nor a maintainer-confirmed independent issue is claimed.
No H1 issue was submitted in the recorded workflow.

The [diagnostic patch](patches/h1_static_zero.patch) changes only static
clearing. In the preceding ten-case mechanism matrix it corrected S1 and
the two braced static union variants, preserved the correct member-only
overrides, and left the three chained union cases incorrect. It was not
validated as a general fix for pointer relocations, every section type,
other targets, or arbitrary initializer combinations.

The bundled patch changes CRLF line endings from the archived patch to LF
so that git apply works on the pinned source. Applying it was checked to
produce the exact recorded patched tccgen.c hash. Both patch hashes and the
source hashes are retained in summary.json.

Historical measurements at e23dabe, its successor 32d1c0a5, and 2d3eea20
all showed the same S1/U1/U3 errors. The last commit introduced DIF_DIRTY,
but it did not introduce these fixed-case failures: the older implementation
also omitted the necessary initialization through a different code path.
Full commit IDs and measurements are in [summary.json](summary.json).

## Measured BOE comparisons

| Pair | Target / GCC O0 result | Raw BOE verdict | Authorization |
|---|---|---|---|
| [P1_H1_baseline](evidence/P1_H1_baseline.json) | 10 / 0 | NEQ | Static-path candidate, stable executable replay, live binary identity check |
| [P2_union_baseline](evidence/P2_union_baseline.json) | 42 / 0 | NEQ | Same NEQ confirmation route; the unqualified memset external model prevents EQ eligibility |
| [P3_H1_patched](evidence/P3_H1_patched.json) | 0 / 0 | EQ | Complete eligible path bijection and exact-identity proof; zero SMT queries |

Each pair has one complete terminating path on each side. P1 and P2 each
have two directional confirmation records for the same empty input
assignment. They are not two distinct inputs. Both had zero SMT UNKNOWNs;
each audited ten queries, including candidate revalidation.

The contract is int snippet(void), represented to BOE as int(void), with
empty input schema, one initialized call, and a 32-bit int return value.
S1 observes b; U3 observes c[0]. No dummy input, volatile qualifier, extra
initialization, or hard-coded result was added. Each ELF retains its own
loader-provided static data; replacing the differing initial values would
erase H1. The common [driver](driver.c) prints the entry's return value.

This is a coverage check performed after source analysis and concrete
differential execution identified the candidates. It is not a claim that
BOE autonomously discovered two new compiler defects. The EQ statement is
limited to this adapted return-value contract, not all behavior of the
original printf programs or arbitrary input spaces.

The recorded method files match the minimal repository's existing method
snapshot. [method_snapshot.json](method_snapshot.json) records the measured
hashes. The run used angr/claripy 9.2.192 and Z3 4.12.2, with no method changes.

## Compiler and environment pins

| Role | Pinned identity |
|---|---|
| TinyCC baseline | 0.9.28rc, commit ce2a61d9cdbaac6dda53095cf501e39182b481c9 |
| TinyCC diagnostic build | The same commit plus patches/h1_static_zero.patch; not an upstream release |
| Reference | GCC 12.2.0, GNU ld 2.40 |
| Target | x86-64 Linux, System V AMD64 ABI, LP64 |
| C mode | gnu11 |
| TinyCC options | -fno-asynchronous-unwind-tables; default code generation |
| GCC reference | -O0 -fno-pie; -O2 was only a concrete admission cross-check |
| Link | GCC -no-pie with the common GCC-built driver |

The baseline compiler SHA256 is
cb5f2a887cef742d53df23467abc0e0192b11e286a5728d50947a943e3463b4a.
The diagnostic compiler SHA256 is
c4636aa1f81ea163333fc1a6db71af3852df1bdf7a4f55cf88ae15a3a5c570fd.
These identify the archived builds; rebuilding under another host compiler
or environment may change binary hashes.

The unwind-table option avoids a separately observed linker problem. That
linker issue is not counted among the wrong-code findings here.

## Reproduce the concrete comparisons

Use Bash in the Linux analysis environment described in the repository's
[main README](../../README.md), with GCC 12.2.0, GNU make, Git, and the BOE
dependencies available. Start at the repository root and use a fresh work
directory. Compiler source trees and generated ELF files are not shipped.

First build the pinned original and diagnostic compilers:

    set -eu
    REPO_ROOT="$PWD"
    CASE_DIR="$REPO_ROOT/benchmark/compiler_initializers"
    WORK="$REPO_ROOT/work/compiler-initializers"
    mkdir -p "$WORK"
    git clone --no-checkout https://repo.or.cz/tinycc.git "$WORK/tinycc-baseline"
    git -C "$WORK/tinycc-baseline" checkout --detach ce2a61d9cdbaac6dda53095cf501e39182b481c9
    git clone --no-hardlinks --no-checkout "$WORK/tinycc-baseline" "$WORK/tinycc-h1"
    git -C "$WORK/tinycc-h1" checkout --detach ce2a61d9cdbaac6dda53095cf501e39182b481c9
    git -C "$WORK/tinycc-h1" apply "$CASE_DIR/patches/h1_static_zero.patch"
    for tree in "$WORK/tinycc-baseline" "$WORK/tinycc-h1"; do
        (
            cd "$tree"
            ./configure --cc=gcc
            make -j2
        )
    done
    TCC_BASELINE="$WORK/tinycc-baseline/tcc"
    TCC_H1="$WORK/tinycc-h1/tcc"

Compile the common driver once, then the seven concrete configurations.
The same adapted source is used by every compiler for a given case:

    gcc -std=gnu11 -O0 -fno-pie -c "$CASE_DIR/driver.c" -o "$WORK/driver.o"
    for case_id in S1 U3; do
        mkdir -p "$WORK/$case_id"
        for opt in 0 2; do
            gcc -std=gnu11 -O"$opt" -fno-pie -c "$CASE_DIR/$case_id/adapted.c" -o "$WORK/$case_id/gcc-o$opt.o"
            gcc -no-pie "$WORK/$case_id/gcc-o$opt.o" "$WORK/driver.o" -lm -o "$WORK/$case_id/gcc-o$opt"
        done
        "$TCC_BASELINE" -std=gnu11 -I "$WORK/tinycc-baseline/include" -fno-asynchronous-unwind-tables -c "$CASE_DIR/$case_id/adapted.c" -o "$WORK/$case_id/tcc-baseline.o"
        gcc -no-pie "$WORK/$case_id/tcc-baseline.o" "$WORK/driver.o" -lm -o "$WORK/$case_id/tcc-baseline"
    done
    "$TCC_H1" -std=gnu11 -I "$WORK/tinycc-h1/include" -fno-asynchronous-unwind-tables -c "$CASE_DIR/S1/adapted.c" -o "$WORK/S1/tcc-h1.o"
    gcc -no-pie "$WORK/S1/tcc-h1.o" "$WORK/driver.o" -lm -o "$WORK/S1/tcc-h1"
    for program in "$WORK/S1/gcc-o0" "$WORK/S1/gcc-o2" "$WORK/S1/tcc-baseline" "$WORK/S1/tcc-h1" "$WORK/U3/gcc-o0" "$WORK/U3/gcc-o2" "$WORK/U3/tcc-baseline"; do
        for trial in 1 2 3; do
            "$program"
        done
    done

In that order the seven programs should print 0, 0, 10, 0, 0, 0, and 42,
each repeated three times. This is the 21-run admission comparison.

For the original printf reproductions, compile any original.c file as the
complete program without driver.c. S1 prints a=2 and b=10 with the baseline
and b=0 with GCC or the diagnostic build. U1 and U3 print 42 0 1 0 with the
baseline, whereas GCC prints 0 0 1 0.

## Run the three BOE comparisons

Continue from the repository root in the same shell. Only GCC O0 enters
these pairs. The numeric profile imposes no argument bounds on an empty
input schema. Each output directory must be new.

    run_initializer_pair() {
        python scripts/run_current_method.py \
            --old-binary "$WORK/$2/$3" \
            --new-binary "$WORK/$2/gcc-o0" \
            --old-source "$CASE_DIR/$2/adapted.c" \
            --new-source "$CASE_DIR/$2/adapted.c" \
            --old-compiler "$4" \
            --new-compiler 'GCC 12.2.0, -std=gnu11 -O0 -fno-pie; GCC -no-pie link' \
            --signature 'int(void)' \
            --domain-profile-json configs/compiler_wrongcode_full_type_v1.json \
            --pair-id "$1" \
            --out-dir "$WORK/boe/$1"
    }
    run_initializer_pair P1_H1_baseline S1 tcc-baseline 'TinyCC ce2a61d9cdbaac6dda53095cf501e39182b481c9; GCC -no-pie link'
    run_initializer_pair P2_union_baseline U3 tcc-baseline 'TinyCC ce2a61d9cdbaac6dda53095cf501e39182b481c9; GCC -no-pie link'
    run_initializer_pair P3_H1_patched S1 tcc-h1 'TinyCC ce2a61d9cdbaac6dda53095cf501e39182b481c9 plus local H1 diagnostic patch; GCC -no-pie link'

The existing runner uses initialized single-entry execution, static
candidates, mandatory artifact identity, and executable NEQ confirmation.
Limits are 60 seconds internal / 75 seconds external and 5 GiB per SE
process, 128 paths, loop bound 30; verification uses B10Z50, 5000 ms per
query, 120 seconds external, and 4 GiB. No expected verdict or admission
output is passed to the method. The summary JSON is reporting data, not
an input to the runner.

The measured outcomes were NEQ, NEQ, and EQ. Any differing rerun outcome
should be retained with its configuration and evidence, not overwritten
with these expected labels.

## Evidence and integrity

[summary.json](summary.json) contains the compiler pins, all seven admission
results, original ELF hashes, historical version matrix, search status,
and the three BOE outcomes. The three evidence JSON files retain selected
raw verdict, authorization, path-return, identity, and stable-replay fields.
Each identifies the original archived report by SHA256.

These are compact evidence extracts. Full compiler archives, ELF files,
raw path summaries, and SMT logs remain outside this minimal repository.
Hash references identify the recorded experiment; the reproduction commands
above are a portable rendering of its build and method configuration.

To check the bundled files:

    (
        cd benchmark/compiler_initializers
        sha256sum -c SHA256SUMS
    )
