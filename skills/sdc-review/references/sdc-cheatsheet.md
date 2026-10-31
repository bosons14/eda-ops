# SDC cheatsheet

## Template order

```tcl
# 1. Clocks
create_clock -name clk     -period 2.000 -waveform {0 1.0} [get_ports clk]
create_clock -name vclk_io -period 10.000                    ;# virtual clock for I/O budgeting
create_generated_clock -name clk_div2 -source [get_ports clk] -divide_by 2 [get_pins u_div/q_reg/Q]

# 2. Clock characteristics
set_clock_uncertainty -setup 0.10 [get_clocks clk]   ;# jitter + pre-CTS skew estimate
set_clock_uncertainty -hold  0.05 [get_clocks clk]
set_clock_transition 0.05 [get_clocks clk]           ;# pre-CTS only
set_clock_latency -source 0.2 [get_clocks clk]

# 3. Clock relationships
set_clock_groups -asynchronous -group {clk clk_div2} -group {vclk_io}

# 4. I/O
set_input_delay  -clock clk -max 0.8 [remove_from_collection [all_inputs] [get_ports clk]]
set_input_delay  -clock clk -min 0.1 [remove_from_collection [all_inputs] [get_ports clk]]
set_output_delay -clock clk -max 0.6 [all_outputs]
set_output_delay -clock clk -min -0.1 [all_outputs]
set_driving_cell -lib_cell BUF_X2 [remove_from_collection [all_inputs] [get_ports clk]]
set_load 0.02 [all_outputs]

# 5. Exceptions (each with a comment saying why)
set_multicycle_path 2 -setup -from [get_cells u_mac/acc_reg*] -to [get_cells u_mac/res_reg*]
set_multicycle_path 1 -hold  -from [get_cells u_mac/acc_reg*] -to [get_cells u_mac/res_reg*]
set_max_delay 2.0 -datapath_only -from [get_cells u_cdc/gray_src_reg*] -to [get_cells u_cdc/sync1_reg*]  ;# Vivado
set_false_path -from [get_ports rst_n]   ;# async reset, synchronized in RTL
```

## Rules of thumb

- Input delay `-max` = external clock-to-out + board delay; leaves `period - max` for internal logic.
- Multicycle N setup -> hold moves to N-1 edges; add `-hold N-1` to restore the original hold check.
- `set_clock_groups -asynchronous` covers both directions; `set_false_path -from A -to B` covers one.
- `-logically_exclusive` for muxed clocks that never coexist; `-physically_exclusive` when they cannot
  both exist on the net (e.g. test vs functional clock on one pin).
- XDC (Vivado) is SDC plus `get_*` with `-hierarchical`, `-of_objects`; `set_max_delay -datapath_only`
  is Vivado-specific; `create_generated_clock` is often auto-derived for MMCM/PLL outputs.
- Verify after loading: `check_setup -verbose` / `report_checks -unconstrained` (OpenSTA),
  `check_timing` (PrimeTime), `report_methodology` and `check_timing` (Vivado).
