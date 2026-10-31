# High-signal message IDs

Messages worth attention regardless of count. IDs change across versions; match on meaning as well.

## Vivado
| ID | Meaning | Action |
|---|---|---|
| Synth 8-327 | Latch inferred | Fix RTL (default assignments) |
| Synth 8-3352 / 8-6859 | Multi-driven net | Fix RTL |
| Synth 8-3331 / 8-7129 | Unconnected / no-load port | Usually benign; check for missing connection |
| Synth 8-3332 / 8-3333 | Register removed (unused / constant) | Check it was meant to be removed |
| Synth 8-5788 / 8-4767 | RAM/DSP inference choices | Review if QoR matters |
| Constraints 18-512 / 18-619 | Constraint matched no objects | Fix the constraint - it is silently ignored |
| Timing 38-282 | Timing not met | Run timing-closure skill |
| DRC NSTD-1 / UCIO-1 | Missing IOSTANDARD / LOC | Add pin constraints; blocks bitstream |
| Place 30-574 | Poor clock placement (clock not on clock-capable pin) | Fix pinout or use CLOCK_DEDICATED_ROUTE |
| Route 35-39 | Unroutable / congestion | Floorplan / reduce utilization |

## Synopsys (DC / PT / VCS)
| ID | Meaning |
|---|---|
| LINT-1/2/28/31/32/33 | Unconnected / constant / multiple drivers / feedthrough |
| ELAB-366 / ELAB-405 | Unresolved reference / black box |
| UID-341, OPT-1206 | Constant/unloaded register removed |
| TIM-052, PTE-* | Timing loop / constraint issues |
| VCS `Error-[SE]` | Syntax error; `Warning-[PCWM-W]` port width mismatch |

## Cadence (Genus / Innovus / Xcelium)
| ID | Meaning |
|---|---|
| CDFG-738/739 | Latch inferred / multi-driver |
| ELABUTL-*, CDFG-472 | Unresolved module / black box |
| IMPSP-*, IMPPSP-* | Placement issues |
| IMPESI-*, NRDB-* | Routing / database |
| Xcelium `*W,CUVWSP` | Port width mismatch |

## OpenROAD / OpenSTA
| ID | Meaning |
|---|---|
| STA-1554, ORD-* | Missing liberty cell / link failure |
| GRT-0097 / GRT-0116 | Global routing congestion / overflow |
| DPL-*, RSZ-* | Detailed placement / resizer issues |

## Simulation / UVM
- `UVM_ERROR` / `UVM_FATAL` counts in the report summary are the verdict.
- `$fatal`, assertion failures and "X on clock/reset" messages outrank everything else.
