// Multi-bit bus crossing clock domains through a single flop stage - a classic CDC bug.
module cdc_bad (
  input  logic       clk_a, clk_b, rst_n,
  input  logic [3:0] count_a,
  output logic [3:0] count_b
);
  logic [3:0] meta;
  always_ff @(posedge clk_b or negedge rst_n)
    if (!rst_n) begin meta <= '0; count_b <= '0; end
    else begin meta <= count_a; count_b <= meta; end
endmodule
