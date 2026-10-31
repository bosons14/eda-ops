---
name: rtl-review
description: >
  This skill should be used when the user asks to "lint my RTL", "review this Verilog/SystemVerilog",
  "check if this is synthesizable", "find bugs in this module", "check CDC", "why is there a latch",
  or runs /rtl-review. Covers lint triage, synthesizability, reset/clocking style, clock-domain
  crossings and simulation/synthesis mismatch risks for Verilog and SystemVerilog designs.
metadata:
  version: "0.1.0"
---

# RTL review

Review RTL the way a senior design engineer does at a pre-merge review: tool evidence first, then
engineering judgement. Never report a lint warning without saying whether it is a real silicon risk.

## Procedure

1. **Scope the design.** Identify the source files, the top module and any `.f` filelist, include
   directories and defines. If the user names only a directory, glob `*.v`/`*.sv` and pick the top by
   finding the module no one instantiates. Call `eda_tool_status` once if the environment is unknown.
2. **Run the linter.** Call `lint_rtl` (eda-ops MCP) with the files/filelist and `top`. With no linter
   installed, fall back to a careful manual read and say the review is unaided by tools.
3. **Triage every diagnostic** into one of:
   - **Bug** - changes silicon behaviour or causes sim/synth mismatch (latch, BLKSEQ, COMBDLY,
     MULTIDRIVEN, width truncation on arithmetic, incomplete case without default, combinational loop).
   - **Risk** - legal but fragile (implicit nets, unconnected ports, mixed reset styles).
   - **Noise** - style or intentional (unused debug signals, DECLFILENAME). Propose a targeted waiver
     (`/* verilator lint_off CODE */` scoped to lines), never a global `-Wno-`.
   Read `references/verilator-codes.md` for the meaning and fix of each common code.
4. **Review beyond lint.** Read the RTL itself for issues linters miss:
   - Clock-domain crossings: any signal launched in one clock and captured in another. Apply
     `references/cdc-patterns.md` - single-bit needs a 2-flop synchronizer, multi-bit needs gray code,
     handshake or async FIFO; never synchronize a binary bus bit-by-bit.
   - Reset: async assert / sync de-assert, consistent polarity, no reset on datapath flops where not
     needed (area), reset synchronizer present per domain.
   - FSMs: default state, unreachable/illegal state recovery, one-hot vs binary intent.
   - Arithmetic: signed/unsigned mixing, carry-out dropped, `$clog2` edge cases (DEPTH=1, non power of 2).
   - Synthesizability: `initial` blocks in RTL (FPGA-only), delays, `$display` in synthesizable code,
     unbounded loops, real types.
5. **Confirm structurally when useful.** For suspected latches or multi-drivers, call `synthesize` on
   the module; Yosys reports inferred latches and driver conflicts definitively.
6. **Fix when asked.** Make minimal edits that preserve intent, then re-run `lint_rtl` and show the
   before/after counts. If a testbench exists, run `simulate` to prove nothing regressed.

## Output format

Start with a one-line verdict (e.g. "2 real bugs, 1 CDC risk, 5 waivable warnings"). Then a table:

| Severity | File:line | Issue | Why it matters | Fix |

Order Bug > CDC > Risk > Noise. Close with the exact lint command that was run so the result is
reproducible. Keep explanations concrete - name the signal, the clock and the failure mode.
