---
name: rtl-testbench
description: >
  This skill should be used when the user asks to "write a testbench", "verify this module", "simulate
  this design", "add a self-checking test", "run the tests", or "does this RTL work", or runs
  /rtl-testbench. Builds self-checking SystemVerilog testbenches and runs them with Icarus Verilog or
  Verilator through the eda-ops MCP server.
metadata:
  version: "0.1.0"
---

# Self-checking testbenches

A testbench that needs a human to look at waveforms is not a test. Every testbench written here must
decide PASS or FAIL itself.

## Procedure

1. **Read the DUT**: ports, parameters, reset polarity and style, clocking, latency, handshake protocol.
   Write down the intended behaviour in 3-6 bullet points and confirm ambiguous points with the user.
2. **Write the testbench** (`tb_<module>.sv`) with:
   - clock generation, reset sequence matching the DUT's reset style;
   - a reference model (behavioural SystemVerilog, queue-based scoreboard for streaming designs);
   - directed tests for corner cases (reset, empty/full, overflow, max/min values, back-to-back
     transactions, simultaneous read/write) plus a constrained-random loop with a fixed, printed seed;
   - checks with a running `errors` count; print `FAIL: <what> got <x> expected <y>` on mismatch;
   - final line exactly `TEST PASSED` when errors == 0, otherwise `TEST FAILED (<n> errors)` and `$fatal`;
   - a timeout watchdog (`#<n> $fatal(1, "TIMEOUT");`);
   - `$dumpfile/$dumpvars` guarded by `` `ifdef DUMP `` so waveforms are optional.
   Use only constructs both Icarus (-g2012) and Verilator --timing support: avoid classes/UVM, covergroups
   and `randomize()` with constraints; use `$urandom` instead.
3. **Run it**: call `simulate` (eda-ops MCP) with the DUT + TB and `top` = the TB module. Use
   `defines: ["DUMP"]` when waveforms are needed.
4. **On FAIL**: decide whether the DUT or the testbench is wrong by re-reading the spec bullets. Fix the
   right one, explain the bug, re-run until PASS. Never weaken a check just to pass.
5. **Report** the verdict, the scenarios covered, the seed, and any behaviour that is still untested.
