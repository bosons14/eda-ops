#!/usr/bin/env python3
"""eda-ops MCP server: RTL lint, synthesis QoR, simulation, STA and log/constraint analysis.

Runs over stdio. Relative paths resolve against EDAOPS_PROJECT_DIR, else CLAUDE_PROJECT_DIR, else cwd.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # noqa: E402

from edaops import __version__, flows, lint, logs, runner, sdc, timing  # noqa: E402

mcp = FastMCP("eda-ops")


def _base() -> Path:
    return Path(os.environ.get("EDAOPS_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _path(p: str) -> str:
    q = Path(p).expanduser()
    return str(q if q.is_absolute() else (_base() / q).resolve())


def _sources(files: list[str] | str | None, filelist: str | None,
             incdirs: list[str] | None, defines: list[str] | None):
    srcs = runner.resolve_files(files or [], _base())
    incs = [_path(d) for d in incdirs or []]
    defs = list(defines or [])
    if filelist:
        f2, i2, d2 = runner.read_filelist(_path(filelist))
        srcs += f2; incs += i2; defs += d2
    return srcs, incs, defs


@mcp.tool()
def eda_tool_status() -> dict:
    """Report which EDA tools (verilator, iverilog, yosys, OpenSTA, OpenROAD, verible, slang) are installed
    and where. Call this first when unsure what the environment can run."""
    return {"version": __version__, "project_dir": str(_base()), "tools": runner.tool_status()}


@mcp.tool()
def lint_rtl(files: list[str] | None = None, top: str | None = None, filelist: str | None = None,
             incdirs: list[str] | None = None, defines: list[str] | None = None,
             tool: str = "auto", waive: list[str] | None = None) -> dict:
    """Lint Verilog/SystemVerilog RTL and return structured diagnostics (severity, code, file, line, message,
    hint). tool: 'auto' (verilator, then iverilog), 'verilator', 'iverilog' or 'verible-lint'.
    files may contain globs (rtl/*.sv). filelist is a .f file with +incdir+/+define+ support.
    waive lists Verilator warning codes to suppress (e.g. ["UNUSEDSIGNAL"])."""
    srcs, incs, defs = _sources(files, filelist, incdirs, defines)
    if not srcs:
        return {"ok": False, "error": "No source files given (files or filelist)."}
    return lint.lint(srcs, top=top, incdirs=incs, defines=defs, tool=tool, waive=waive)


@mcp.tool()
def synthesize(top: str, files: list[str] | None = None, filelist: str | None = None,
               liberty: str | None = None, flatten: bool = True, defines: list[str] | None = None,
               incdirs: list[str] | None = None, write_netlist: str | None = None) -> dict:
    """Synthesize RTL with Yosys and return QoR: cell count, area (with a liberty file), cell mix,
    sequential cells, inferred latches, multi-driver/undriven/loop problems, and grouped warnings.
    Without liberty the result is generic-gate counts - good for relative comparisons only.
    write_netlist saves a gate-level Verilog netlist (useful as input to run_sta)."""
    srcs, incs, defs = _sources(files, filelist, incdirs, defines)
    if not srcs:
        return {"ok": False, "error": "No source files given."}
    return flows.synth(srcs, top, liberty=_path(liberty) if liberty else None, flatten=flatten,
                       defines=defs, incdirs=incs,
                       out_netlist=_path(write_netlist) if write_netlist else None)


@mcp.tool()
def simulate(top: str, files: list[str] | None = None, filelist: str | None = None,
             tool: str = "auto", defines: list[str] | None = None, incdirs: list[str] | None = None,
             plusargs: list[str] | None = None) -> dict:
    """Compile and run a testbench with Icarus Verilog (default) or Verilator --binary. Returns a verdict
    (PASS / FAIL / TIMEOUT / RAN), failure lines, waveform files, and clipped output. Testbenches should
    print 'PASS' or 'FAIL' (or use $fatal/$error) so the verdict is reliable."""
    srcs, incs, defs = _sources(files, filelist, incdirs, defines)
    if not srcs:
        return {"ok": False, "error": "No source files given."}
    return flows.simulate(srcs, top, tool=tool, defines=defs, incdirs=incs, plusargs=plusargs)


@mcp.tool()
def parse_timing_report(path: str, top_n: int = 10) -> dict:
    """Parse a static timing report (OpenSTA/OpenROAD report_checks, PrimeTime/Tempus report_timing) and
    return setup/hold WNS, TNS, violating endpoints, per-group summary, the worst paths with their largest
    stage delays, logic depth, clock-domain crossing flags, and heuristic root-cause patterns."""
    return timing.parse_file(_path(path), top_n=top_n)


@mcp.tool()
def run_sta(netlist: str, top: str, liberty: list[str], sdc_file: str, spef: str | None = None,
            group_count: int = 20) -> dict:
    """Run OpenSTA on a gate-level netlist with liberty + SDC (+ optional SPEF), then parse the result like
    parse_timing_report. Also returns max slew/cap/fanout violators."""
    return flows.run_sta(_path(netlist), top, [_path(l) for l in liberty], _path(sdc_file),
                         spef=_path(spef) if spef else None, group_count=group_count)


@mcp.tool()
def triage_log(path: str, max_groups: int = 40, include_info: bool = False) -> dict:
    """Triage a (possibly multi-GB or .gz) EDA log: detect the tool family (Vivado, Synopsys, Cadence,
    OpenROAD, Questa, Xcelium, VCS, Verilator, UVM, Yosys), group messages by ID with counts and first/last
    line, find the first error with context, and flag crashes, OOM, license and disk problems."""
    return logs.triage(_path(path), max_groups=max_groups, include_info=include_info)


@mcp.tool()
def grep_log(path: str, pattern: str, limit: int = 50) -> dict:
    """List occurrences (with line numbers) of one message ID or substring in a log, e.g. 'Synth 8-327'."""
    return logs.grep_id(_path(path), pattern, limit=limit)


@mcp.tool()
def review_sdc(path: str) -> dict:
    """Statically review an SDC/XDC constraints file: clock definitions and frequencies, generated clocks,
    missing I/O delays, uncertainty, driving cells/loads, risky false paths, multicycle setup/hold pairing,
    and clock-group intent. Returns findings with line numbers and suggested fixes."""
    return sdc.review(_path(path))


if __name__ == "__main__":
    mcp.run()
