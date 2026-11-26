[Evaluation](#evaluation)

# Symbolicana Experimental Results

This README reports the current measured outcomes for the fixed 62-case
benchmark and the complete 272-entry OSF accounting.

## Quick start

Build the pinned analysis image and run the test suite:

```bash
python run_experiment.py --suite tests --rebuild
```

Run the fixed 62-case experiment with a fresh path cache:

```bash
python run_experiment.py \
  --suite paper \
  --bindiff \
  --fresh \
  --run-name paper_latest
```

Run the complete 272-entry OSF experiment:

```bash
python run_experiment.py \
  --suite osf \
  --fresh \
  --run-name osf_latest
```

`--bindiff` selects the optional graph-reranking image. If it is unavailable,
the runner falls back to feature-only ranking and records that fallback.
Generated binaries and paths are written below `work/`; rerun summaries are
written below `results/rerun/<run-name>/`.

## Evaluation

### Experimental scope

| Item | Current setting |
|---|---|
| Fixed benchmark | 62 cases: 33 EQ and 29 NEQ |
| Fixed input domain | Integers and floats in `[-100,100]`; Ell uses `[0,10]` and `[-1,1]` |
| OSF input domain | Complete signed 32-bit and floating-point SMT bit-vector spaces |
| Compilation | GCC 12.2, x86-64, `-O3` |
| Symbolic execution | angr/claripy 9.2.192 |
| Solver | Z3 4.12.2 |
| SMT timeout | 60 seconds per query |
| Loop bound | 30 completed iterations |

### Difference from the paper

The current fixed-benchmark result is `58/62`, while the paper reports
`54/62`. This difference has three concrete causes.

First, the execution environment differs. The paper reports a 32-core Intel
Xeon 2.5 GHz machine with 64 GB RAM on Ubuntu 22.04. The recorded runs here use
Docker Linux containers on an x86-64 Docker Desktop/WSL2 host with 16 logical
CPUs and about 16 GB exposed to Docker. Symbolic-execution wall-clock limits
therefore admit a different set of complete paths.

Second, the paper does not state a fixed numeric interval for symbolic inputs.
The fixed 62-case profile uses the same integer and floating-point assumption
as the upstream ARDiff runner, `[-100,100]`, with Ell overrides `[0,10]` and
`[-1,1]`. The complete OSF profile instead uses the full representable 32-bit
SMT input spaces. These domains change path feasibility and path counts, so
the two result sets are not directly interchangeable.

Third, the implementation has engineering improvements that affect evidence
quality: ordered standard output is part of the observable state, formatted
floating-point output is serialized by IEEE bit pattern, 64-bit ABI values are
preserved, infeasible paths are removed by a bounded conservative prefilter,
path summaries are streamed to disk, and unconstrained paths recover their
complete input arity. The latest verifier also resolves several cases that the
paper reports as SMT-UNK. These changes are reported explicitly and are not
converted into correct results when path evidence remains incomplete.

## 1. Main fixed 62-case result

| Metric | Result |
|---|---:|
| Correct determinate | **58/62 (93.55%)** |
| Correct EQ | **29/33 (87.88%)** |
| Correct NEQ | **29/29 (100.00%)** |
| Wrong EQ / NEQ | **0** |
| UNK | **4** |

Per-family results:

| Family | Cases | Correct | UNK |
|---|---:|---:|---:|
| CLEVER | 28 | 28 | 0 |
| airy | 4 | 4 | 0 |
| bess | 14 | 10 | 4 |
| caldat | 2 | 2 | 0 |
| dart | 2 | 2 | 0 |
| Ell | 2 | 2 | 0 |
| gam | 4 | 4 | 0 |
| power | 2 | 2 | 0 |
| Ran | 4 | 4 | 0 |

The four UNK cases are:

| Case | Reason |
|---|---|
| `bess/bessi_Eq` | Symbolic-execution timeout |
| `bess/bessj_Eq` | Symbolic-execution timeout |
| `bess/bessk_Eq` | No complete symbolic paths |
| `bess/bessy_Eq` | No complete symbolic paths |

The 58 analyzed cases include 29 correct EQ, 29 correct NEQ, and no incorrect
EQ/NEQ result. The four remaining cases are excluded only from the denominator
for timing and ranking metrics; they remain UNK in the verdict denominator.


### Column definitions

| Label | Definition |
|---|---|
| `Case` | Official benchmark case identifier. |
| `Family` | Benchmark family assigned by the benchmark manifest. |
| `Cases` | Number of official entries in the family; the full OSF denominator is 272. |
| `Configuration` | One experimental variant under comparison. |
| `Metric` | Aggregate quantity measured by a result table. |
| `Result` | Value produced by the current run. |
| `Outcome` | Final verdict/audit category assigned to one case. |
| `Reason` | Residual condition that prevented a more specific result. |
| `File` | Path-free or path-only result artifact linked by the README. |
| `Supported` | Entries for which a source-free harness could be generated and staged. |
| `Complete` | Entries whose old and new executions both produced path artifacts and completed exploration. |
| `Correct EQ` | The verdict is EQ and also matches the official EQ label. |
| `Correct NEQ` | The verdict is NEQ and also matches the official NEQ label. |
| `Correct determinate` | Correct EQ plus correct NEQ outcomes. |
| `Correct / 62` | Number of correct determinate verdicts over the fixed 62-case denominator. |
| `Correct rate` | Correct determinate verdicts divided by all 62 cases. |
| `Wrong EQ` | Determinate EQ verdicts for cases labelled NEQ. |
| `Wrong NEQ` | Determinate NEQ verdicts for cases labelled EQ. |
| `Difference` | Current full configuration minus the comparison configuration. |
| `Label inconsistent` | The released sources contradict the official label, so the row is excluded from correct/wrong counts. |
| `UB` | Final exclusion because source-level undefined behavior or unstable formatting prevents a trustworthy verdict. |
| `Undefined behavior excluded` | Long-form label for the `UB` outcome column. |
| `UNK` | The method declined to decide because evidence was incomplete or no proof was reached; UNK is not a wrong verdict. |
| `Failed` | Harness construction, symbolic execution, or another process stage failed before a verdict. |
| `Not attempted` | No harness could be constructed, including unsupported pointer/array signatures. |
| `Not attempted / unsupported` | Long-form label for entries with no executable harness. |
| `Entered symbolic execution` | At least one side started symbolic execution and produced path evidence. |
| `Both-side path artifacts` | Both binaries produced at least one path artifact, regardless of completeness. |
| `Both-side complete exploration` | Both sides have complete exploration markers, path artifacts, and no failure marker. |
| `Incomplete exploration` | Some path evidence exists, but at least one side does not have complete exploration. |
| `No path artifact` | Neither side produced a usable path artifact. |
| `Timed cases` | Cases with a recorded verifier wall-clock duration. Path- or verifier-failed cases without a duration are not imputed. |
| `Mean verifier time / timed case` | Arithmetic mean of `evaluation_wall_seconds` over `Timed cases` only; expressed in seconds. |
| `symbolic_timeout` | Symbolic execution exceeded its configured wall-clock limit. |
| `sigkill_or_oom` | The executor was terminated by SIGKILL, usually because of memory exhaustion. |
| `incomplete_symbolic_execution` | Exploration stopped with an incomplete path set. |
| `verifier_or_semantic_unknown` | Complete paths were available, but no trustworthy semantic proof was reached. |
| `no_complete_paths` | Symbolic execution produced no complete terminating path. |
| `unsupported_harness` | The source signature could not be represented by the source-free harness. |

## 3. Complete OSF evaluation

All 272 entries use the same complete-input-space profile. The table below is
the strict audit of the current run, including every generation retry and
verification attempt.

| Outcome | Cases |
|---|---:|
| Correct EQ | **72** |
| Correct NEQ | **72** |
| **Correct determinate** | **144** |
| Wrong EQ | 0 |
| Wrong NEQ | 0 |
| Label inconsistent | 5 |
| Undefined behavior excluded | 3 |
| UNK | 43 |
| Failed | 76 |
| Not attempted / unsupported | 1 |
| **Total** | **272** |

Coverage and failure accounting:

| Metric | Cases |
|---|---:|
| Supported / staged | 271 |
| Entered symbolic execution | 195 |
| Both-side path artifacts | 180 |
| Both-side complete exploration | 165 |
| Incomplete exploration | 30 |
| No path artifact | 76 |
| `symbolic_timeout` | 26 |
| `sigkill_or_oom` | 63 |
| `incomplete_symbolic_exploration` | 15 |
| `verifier_or_semantic_unknown` | 13 |
| `no_complete_paths` | 2 |
| `unsupported_harness` | 1 |

The only unsupported entry is `REVE/average_Eq`; its source declares `int a[]`
without an array extent.

Per-family OSF results:

| Family | Cases | Supported | Complete | Correct EQ | Correct NEQ | Wrong EQ | Wrong NEQ | Label inconsistent | UB | UNK | Failed | Not attempted | Timed cases | Mean verifier time / timed case (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| airy | 12 | 12 | 10 | 3 | 5 | 0 | 0 | 1 | 0 | 3 | 0 | 0 | 9 | 1.612 |
| bess | 36 | 36 | 24 | 9 | 12 | 0 | 0 | 1 | 0 | 7 | 7 | 0 | 23 | 19.775 |
| caldat | 10 | 10 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 8 | 0 | 2 | 0.772 |
| CLEVER | 50 | 50 | 50 | 27 | 20 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 50 | 1.911 |
| dart | 2 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 1.350 |
| ej_hash | 12 | 12 | 12 | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 0.873 |
| ell | 26 | 26 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 24 | 0 | 2 | 9.092 |
| frenel | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 0 | 0 | NA |
| gam | 24 | 24 | 11 | 4 | 5 | 0 | 0 | 0 | 0 | 4 | 11 | 0 | 11 | 59.246 |
| optimization | 6 | 6 | 6 | 2 | 2 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 6 | 205.246 |
| pow | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.622 |
| ran | 22 | 22 | 5 | 3 | 2 | 0 | 0 | 0 | 0 | 3 | 14 | 0 | 6 | 0.915 |
| raytrace | 12 | 12 | 12 | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 0.998 |
| REVE | 32 | 31 | 9 | 5 | 2 | 0 | 0 | 0 | 1 | 17 | 6 | 1 | 14 | 0.578 |
| sine | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 45.889 |
| statcalc | 2 | 2 | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.570 |
| tcas | 8 | 8 | 6 | 0 | 3 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 6 | 24.046 |
| tsafe | 8 | 8 | 8 | 2 | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 8 | 225.360 |
| **All** | **272** | **271** | **165** | **72** | **72** | **0** | **0** | **5** | **3** | **43** | **76** | **1** | **169** | **26.910** |

`NA` means that no case in that family had a recorded verifier wall time. The
overall mean is computed over all 169 timed cases, not as an unweighted mean of
the family means.

### Path-matching type distribution

`Records` counts accepted source-path records. `Four-class share` is the share
of those accepted records. `Target links` counts target paths covered after
one-to-many expansion, so it can be larger than `Records`.



Full multi-target union configuration:

| Match Type | Records | Four-class share | Target links |
|---|---:|---:|---:|
| One-to-one exact | 906 | 71.56% | 906 |
| One-to-one source-subset-target | 185 | 14.61% | 185 |
| One-to-many exact cover | 36 | 2.84% | 86 |
| One-to-many source-subset-target union | 139 | 10.98% | 859 |
| **Four-class total** | **1,266** | **100.00%** | **2,036** |

Percentages are rounded to two decimals; displayed components can differ from
100.00% by 0.01% due to rounding.

## Result files

| Result | File |
|---|---|
| Fixed 62 per-case outcomes | [`results/paper/cases.csv`](results/paper/cases.csv) |
| Fixed 62 summary | [`results/paper/summary.json`](results/paper/summary.json) |
| Fixed 62 definedness audit | [`results/paper/summary.md`](results/paper/summary.md) |
| Complete OSF per-case outcomes | [`results/osf/cases.csv`](results/osf/cases.csv) |
| Complete OSF summary | [`results/osf/summary.json`](results/osf/summary.json) |
| Complete OSF family table | [`results/osf/family_summary.csv`](results/osf/family_summary.csv) |
| Complete OSF failure table | [`results/osf/failure_cases.csv`](results/osf/failure_cases.csv) |
| Complete OSF label audit | [`results/osf/label_audit.csv`](results/osf/label_audit.csv) |

## Current method snapshot — 2026-11-11

The symbolic executor, equivalence verifier, and their local runtime dependencies
now match the method used in `compiler_wrongcode_20261111/run1`, after the
historical-UNKNOWN accounting update. File hashes are recorded in
[`configs/current_method_snapshot.json`](configs/current_method_snapshot.json).
The historical evaluation tables and result files above have not been changed
or regenerated. Their configurations describe those recorded experiments;
they are not measurements of this new snapshot. Historical benchmark/ranking
orchestration is retained for compatibility.

The current method includes shared input-domain contracts, ELF/source/artifact
identity checks, static candidate provenance and repeated binary replay,
fixed-runtime external-math evidence, initialized single-entry execution,
loop/model evidence checks, and separation of historical solver UNKNOWN events
from unresolved final proof obligations. The solver stack is angr/claripy
9.2.192, Z3 4.12.2, and Bitwuzla 0.9.1.

For the measured configuration, use the Linux entry point
[`scripts/run_current_method.py`](scripts/run_current_method.py) with two
already compiled ELF programs and their actual source files. For example,
after building the C02 source with the pinned compilers listed below:

```bash
python scripts/run_current_method.py \
  --old-binary work/c02_chibicc --new-binary work/c02_gcc \
  --old-source benchmark/compiler_wrongcode/C02_bitfield_assignment.c \
  --new-source benchmark/compiler_wrongcode/C02_bitfield_assignment.c \
  --old-compiler 'chibicc 90d1f7f199cc55b13c7fdb5839d1409806633fdb, default code generation; GCC -no-pie link' \
  --new-compiler 'GCC 12.2.0, -std=c11 -O0 -fno-pie; -no-pie link' \
  --signature 'long(unsigned int)' \
  --domain-profile-json configs/compiler_wrongcode_full_type_v1.json \
  --pair-id C02_bitfield_assignment --out-dir work/current_c02
```

Use a new output directory for each attempt. The runner executes serially with
60 seconds internal / 75 seconds external and 5 GiB per SE process, at most
128 paths and loop bound 30; verification uses B10Z50, 5 seconds per query,
120 seconds external and 4 GiB. It enables `--initialized-entry`,
`--fixed-math-runtime`, `--static-only`, `--naive`, full SMT audit, and mandatory
artifact identity checks. No known witness or expected verdict is supplied to
the method, and no automatic budget escalation occurs. The wrapper records
caller-supplied build descriptions and verifies artifact identity; it does not
independently prove which compiler produced an arbitrary supplied ELF.

**Known limitations of this measured snapshot:** AMD64 `long` input arguments
can be truncated through 32-bit argument registers, and non-floating `long`
returns are read through `eax`. Differences confined to the upper 32 bits can
therefore produce false EQ. Both limitations remain explicitly covered by
expected-failure tests in
[`tests/test_current_abi_limitations.py`](tests/test_current_abi_limitations.py).
No post-experiment ABI fix is included in this update. A successful concrete
NEQ replay does not establish that the complete 64-bit domain was modeled
correctly. The deployed loop limit counts binary loop trips, which need not
equal the number of source-level iterations after optimization.

## Eight confirmed compiler wrong-code bugs

These are **known upstream bugs independently reproduced and detected by the
method**, not newly discovered compiler vulnerabilities. Each pair compiles
the same C source for **x86-64 Linux, System V AMD64 ABI, LP64**. All eight NEQ
cases were confirmed by actual binary execution. The table lists the eight
successful detections from the frozen ten-case experiment, not an eight-case
accuracy denominator. The full run had eight NEQ and two false EQ; the latter
exposed the return-width limitation described above.

Compiler versions used:

| Role | Compiler and pinned version |
|---|---|
| Target for C01, C02, C04, C05, C07, C09, C10 | **chibicc**, commit `90d1f7f199cc55b13c7fdb5839d1409806633fdb` |
| Target for C08 | **slimcc**, commit `8148979457ddcdb71f670c24e687ebd1199c3899` |
| Reference for every pair | **GCC 12.2.0**, Debian `12.2.0-14+deb12u1`, `-std=c11 -O0 -fno-pie` |

Targets used default code generation; both object files were linked through
GCC with `-no-pie`. These are cross-compiler comparisons, not optimization-level
comparisons. TinyCC was examined during preparation, but no TinyCC bug is
claimed in this successful set.

| Case and source | Target compiler | Bug mechanism | Method witness | Target result | GCC result | Upstream evidence |
|---|---|---|---|---:|---:|---|
| [C01](benchmark/compiler_wrongcode/C01_switch64.c) | chibicc | 64-bit switch label `0x100000000L` is truncated to zero | `v = 0` | 2 | 1 | [chibicc #175](https://github.com/rui314/chibicc/issues/175) |
| [C02](benchmark/compiler_wrongcode/C02_bitfield_assignment.c) | chibicc | A 3-bit unsigned bit-field assignment expression returns the original value instead of the converted value | `v = 4294967288` | 4294967288 | 0 | [chibicc #175](https://github.com/rui314/chibicc/issues/175) |
| [C04](benchmark/compiler_wrongcode/C04_bool_initializer.c) | chibicc | `_Bool g = 256` is initialized to zero instead of one | No arguments | 0 | 1 | [chibicc #175, comment](https://github.com/rui314/chibicc/issues/175#issuecomment-6204519490) |
| [C05](benchmark/compiler_wrongcode/C05_bool_bitfield.c) | chibicc | Reading a one-bit `_Bool` field incorrectly sign-extends one to minus one | `v = 1` | -1 | 1 | [chibicc #175, comment](https://github.com/rui314/chibicc/issues/175#issuecomment-6204519490) |
| [C07](benchmark/compiler_wrongcode/C07_unary_promotion.c) | chibicc | Unary plus fails to promote `char` to `int` in `sizeof(+c)` | No arguments | 1 | 4 | [chibicc #169](https://github.com/rui314/chibicc/issues/169) |
| [C08](benchmark/compiler_wrongcode/C08_shift_constant_width.c) | slimcc | Constant folding of `3U << 31 >> 31` fails to preserve 32-bit unsigned width | No arguments | 3 | 1 | [slimcc #43](https://github.com/fuhsnn/slimcc/issues/43) |
| [C09](benchmark/compiler_wrongcode/C09_fp_logical_constant.c) | chibicc | Floating constant logical AND `0.5 && 0.3` evaluates to zero | No arguments | 0 | 1 | [slimcc #63](https://github.com/fuhsnn/slimcc/issues/63), reproduced in pinned chibicc |
| [C10](benchmark/compiler_wrongcode/C10_fp_narrow_constant.c) | chibicc | `(float)16777217.0` omits binary32 precision narrowing before integer initialization | No arguments | 16777217 | 16777216 | [slimcc #56](https://github.com/fuhsnn/slimcc/issues/56), reproduced in pinned chibicc |

C01 and C02 were detected using inputs different from the admission witnesses.
C02's original replay text was `-8`, encoding BV32 `0xfffffff8`; independent
replay with the canonical unsigned decimal `4294967288` confirmed the same
difference. Parameterless cases have an empty input assignment as their
witness. C09/C10 are compile-time floating-point errors manifested as constant
integer results, not demonstrations of complex runtime floating-point proofs.
C10 uses the shared binary32/default round-to-nearest-even environment.

Machine-readable compiler commits, source and ELF hashes, method witnesses,
and confirmed outputs are in
[`benchmark/compiler_wrongcode/confirmed_bugs.json`](benchmark/compiler_wrongcode/confirmed_bugs.json).
The source reproducers are included; compiler source archives and generated
binaries are excluded from this minimal repository. These small, loop-free
examples do not measure coverage of complex optimizer or interprocedural bugs.

## TinyCC initializer findings — 2026-11-26

Two initializer behavior groups were investigated using **TinyCC 0.9.28rc**,
commit **ce2a61d9cdbaac6dda53095cf501e39182b481c9**, against **GCC 12.2.0**
on x86-64 Linux. Source analysis and concrete differential execution identified
the candidates; the unchanged BOE method was then evaluated on them.

| Finding and reproducer | Mechanism | Public-record status |
|---|---|---|
| [H1: static aggregate reinitialization](benchmark/compiler_initializers/S1/original.c) | A later whole-element initializer omits a previously nonzero member. The static zeroing branch does not clear its old section bytes, leaving b=10 instead of b=0. | Confirmed implementation error; no matching record found in the bounded search. First discovery and independence from related reports are not claimed. |
| [Union member switching](benchmark/compiler_initializers/U3/original.c) | A chained initializer switches union members but retains old bytes, producing 42 0 1 0 instead of 0 0 1 0. | [Savannah #68807](https://savannah.nongnu.org/bugs/?func=detailitem&item_id=68807) reports the file-scope form. This automatic-object variant is grouped with that known problem, not counted as a new independent bug. |

H1 has a [local diagnostic patch](benchmark/compiler_initializers/patches/h1_static_zero.patch)
that restores static clearing in the tested cases. It is not an upstream fix
or a general production-ready patch. A seven-query mechanism search and the
reused fourteen-query archive found no clear H1 match; this is a bounded
prior-report check, not proof that no earlier report exists.

The three recorded BOE comparisons use the same adapted C source on both
sides, no arguments, each ELF's own initialized global data, and a 32-bit int
return-value contract:

| Pair | Target compiler | GCC O0 reference | BOE result | Evidence |
|---|---|---|---|---|
| H1 before the diagnostic patch | TinyCC: 10 | 0 | **NEQ** | [Static candidate and confirmed executable replay](benchmark/compiler_initializers/evidence/P1_H1_baseline.json) |
| Union automatic-object variant | TinyCC: 42 | 0 | **NEQ** | [Confirmed executable replay](benchmark/compiler_initializers/evidence/P2_union_baseline.json); the unqualified memset model blocks EQ eligibility |
| H1 after the diagnostic patch | Locally patched TinyCC: 0 | 0 | **EQ** | [Complete eligible path-identity proof](benchmark/compiler_initializers/evidence/P3_H1_patched.json) |

There were two adapted programs, seven concrete admission configurations,
21 admission runs, six independent symbolic executions, and three verifier
processes. BOE confirmation replays are additional to the admission runs.
Each NEQ pair has one empty-input witness, recorded in two directions.
The EQ result applies to the adapted single-call return-value contract, not
to all observable behavior of the original printf programs. These small,
parameterless cases do not measure complex input-space search or overall
accuracy.

The [reproduction guide](benchmark/compiler_initializers/README.md) includes
original and adapted sources, the common driver, pinned compiler information,
and commands for all three BOE comparisons.
[Machine-readable results](benchmark/compiler_initializers/summary.json)
and the [recorded method hashes](benchmark/compiler_initializers/method_snapshot.json)
identify the measured run. Compiler trees, ELF binaries, and raw solver logs
are excluded from this minimal package.
