"""Tool flows: Yosys synthesis/QoR, Icarus/Verilator simulation, OpenSTA timing runs."""

from __future__ import annotations

import json
import shutil
import re
import tempfile
from pathlib import Path

from . import logs, runner, timing


def _ys_list(items: list[str]) -> str:
    return " ".join(f'"{i}"' for i in items)


def _tcl_list(items: list[str]) -> str:
    return " ".join("{" + i + "}" for i in items)


# ----------------------------------------------------------------------------- synthesis

def synth(files: list[str], top: str, liberty: str | None = None, flatten: bool = True,
          defines: list[str] | None = None, incdirs: list[str] | None = None,
          extra_script: str = "", out_netlist: str | None = None, timeout: int = 1800) -> dict:
    exe = runner.find_tool("yosys")
    if not exe:
        return {"ok": False, "error": "yosys not found. Install yosys (or `pip install yowasp-yosys`), "
                                      "or set EDAOPS_YOSYS."}
    files = [str(Path(f).resolve()) for f in files]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        return {"ok": False, "error": f"Files not found: {missing}"}
    work = Path(tempfile.mkdtemp(prefix="edaops_synth_"))
    stat_json = work / "stat.json"
    defs = " ".join(f"-D{d}" for d in (defines or []))
    incs = " ".join(f"-I{d}" for d in (incdirs or []))

    def script(abc: bool) -> str:
        s = [f"read_verilog -sv {defs} {incs} {_ys_list(files)}",
             f"hierarchy -check -top {top}",
             f"synth -top {top}{' -flatten' if flatten else ''}{'' if abc else ' -noabc'}"]
        if liberty:
            s += [f'dfflibmap -liberty "{liberty}"',
                  f'abc -liberty "{liberty}"' if abc else "",
                  "opt_clean"]
        s += ["check", extra_script,
              'tee -q -o stat.json stat -json' + (f' -liberty "{liberty}"' if liberty else ""),
              "stat" + (f' -liberty "{liberty}"' if liberty else "")]
        if out_netlist:
            s.append("write_verilog -noattr netlist.v")
        return "\n".join(x for x in s if x)

    notes = []
    script_path = work / "synth.ys"
    script_path.write_text(script(True))
    res = runner.run([exe, "-l", "yosys.log", "-s", "synth.ys"], cwd=work, timeout=timeout)
    first_log = (work / "yosys.log").read_text(errors="replace") if (work / "yosys.log").exists() else res["stdout"]
    if not stat_json.exists() and not res["timed_out"] and "ERROR:" not in first_log:
        # Some builds (e.g. YoWASP without ABC) stop silently in ABC - retry without it.
        notes.append("ABC technology mapping failed or is unavailable; reran with -noabc (cell counts are "
                     "pre-optimisation generic gates).")
        script_path.write_text(script(False))
        res = runner.run([exe, "-l", "yosys.log", "-s", "synth.ys"], cwd=work, timeout=timeout)

    # Outputs are written relative to the work dir (sandboxed builds such as YoWASP can only write there).
    if out_netlist and (work / "netlist.v").exists():
        Path(out_netlist).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work / "netlist.v", out_netlist)
    log_path = work / "yosys.log"
    tri = logs.triage(str(log_path), max_groups=30) if log_path.exists() else {}
    stats = {}
    if stat_json.exists():
        try:
            data = json.loads(stat_json.read_text())
            design = data.get("design", {})
            stats = {
                "cells": design.get("num_cells"),
                "area": design.get("area"),
                "cells_by_type": dict(sorted(design.get("num_cells_by_type", {}).items(),
                                             key=lambda kv: -kv[1])[:40]),
                "wires": design.get("num_wires"),
                "memories": design.get("num_memories"),
                "per_module": {m.lstrip("\\"): {"cells": v.get("num_cells"), "area": v.get("area")}
                               for m, v in data.get("modules", {}).items()},
            }
        except (json.JSONDecodeError, OSError) as exc:
            notes.append(f"Could not parse stat JSON: {exc}")
    text = log_path.read_text(errors="replace") if log_path.exists() else res["stdout"]
    latches = sorted({m.replace("\\", "") for m in re.findall(r"Latch inferred for signal `([^']+)'", text)})
    ff_types = {k: v for k, v in stats.get("cells_by_type", {}).items() if re.search(r"DFF|dff|SDFF|ADFF|LATCH|DLATCH", k)}
    problems = re.findall(r"Warning: (.*(?:multiple conflicting drivers|is used but has no driver|"
                          r"undriven|found logic loop|combinational loop).*)", text)
    return {
        "ok": res["returncode"] == 0 and bool(stats),
        "returncode": res["returncode"], "timed_out": res["timed_out"],
        "work_dir": str(work), "log": str(log_path), "netlist": out_netlist,
        "stats": stats, "sequential_cells": ff_types,
        "latches_inferred": latches, "structural_problems": sorted(set(problems))[:50],
        "warnings": [g for g in tri.get("groups", []) if g["severity"] in ("warning", "critical")][:25],
        "errors": [g for g in tri.get("groups", []) if g["severity"] in ("error", "fatal")][:25],
        "notes": notes,
        "log_tail": runner.clip("\n".join(text.splitlines()[-40:]), 4000) if res["returncode"] else "",
    }


# ----------------------------------------------------------------------------- simulation

_PASS = re.compile(r"\b(TEST\s+PASS(ED)?|ALL TESTS PASSED|\bPASS(ED)?\b)", re.I)
_FAIL = re.compile(r"\b(FAIL(ED|URE)?|MISMATCH|ASSERTION|\$fatal|Error:|UVM_ERROR\s*:\s*[1-9]|UVM_FATAL\s*:\s*[1-9])", re.I)


