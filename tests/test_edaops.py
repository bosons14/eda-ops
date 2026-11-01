"""Tests for eda-ops parsers and flows. Tool-dependent tests are skipped when the tool is missing.

Run:  python -m pytest -q tests
"""

import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from edaops import flows, lint, logs, runner, sdc, timing

EX = ROOT / "examples"


# ------------------------------------------------------------------ timing
def test_opensta_report_summary():
    r = timing.parse_file(str(EX / "reports/opensta_checks.rpt"))
    assert r["ok"] and r["paths_parsed"] == 4
    assert r["setup"]["wns"] == -0.175
    assert r["setup"]["tns"] == pytest.approx(-0.337)
    assert r["setup"]["violating_endpoints"] == 2
    assert r["setup"]["cross_clock_violations"] == 1
    assert r["hold"]["wns"] == -0.03
    worst = r["setup"]["worst_paths"][0]
    assert worst["logic_depth"] == 17
    assert worst["top_stages"][0]["cell"] == "BUF_X1"
    assert any("cross clock" in n for n in r["patterns"])


PT_REPORT = """
  Startpoint: in_a (input port clocked by clk)
  Endpoint: u1/q_reg (rising edge-triggered flip-flop clocked by clk)
  Path Group: clk
  Path Type: max

  Point                                    Incr       Path
  -----------------------------------------------------------
  clock clk (rise edge)                    0.00       0.00
  input external delay                     1.20       1.20 r
  in_a (in)                                0.00       1.20 r
  u0/U5/Y (NAND2X1)                        0.35       1.55 f
  u0/U6/Y (INVX1)                          0.20       1.75 r
  u1/q_reg/D (DFFX1)                       0.00       1.75 r
  data arrival time                                   1.75

  clock clk (rise edge)                    2.00       2.00
  clock network delay (ideal)              0.00       2.00
  u1/q_reg/CK (DFFX1)                      0.00       2.00 r
  library setup time                      -0.10       1.90
  data required time                                  1.90
  -----------------------------------------------------------
  data required time                                  1.90
  data arrival time                                  -1.75
  -----------------------------------------------------------
  slack (MET)                                         0.15
"""


def test_primetime_style_report():
    paths = timing.parse_report(PT_REPORT)
    assert len(paths) == 1
    p = paths[0]
    assert p["slack"] == 0.15 and p["status"] == "MET"
    assert p["path_class"] == "input2reg"
    assert p["arrival"] == 1.75 and p["required"] == 1.90
    assert p["terms"]["launch_input_delay"] == 1.20
    assert {s["cell"] for s in p["stages"]} >= {"NAND2X1", "INVX1"}


def test_no_paths():
    assert timing.parse_report("nothing here") == []


# ------------------------------------------------------------------ logs
def test_vivado_log_triage():
    r = logs.triage(str(EX / "reports/vivado_synth.log"))
    assert r["ok"] and "vivado" in r["detected_tools"]
    ids = {g["id"]: g for g in r["groups"]}
    assert ids["Synth 8-7129"]["count"] == 4
    assert ids["DRC NSTD-1"]["severity"] == "error"
    assert r["groups"][0]["severity"] == "error"  # errors sorted first
    assert r["first_error"]["line"] == 12
    hints = {f["hint"] for f in r["fatal_signs"]}
    assert "Tool reports timing not met." in hints and "A tool command failed." in hints


def test_big_gz_log_groups(tmp_path):
    f = tmp_path / "big.log.gz"
    with gzip.open(f, "wt") as fh:
        for i in range(50_000):
            fh.write(f"Warning: Net 'n{i}' has no loads (LINT-2)\n")
        fh.write("Error: Unable to resolve reference 'foo' in 'top'. (LINK-5)\n")
    r = logs.triage(str(f))
    assert r["lines"] == 50_001 and r["unique_messages"] == 2
    assert r["groups"][0]["id"] == "LINK-5"
    assert r["groups"][1]["count"] == 50_000


