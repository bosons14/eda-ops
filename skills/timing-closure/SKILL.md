---
name: timing-closure
description: >
  This skill should be used when the user asks to "analyze this timing report", "why is timing failing",
  "fix setup/hold violations", "what is my WNS/TNS", "help me close timing", "run STA", or runs
  /timing-closure. Works with OpenSTA/OpenROAD report_checks and PrimeTime/Tempus report_timing output,
  and can run OpenSTA directly on a netlist with liberty and SDC.
metadata:
  version: "0.1.0"
---

# Timing closure

Turn a timing report into a ranked, root-caused fix plan. Distinguish constraint problems from real
logic problems before proposing any RTL change - most "timing failures" early in a project are
constraints.

## Procedure

1. **Get parsed data.**
   - Report file given: call `parse_timing_report` (eda-ops MCP) with `top_n` 10-20.
   - Netlist + liberty + SDC given: call `run_sta`; it runs OpenSTA and returns the same structure plus
     max slew/cap/fanout violators.
   - Pasted text: write it to a temporary `.rpt` file and parse that.
2. **State the headline**: setup WNS/TNS/violating endpoints, hold WNS/TNS, per path group, and the
   clock period(s) involved. Express WNS as a percentage of the period - -0.05 ns at 2 ns is very
   different from -0.05 ns at 20 ns.
3. **Classify each worst path** using the parser fields (`path_class`, `cross_clock`, `logic_depth`,
   `top_stages`, `terms`):
   - **Constraint suspect**: cross-clock path between asynchronous clocks, I/O path with an unrealistic
     input/output delay, a path that should be multicycle, uncertainty larger than the violation.
     Verify with the SDC (use the `sdc-review` skill / `review_sdc` tool when the SDC is available).
   - **Logic depth**: many stages, each modest. Fix in RTL - pipeline, retime, restructure (carry-lookahead,
     parallel-prefix, one-hot FSM, precompute).
   - **Single dominant stage**: one cell or net carries a large share of the delay - high fanout, weak
     drive, long wire. Fix physically - buffer/clone, upsize, placement constraint, register duplication.
   - **Clock skew**: large difference between launch and capture clock network delay. Fix in CTS / clock
     tree, or useful skew.
   - **Hold**: only meaningful with propagated clocks after CTS; fix by tool hold-fixing, not RTL, unless
     it is a genuine short path across a crossing.
4. **Use the `patterns` field** as hypotheses, not conclusions; confirm each against the path detail.
5. **Propose fixes** ranked by (expected slack recovered) / (effort), using `references/fix-playbook.md`.
   For RTL fixes, point at the actual source: search the RTL for the start/end register names (strip
   `_reg`, bit indices and hierarchy) and show the expression that forms the path.
6. **Re-verify** after changes: re-run `run_sta` (or ask for a new report) and show before/after WNS/TNS.

## Output format

1. Headline table: group | WNS | TNS | violating endpoints | period.
2. Top paths table: start -> end | slack | depth | class | dominant stage | likely cause.
3. Fix plan: numbered, each with expected impact and where to make the change (SDC / RTL file:line /
   physical flow).
4. Any constraint questions that must be answered before touching RTL.

Never recommend `set_false_path` to make a violation disappear without stating why the path is not a
real functional path.