def simulate(files: list[str], top: str, tool: str = "auto", defines: list[str] | None = None,
             incdirs: list[str] | None = None, plusargs: list[str] | None = None,
             timeout: int = 900) -> dict:
    files = [str(Path(f).resolve()) for f in files]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        return {"ok": False, "error": f"Files not found: {missing}"}
    work = Path(tempfile.mkdtemp(prefix="edaops_sim_"))
    order = ["iverilog", "verilator"] if tool == "auto" else [tool]
    for t in order:
        if t == "iverilog" and runner.find_tool("iverilog") and runner.find_tool("vvp"):
            out = work / "sim.vvp"
            cmd = [runner.find_tool("iverilog"), "-g2012", "-o", str(out), "-s", top]
            cmd += [f"-D{d}" for d in defines or []] + [f"-I{d}" for d in incdirs or []]
            comp = runner.run(cmd + files, cwd=work, timeout=timeout)
            if comp["returncode"] != 0:
                return {"ok": False, "stage": "compile", "tool": t, "command": " ".join(cmd + files),
                        "output": runner.clip(comp["stderr"] + comp["stdout"], 8000)}
            res = runner.run([runner.find_tool("vvp"), "-n", str(out)] + [f"+{p}" for p in plusargs or []],
                             cwd=work, timeout=timeout)
            break
        if t == "verilator" and runner.find_tool("verilator"):
            cmd = [runner.find_tool("verilator"), "--binary", "--timing", "-Wno-fatal", "-j", "0",
                   "--top-module", top, "-Mdir", str(work / "obj")]
            cmd += [f"-D{d}" for d in defines or []] + [f"+incdir+{d}" for d in incdirs or []]
            comp = runner.run(cmd + files, cwd=work, timeout=timeout)
            if comp["returncode"] != 0:
                return {"ok": False, "stage": "compile", "tool": t, "command": " ".join(cmd + files),
                        "output": runner.clip(comp["stderr"] + comp["stdout"], 8000)}
            res = runner.run([str(work / "obj" / f"V{top}")] + [f"+{p}" for p in plusargs or []],
                             cwd=work, timeout=timeout)
            break
    else:
        return {"ok": False, "error": "No simulator found (need iverilog+vvp or verilator >= 5)."}

    output = res["stdout"] + res["stderr"]
    fails = [l.strip() for l in output.splitlines() if _FAIL.search(l)][:30]
    passes = bool(_PASS.search(output))
    vcds = [str(p) for p in work.rglob("*.vcd")] + [str(p) for p in work.rglob("*.fst")]
    if res["timed_out"]:
        verdict = "TIMEOUT"
    elif res["returncode"] not in (0, None) or fails:
        verdict = "FAIL"
    elif passes:
        verdict = "PASS"
    else:
        verdict = "RAN (no PASS/FAIL marker printed)"
    return {"ok": verdict == "PASS", "verdict": verdict, "tool": t, "returncode": res["returncode"],
            "failure_lines": fails, "waveforms": vcds, "work_dir": str(work),
            "output": runner.clip(output, 12000)}


# ----------------------------------------------------------------------------- static timing

def run_sta(netlist: str, top: str, liberty: list[str], sdc: str, spef: str | None = None,
            group_count: int = 20, corner_note: str = "", timeout: int = 1800) -> dict:
    exe = runner.find_tool("sta") or runner.find_tool("openroad")
    if not exe:
        return {"ok": False, "error": "OpenSTA ('sta') or OpenROAD not found. Install OpenSTA, or run "
                                      "report_checks in your own flow and use parse_timing_report on the output."}
    for f in [netlist, sdc, *liberty] + ([spef] if spef else []):
        if not Path(f).exists():
            return {"ok": False, "error": f"File not found: {f}"}
    work = Path(tempfile.mkdtemp(prefix="edaops_sta_"))
    rpt = work / "checks.rpt"
    tcl = [*(f"read_liberty {{{l}}}" for l in liberty),
           f"read_verilog {{{netlist}}}", f"link_design {top}", f"read_sdc {{{sdc}}}"]
    if spef:
        tcl.append(f"read_spef {{{spef}}}")
    tcl += [
        f"report_checks -path_delay max -group_path_count {group_count} -fields {{slew cap input fanout}} "
        f"-digits 4 > {{{rpt}}}",
        f"report_checks -path_delay min -group_path_count {group_count} -digits 4 >> {{{rpt}}}",
        f"report_checks -unconstrained -group_path_count 5 >> {{{work / 'unconstrained.rpt'}}}",
        "report_wns", "report_tns",
        f"report_check_types -max_slew -max_capacitance -max_fanout -violators > {{{work / 'drv.rpt'}}}",
        "exit",
    ]
    script = work / "sta.tcl"
    script.write_text("\n".join(tcl) + "\n")
    cmd = [exe, "-no_splash", "-exit", str(script)] if Path(exe).name.startswith("sta") else [exe, "-exit", str(script)]
    res = runner.run(cmd, cwd=work, timeout=timeout)
    parsed = timing.parse_file(str(rpt)) if rpt.exists() else {"ok": False}
    drv = (work / "drv.rpt").read_text(errors="replace") if (work / "drv.rpt").exists() else ""
    return {"ok": res["returncode"] == 0 and parsed.get("ok", False), "work_dir": str(work),
            "report": str(rpt), "corner": corner_note, "timing": parsed,
            "drv_violations": runner.clip(drv, 4000),
            "tool_output": runner.clip(res["stdout"] + res["stderr"], 6000)}
