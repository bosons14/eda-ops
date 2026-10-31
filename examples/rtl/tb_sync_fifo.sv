`timescale 1ns/1ps
module tb_sync_fifo;
  logic clk = 0, rst_n = 0, wr_en = 0, rd_en = 0;
  logic [7:0] wdata, rdata;
  logic full, empty;
  int errors = 0;

  sync_fifo #(.WIDTH(8), .DEPTH(16)) dut (.*);
  always #5 clk = ~clk;

  initial begin
    $dumpfile("tb_sync_fifo.vcd"); $dumpvars(0, tb_sync_fifo);
    repeat (2) @(posedge clk); rst_n = 1;
    for (int i = 0; i < 16; i++) begin
      @(negedge clk); wr_en = 1; wdata = 8'(i * 3);
    end
    @(negedge clk); wr_en = 0;
    if (!full) begin $display("FAIL: fifo not full after 16 writes"); errors++; end
    for (int i = 0; i < 16; i++) begin
      @(negedge clk);
      if (rdata !== 8'(i * 3)) begin
        $display("FAIL: read %0d got %0d expected %0d", i, rdata, i * 3); errors++;
      end
      rd_en = 1; @(negedge clk); rd_en = 0;
    end
    if (!empty) begin $display("FAIL: fifo not empty at end"); errors++; end
    if (errors == 0) $display("TEST PASSED");
    $finish;
  end
endmodule
