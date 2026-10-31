# Verilator warning codes - meaning, risk, fix

| Code | Risk | Meaning | Typical fix |
|---|---|---|---|
| LATCH | Bug | Combinational block does not assign a variable on every path | Default assignment at top of `always_comb`, or complete `if/else`/`case` with `default` |
| CASEINCOMPLETE | Bug/Risk | `case` does not cover all values | Add `default:`; use `unique case` only if the cases are truly exhaustive |
| BLKSEQ | Bug | Blocking `=` in clocked block | Use `<=` in `always_ff`; blocking only for local temporaries |
| COMBDLY | Bug | Non-blocking `<=` in combinational block | Use `=` in `always_comb` |
| MULTIDRIVEN | Bug | Variable assigned in more than one always block | Merge into one process or split the variable |
| UNOPTFLAT | Risk | Apparent combinational loop (may be bit-level false loop) | Split vector, or break real loop with a register |
| ALWCOMBORDER | Bug | `always_comb` reads variable before it is written | Reorder assignments |
| WIDTHTRUNC / WIDTHEXPAND / WIDTH | Bug when arithmetic, else Risk | Operand widths differ | Size explicitly: `8'(x)`, `{carry, sum} = a + b`, zero-extend intentionally |
| IMPLICIT | Risk | Implicit net created (often a typo) | Declare the net; add `` `default_nettype none `` to every file |
| PINMISSING / PINCONNECTEMPTY | Risk | Port not connected | Connect, or tie off explicitly `.port()` with a comment |
| SYNCASYNCNET | Risk | Net used as both sync and async reset | Pick one reset style per flop group |
| CMPCONST | Risk | Comparison is constant | Usually a width bug |
| SELRANGE | Bug | Bit select out of range | Fix index width / parameter |
| UNSIGNED | Risk | `x >= 0` on unsigned, always true | Remove or make signed |
| UNUSEDSIGNAL / UNUSEDPARAM / UNDRIVEN | Noise/Risk | Dead or floating logic | Remove, or waive debug signals locally |
| DECLFILENAME / EOFNEWLINE | Noise | Style | Waive |
| TIMESCALEMOD | Risk | Mixed timescale across files | Add `` `timescale `` consistently or none at all |

Scoped waiver (preferred over command-line `-Wno-`):

```systemverilog
/* verilator lint_off UNUSEDSIGNAL */
logic [31:0] dbg_bus;   // observed only in waveforms
/* verilator lint_on UNUSEDSIGNAL */
```
