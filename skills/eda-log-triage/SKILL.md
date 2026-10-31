---
name: eda-log-triage
description: >
  This skill should be used when the user asks "why did my synthesis/P&R/simulation fail", "triage this
  log", "what's in this huge log", "summarize the warnings", "is this warning important", or points at a
  .log/.log.gz file from Vivado, Design Compiler, Genus, Innovus, OpenROAD, OpenSTA, Questa, Xcelium,
  VCS, Verilator, UVM or Yosys, or runs /eda-log-triage.
metadata:
  version: "0.1.0"
---

# EDA log triage

EDA logs are huge and repetitive; the cause of a failure is usually one line among thousands of
warnings. Never read a large log with Read or cat - use the streaming tools.

## Procedure

1. **Triage first.** Call `triage_log` (eda-ops MCP) on the file (works on `.gz` and multi-GB files).
   It returns detected tool family, totals by severity, unique message groups with counts and line
   ranges, the first error with preceding context, fatal signs (crash, OOM, license, disk, command
   failed) and the log tail.
2. **Find the root cause of a failure**, in this order:
   - `fatal_signs` - crashes, OOM kills, license or disk problems are environment issues, not design
     issues; say so immediately.
   - `first_error` and its context - the first error usually causes the later ones.
   - Critical warnings (Vivado) and errors grouped by ID.
   - The tail - the final command/status often names the failing step.
3. **Drill down only where needed.** Use `grep_log` with a message ID (e.g. `Synth 8-327`) to list
   occurrences, then Read with `offset`/`limit` around a specific line number for full context.
4. **Rank warnings by risk, not count.** 50,000 "port unconnected" warnings are usually harmless;
   one "inferring latch", "multi-driven net", "timing not met", "no valid objects found" (constraint
   matched nothing) or "black box" warning matters more. Use `references/message-ids.md`.
5. **Connect to sources.** When a message names a file:line or a signal, open that location in the
   RTL/constraints and explain the cause concretely.

## Output format

1. **Verdict**: did the run succeed; if not, the single most likely root cause with the log line number.
2. **Must-fix** list: message ID, count, what it means, where to fix.
3. **Review** list: warnings that are likely benign but deserve a look, with why.
4. **Noise**: the high-count groups that can be waived, with a suggested waiver/message-suppression
   command for that tool (e.g. `set_msg_config -id {Synth 8-7129} -suppress` in Vivado,
   `suppress_message LINT-1` in DC).
