// Deliberately buggy ALU used to exercise lint_rtl and synthesize.
module alu (
  input  logic       clk,
  input  logic [2:0] op,
  input  logic [7:0] a, b,
  output logic [7:0] y,
  output logic       zero
);
  logic [8:0] sum;
  logic [7:0] r;

  always_comb begin
    case (op)                       // no default -> latch on r
      3'd0: r = a + b;
      3'd1: r = a - b;
      3'd2: r = a & b;
      3'd3: r = a | b;
    endcase
  end

  assign sum = a + b;
  assign zero = (r == 0);

  always_ff @(posedge clk) begin
    y = r;                          // blocking assignment in sequential block
  end
endmodule
