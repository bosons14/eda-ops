# Timing fix playbook

## Setup - ordered from cheapest to most invasive

| Symptom | Fix | Typical gain | Where |
|---|---|---|---|
| Async cross-clock path timed | `set_clock_groups -asynchronous` (+ CDC check) | removes path | SDC |
| I/O path violates | Re-budget `set_input_delay`/`set_output_delay` with the real board/partner timing; register I/O | large | SDC / RTL |
| Path is legitimately multi-cycle (enable every N clocks) | `set_multicycle_path N -setup` **and** `N-1 -hold` | large | SDC |
| Uncertainty > violation pre-CTS | Check uncertainty value for this flow stage (pre-CTS adds skew estimate) | small-med | SDC |
| High fanout startpoint | Register duplication (`(* keep *)`/`max_fanout`), buffer tree | 10-30% of path | RTL / synth attr |
| Single slow cell | Upsize / Vt swap (LVT on critical path) | 5-20% | Synthesis/P&R |
| Long wire | Placement bounds, pipelining across the die, floorplan | varies | P&R |
| Deep logic (> ~12-15 levels at target freq) | Pipeline stage, retiming (`retime`/`-retime`), restructure | 30-50% | RTL |
| Wide adder/compare | Parallel-prefix adder, split compare, precompute | 20-40% | RTL |
| Wide mux / priority chain | One-hot select, balanced tree, `unique case` | 10-30% | RTL |
| Big FSM next-state logic | One-hot encoding, register outputs | 10-20% | RTL |
| Memory output path | Register RAM output (use the RAM's output register) | large | RTL |

## Hold

- Evaluate only with propagated clocks (post-CTS); ideal-clock hold numbers mislead.
- Let the tool insert delay cells (`repair_timing -hold` in OpenROAD, `fix_hold` flows elsewhere).
- Large hold violations right after adding a multicycle path almost always mean the matching `-hold`
  multicycle is missing.
- Hold violations on scan paths are fixed in the scan stitch order / lockup latches, not functional RTL.

## Sanity checks before any fix

- Is the clock period what the user expects? (`report_clock_properties` / SDC create_clock)
- Are there unconstrained endpoints? (`report_checks -unconstrained`) - a "clean" report can hide them.
- Is the report from the right corner (slow/setup, fast/hold) and with parasitics?
