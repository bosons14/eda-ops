# Example constraints with deliberate problems for review_sdc
create_clock -name core_clk -period 2.0 [get_ports clk]
create_clock -period 6.0 [get_ports cfg_clk]
create_generated_clock -name div2 -divide_by 2 [get_pins u_div/q_reg/Q]

set_clock_uncertainty -setup 0.05 [get_clocks core_clk]

set_input_delay 0.4 [all_inputs]
set_output_delay -clock core_clk -max 0.5 [get_ports {dout[*]}]

set_false_path -from [get_clocks cfg_clk] -to [get_clocks core_clk]
set_false_path -to [get_ports *]

set_multicycle_path 2 -setup -from [get_cells u_core/acc_reg*] -to [get_cells u_core/res_reg*]
