// Small synchronous FIFO (clean reference design).
module sync_fifo #(
  parameter int WIDTH = 8,
  parameter int DEPTH = 16
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             wr_en,
  input  logic [WIDTH-1:0] wdata,
  input  logic             rd_en,
  output logic [WIDTH-1:0] rdata,
  output logic             full,
  output logic             empty
);
  localparam int AW = $clog2(DEPTH);
  logic [WIDTH-1:0] mem [DEPTH];
  logic [AW:0] wptr, rptr;

  assign full  = (wptr[AW] != rptr[AW]) && (wptr[AW-1:0] == rptr[AW-1:0]);
  assign empty = (wptr == rptr);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr <= '0;
      rptr <= '0;
    end else begin
      if (wr_en && !full) begin
        mem[wptr[AW-1:0]] <= wdata;
        wptr <= wptr + 1'b1;
      end
      if (rd_en && !empty) rptr <= rptr + 1'b1;
    end
  end

  assign rdata = mem[rptr[AW-1:0]];
endmodule
