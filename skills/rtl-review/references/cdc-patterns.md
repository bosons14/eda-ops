# Clock-domain crossing patterns

Identify every crossing by listing, per flop, its clock; any combinational path from a flop on clock A to
a flop on clock B is a crossing. Unrelated clocks (different sources, or no defined phase relation) need
synchronization; related clocks (divided from the same source, constrained together) may be timed
synchronously.

## Correct structures

| Crossing | Structure | Notes |
|---|---|---|
| Single-bit level | 2-flop (3 for high MTBF) synchronizer in destination domain | Source must be registered - no glitchy combinational logic before the synchronizer. Mark flops `(* ASYNC_REG = "TRUE" *)` on FPGA |
| Single-bit pulse, fast->slow | Toggle synchronizer or pulse stretcher + edge detect | A 1-cycle pulse can be missed by the slow clock |
| Multi-bit counter / pointer | Gray-code in source, 2-flop each bit, convert back | Only valid if value changes by at most 1 per source cycle |
| Multi-bit data bus | Handshake (req/ack), or MUX recirculation with synchronized enable | Data must be stable while the enable is synchronized |
| Streaming data | Asynchronous FIFO with gray pointers | Standard Cummings design |
| Reset de-assertion | Reset synchronizer: async assert, 2-flop sync de-assert | One per destination domain |

## Classic bugs

- Synchronizing each bit of a binary bus independently -> bits resolve in different cycles -> corrupt value.
- Re-convergence: two separately synchronized signals combined in the destination -> may disagree for a cycle.
- Combinational logic between the source flop and the first synchronizer flop -> glitches get captured.
- Fan-out of the first (metastable) synchronizer stage to logic.
- Missing constraints: the crossing must be excluded from normal timing (`set_clock_groups -asynchronous`)
  and, for gray/bus crossings, bounded with `set_max_delay -datapath_only <source period>` so skew between
  bits stays under one cycle.

## Review output

For each crossing report: source clock, destination clock, signal(s), width, structure found, verdict
(OK / BUG / NEEDS CONSTRAINT), and the fix.