@pytest.mark.parametrize("line,sev,mid", [
    ("[WARNING GRT-0097] No global routing found for nets.", "warning", "GRT-0097"),
    ("**ERROR: (IMPSYT-6000): No Netlist files provided.", "error", "IMPSYT-6000"),
    ("** Error (suppressible): (vlog-2388) 'x' already declared", "error", "vlog-2388"),
    ("xmelab: *W,CUVWSP (./tb.sv,12|5): 1 output port was not connected", "warning", "CUVWSP"),
    ("UVM_ERROR tb.sv(40) @ 100: uvm_test_top [SCB] mismatch", "error", "SCB"),
    ("%Warning-WIDTH: a.v:3:7: Operator ASSIGN expects 4 bits", "warning", "WIDTH"),
    ("Error-[SE] Syntax error", "error", "SE"),
])
def test_log_families(tmp_path, line, sev, mid):
    f = tmp_path / "x.log"
    f.write_text(line + "\n")
    g = logs.triage(str(f))["groups"][0]
    assert (g["severity"], g["id"]) == (sev, mid)


# ------------------------------------------------------------------ sdc
def test_sdc_review_findings():
    r = sdc.review(str(EX / "constraints/top.sdc"))
    rules = {f["rule"] for f in r["findings"]}
    assert {"GCLK-NOSRC", "IO-NOCLK", "IO-ALLINPUTS", "FP-WILDCARD", "MCP-NOHOLD", "CLK-NOUNCERT"} <= rules
    assert r["clocks"]["core_clk"]["freq_mhz"] == 500.0
    assert "cfg_clk" in r["clocks"]
    assert not r["ok"]


def test_sdc_clean(tmp_path):
    f = tmp_path / "ok.sdc"
    f.write_text("""
create_clock -name clk -period 4.0 [get_ports clk]
set_clock_uncertainty 0.1 [get_clocks clk]
set_input_delay -clock clk -max 1.0 [get_ports din]
set_input_delay -clock clk -min 0.2 [get_ports din]
set_output_delay -clock clk -max 1.0 [get_ports dout]
set_driving_cell -lib_cell BUF_X1 [get_ports din]
set_load 0.01 [get_ports dout]
set_multicycle_path 2 -setup -from [get_cells a_reg] -to [get_cells b_reg]
set_multicycle_path 1 -hold -from [get_cells a_reg] \\
    -to [get_cells b_reg]
""")
    r = sdc.review(str(f))
    assert r["ok"] and r["summary"]["warning"] == 0, r["findings"]


# ------------------------------------------------------------------ lint parsing (no tools needed)
def test_parse_verilator_text():
    text = ("%Warning-LATCH: rtl/a.sv:12:3: Latch inferred for signal 'r'\n"
            "%Error: rtl/b.sv:4:1: syntax error, unexpected endmodule\n"
            "%Error: Exiting due to 2 error(s)\n")
    d = lint.parse_verilator(text)
    assert len(d) == 2
    assert d[0]["code"] == "LATCH" and d[0]["line"] == 12 and d[0]["hint"]
    assert d[1]["severity"] == "error" and d[1]["file"] == "rtl/b.sv"


def test_parse_icarus_text():
    d = lint.parse_icarus("top.v:7: error: Unknown module type: foo\n")
    assert d[0]["severity"] == "error" and d[0]["line"] == 7


def test_filelist():
    files, incs, defs = runner.read_filelist(EX / "rtl/files.f")
    assert [Path(f).name for f in files] == ["sync_fifo.sv", "tb_sync_fifo.sv"]
    assert incs and not defs


# ------------------------------------------------------------------ tool flows
needs_verilator = pytest.mark.skipif(not runner.find_tool("verilator"), reason="verilator missing")
needs_iverilog = pytest.mark.skipif(not runner.find_tool("iverilog"), reason="iverilog missing")
needs_yosys = pytest.mark.skipif(not runner.find_tool("yosys"), reason="yosys missing")


@needs_verilator
def test_lint_buggy_alu():
    r = lint.lint([str(EX / "rtl/alu.sv")], top="alu")
    codes = r["summary"]["by_code"]
    assert "CASEINCOMPLETE" in codes and "BLKSEQ" in codes


@needs_verilator
def test_lint_clean_fifo():
    r = lint.lint([str(EX / "rtl/sync_fifo.sv")], top="sync_fifo")
    assert r["ok"] and r["summary"]["total"] == 0


