---
name: synthesis-qor
description: >
  This skill should be used when the user asks to "synthesize this design", "how big is this module",
  "estimate area", "compare two implementations", "check for latches", "optimize area/QoR", "generate a
  netlist", or runs /synthesis-qor. Uses Yosys (optionally with a liberty file) to measure cell count,
  area and structure, and to compare RTL variants.
metadata:
  version: "0.1.0"
---

# Synthesis and QoR

Use synthesis as a measuring instrument: it answers "how big", "what got inferred" and "did my change
help" with numbers instead of opinions.

## Procedure

1. **Synthesize.** Call `synthesize` (eda-ops MCP) with `top` and files/filelist. Pass `liberty` when the
   user has a standard-cell library (e.g. Sky130, Nangate45/FreePDK45, GF180, ASAP7) so area is real;
   without it, counts are generic gates and valid only for relative comparison - say so.
2. **Read the result.**
   - `latches_inferred` and `structural_problems` are bugs until proven intentional.
   - `sequential_cells`: compare flop count with what the RTL intends (e.g. a 16x8 FIFO with ~128 data
     flops means the memory became registers, not RAM - expected for small FIFOs, wasteful for large).
   - `cells_by_type`: large mux or XOR counts point to wide muxes or arithmetic; check against intent.
   - `per_module` (with `flatten=false`) to find which submodule dominates.
3. **Compare variants** when the user is optimizing: synthesize each variant with the same options and
   report a delta table (cells, area, flops, latches). Run `simulate` on both to prove equivalence of
   behaviour when a testbench exists.
4. **Recommend optimizations** grounded in the numbers: resource sharing, removing unneeded resets on
   datapath flops, narrowing widths, RAM inference for large arrays, one-hot vs binary FSM encoding,
   constant propagation through parameters.
5. **Netlist for STA.** When the user wants timing, pass `write_netlist` and a liberty file, then hand
   the netlist to `run_sta` (see the `timing-closure` skill).

## Output format

- QoR table: metric | value (| variant B | delta).
- Findings: latches / multi-drivers / unexpected inference, each with RTL location.
- Recommendations ranked by expected saving.
- The exact options used (liberty, flatten, defines) so numbers can be reproduced.
