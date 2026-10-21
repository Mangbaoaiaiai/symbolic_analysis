# UB heuristic audit

| Metric | Result |
|---|---:|
| Correct | 58/62 |
| Correct EQ | 29/33 |
| Correct NEQ | 29/29 |
| Wrong | 0 |
| UNK | 4 |
| Unknown status treated as NEQ | 0 |

## Definedness events

| Classification | Logical witnesses |
|---|---:|
| `asymmetric_ub_like` | 2 |
| `defined_neq` | 27 |

## Per-case outcomes

| Case | Label | Verdict | Status | Audit checks | Rejected | Reason |
|---|---|---|---|---:|---:|---|
| `airy/MAX_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `airy/MAX_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `airy/Sign_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `airy/Sign_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `bess/bessi0_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `bess/bessi0_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `bess/bessi1_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `bess/bessj0_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `bess/bessj0_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `bess/bessj1_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `bess/probks_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `bess/SIGN_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `bess/SIGN_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `bess/SQR_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `bess/bessi_Eq` | EQ | UNK | UNK | 0 | 0 | symbolic execution timed out |
| `bess/bessj_Eq` | EQ | UNK | UNK | 0 | 0 | symbolic execution timed out |
| `bess/bessk_Eq` | EQ | UNK | UNK | 0 | 0 | symbolic execution produced no complete paths |
| `bess/bessy_Eq` | EQ | UNK | UNK | 0 | 0 | symbolic execution produced no complete paths |
| `caldat/julday_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `caldat/julday_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `dart/test_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `dart/test_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `ell/plgndr_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `ell/plgndr_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `gam/ei_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `gam/ei_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `gam/factrl_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `gam/factrl_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/Add_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/Comp_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/Const_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopMult10_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopMult10_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopMult15_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopMult15_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopMult2_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopMult2_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopMult20_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopMult20_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopMult5_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopMult5_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopSub_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopSub_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopUnreach10_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopUnreach10_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopUnreach15_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopUnreach15_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopUnreach2_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopUnreach2_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopUnreach20_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopUnreach20_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/LoopUnreach5_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/LoopUnreach5_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `CLEVER/Sub_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/UnchLoop_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `CLEVER/UnchLoop_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `pow/test_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `pow/test_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `ran/gammln_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `ran/gammln_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
| `ran/ranzero_Eq` | EQ | EQ | CORRECT | 0 | 0 |  |
| `ran/ranzero_NEq` | NEQ | NEQ | CORRECT | 1 | 0 |  |