@needs_yosys
def test_synth_latch_detected():
    r = flows.synth([str(EX / "rtl/alu.sv")], "alu")
    assert "alu.r" in r["latches_inferred"]


@needs_yosys
def test_synth_fifo_qor(tmp_path):
    net = tmp_path / "fifo_net.v"
    r = flows.synth([str(EX / "rtl/sync_fifo.sv")], "sync_fifo", out_netlist=str(net))
    assert r["ok"] and r["stats"]["cells"] > 0
    assert sum(r["sequential_cells"].values()) == 16 * 8 + 10   # memory + two 5-bit pointers
    assert net.exists()


@needs_iverilog
def test_sim_fifo_passes():
    r = flows.simulate([str(EX / "rtl/sync_fifo.sv"), str(EX / "rtl/tb_sync_fifo.sv")], "tb_sync_fifo",
                       tool="iverilog")
    assert r["verdict"] == "PASS", r.get("output")


# ------------------------------------------------------------------ docs search
DOC_CHUNKS = [
    {"tool": "openroad", "source": "docs", "path": "src/rsz/README.md", "section": "Repair Design",
     "url": "https://github.com/The-OpenROAD-Project/OpenROAD/blob/HEAD/src/rsz/README.md",
     "text": "repair_design inserts buffers on nets to repair max slew, max capacitance and max fanout "
             "violations. Use -max_fanout to override the fanout limit. If no limit is set it uses a "
             "default limit of 50 load pins."},
    {"tool": "yosys", "source": "docs", "path": "docs/source/cmd/flatten.rst", "section": "flatten",
     "url": "https://github.com/YosysHQ/yosys/blob/HEAD/docs/source/cmd/flatten.rst",
     "text": "flatten: this pass flattens the design by replacing cells by their implementation, "
             "producing a single module without hierarchy."},
    {"tool": "opensta", "source": "docs", "path": "doc/OpenSTA.md", "section": "create_clock",
     "url": "https://github.com/The-OpenROAD-Project/OpenSTA/blob/HEAD/doc/OpenSTA.md",
     "text": "create_clock -period 10 clk1 defines a clock with a 10 ns period on port clk1."},
]


@pytest.fixture
def doc_index(tmp_path, monkeypatch):
    from edaops import docs
    d = tmp_path / "data" / "index" / "struct"
    d.mkdir(parents=True)
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(c) for c in DOC_CHUNKS) + "\n")
    monkeypatch.setenv("EDAOPS_DOCS_INDEX", str(tmp_path))  # eda-rag root layout is accepted
    return docs


def test_docs_tokenize_keeps_identifiers():
    from edaops import docs
    toks = docs.tokenize("repair_design -max_fanout")
    assert {"repair_design", "repair", "design", "max_fanout", "max", "fanout"} <= set(toks)


def test_docs_search_identifier_and_paraphrase(doc_index):
    r = doc_index.search("-max_fanout")
    assert r["ok"] and r["mode"] == "bm25"
    assert r["results"][0]["path"] == "src/rsz/README.md"
    r = doc_index.search("command to make a single module without hierarchy")
    assert r["results"][0]["tool"] == "yosys"


def test_docs_search_tool_filter_and_validation(doc_index):
    r = doc_index.search("clock period", tools=["opensta"])
    assert [x["tool"] for x in r["results"]] == ["opensta"]
    assert not doc_index.search("x", tools=["vivado"])["ok"]
    assert not doc_index.search("   ")["ok"]
    assert not doc_index.search("x", mode="magic")["ok"]


def test_docs_dense_falls_back_to_bm25(doc_index):
    r = doc_index.search("max fanout", mode="hybrid_rerank")
    assert r["ok"] and r["mode"] == "bm25" and "note" in r
    s = doc_index.status()
    assert s["available"] and s["passages"] == 3 and s["modes"] == ["bm25"]


def test_docs_no_index(tmp_path, monkeypatch):
    from edaops import docs
    monkeypatch.setenv("EDAOPS_DOCS_INDEX", str(tmp_path / "missing"))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin-data"))
    r = docs.search("anything")
    assert not r["ok"] and "eda-rag" in r["error"]
    assert docs.status()["available"] is False
