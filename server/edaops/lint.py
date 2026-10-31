"""RTL lint: run Verilator / Icarus / Verible and normalise their diagnostics."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import runner

# %Warning-WIDTHTRUNC: rtl/x.v:12:15: Operator ASSIGNW expects 8 bits ...
_VERILATOR = re.compile(
    r"^%(?P<sev>Warning|Error)(?:-(?P<code>[A-Z0-9_]+))?:\s*"
    r"(?:(?P<file>[^:\s][^:]*?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*)?(?P<msg>.*)$"
)
# x.v:12: error: Unknown module type: foo
_ICARUS = re.compile(r"^(?P<file>[^:\s][^:]*?):(?P<line>\d+):\s*(?P<sev>error|warning|sorry):\s*(?P<msg>.*)$", re.I)
# file.sv:3:5-10: message [Style: x] [rule-name]
_VERIBLE = re.compile(r"^(?P<file>[^:\s][^:]*?):(?P<line>\d+):(?P<col>\d+)(?:-\d+)?:\s*(?P<msg>.*?)(?:\s*\[(?P<code>[a-z0-9-]+)\])?$")

# Verilator codes worth explaining because they usually indicate real silicon bugs.
SEVERE_CODES = {
    "LATCH": "Latch inferred - incomplete assignment in combinational always block.",
    "COMBDLY": "Non-blocking assignment in combinational logic.",
    "BLKSEQ": "Blocking assignment in sequential logic - simulation/synthesis mismatch risk.",
    "MULTIDRIVEN": "Signal driven from multiple always blocks.",
    "UNOPTFLAT": "Combinational loop (or apparent loop) detected.",
    "ALWCOMBORDER": "always_comb reads a variable before it is assigned.",
    "CASEINCOMPLETE": "Case statement is not full - possible latch or X propagation.",
    "WIDTHTRUNC": "Value silently truncated.",
    "WIDTHEXPAND": "Value silently zero-extended.",
    "WIDTH": "Width mismatch.",
    "IMPLICIT": "Implicit net declared - usually a typo.",
    "PINMISSING": "Instance port left unconnected.",
    "SYNCASYNCNET": "Net used as both sync and async reset.",
    "INITIALDLY": "Delayed assignment in initial block.",
}

NOISE_CODES = {"DECLFILENAME", "EOFNEWLINE"}


def parse_verilator(text: str) -> list[dict]:
    out: list[dict] = []
    for line in text.splitlines():
        m = _VERILATOR.match(line.strip())
        if not m:
            continue
        msg = m["msg"].strip()
        if m["sev"] == "Error" and msg.startswith("Exiting due to"):
            continue
        code = m["code"] or ""
        out.append({
            "tool": "verilator",
            "severity": "error" if m["sev"] == "Error" else "warning",
            "code": code,
            "file": m["file"], "line": int(m["line"]) if m["line"] else None,
            "col": int(m["col"]) if m["col"] else None,
            "message": msg,
            "hint": SEVERE_CODES.get(code, ""),
        })
    return out


def parse_icarus(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = _ICARUS.match(line.strip())
        if m:
            sev = m["sev"].lower()
            out.append({"tool": "iverilog", "severity": "error" if sev in ("error", "sorry") else "warning",
                        "code": "", "file": m["file"], "line": int(m["line"]), "col": None,
                        "message": m["msg"].strip(), "hint": ""})
    return out


def parse_verible(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = _VERIBLE.match(line.strip())
        if m:
            out.append({"tool": "verible", "severity": "style", "code": m["code"] or "",
                        "file": m["file"], "line": int(m["line"]), "col": int(m["col"]),
                        "message": m["msg"].strip(), "hint": ""})
    return out


def summarise(diags: list[dict]) -> dict:
    by_sev = Counter(d["severity"] for d in diags)
    by_code = Counter(d["code"] or "(none)" for d in diags)
    return {"total": len(diags), "by_severity": dict(by_sev), "by_code": dict(by_code.most_common())}


def lint(files: list[str], top: str | None = None, incdirs: list[str] | None = None,
         defines: list[str] | None = None, tool: str = "auto", waive: list[str] | None = None,
         timeout: int = 300) -> dict:
    incdirs = incdirs or []
    defines = defines or []
    waive = set(waive or []) | NOISE_CODES
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        return {"ok": False, "error": f"Files not found: {missing}"}

    order = ["verilator", "iverilog"] if tool == "auto" else [tool]
    for t in order:
        exe = runner.find_tool(t)
        if not exe:
            continue
        if t == "verilator":
            cmd = [exe, "--lint-only", "-Wall", "-Wno-fatal", "--timing"]
            cmd += [f"-Wno-{c}" for c in sorted(waive)]
            cmd += [f"+incdir+{d}" for d in incdirs] + [f"-D{d}" for d in defines]
            if top:
                cmd += ["--top-module", top]
            res = runner.run(cmd + files, timeout=timeout)
            if "--timing" in cmd and "Invalid option: --timing" in res["stderr"]:
                cmd.remove("--timing")
                res = runner.run(cmd + files, timeout=timeout)
            diags = parse_verilator(res["stderr"] + "\n" + res["stdout"])
        elif t == "iverilog":
            cmd = [exe, "-g2012", "-Wall", "-t", "null"]
            cmd += [f"-I{d}" for d in incdirs] + [f"-D{d}" for d in defines]
            if top:
                cmd += ["-s", top]
            res = runner.run(cmd + files, timeout=timeout)
            diags = parse_icarus(res["stderr"] + "\n" + res["stdout"])
        elif t == "verible-lint":
            res = runner.run([exe] + files, timeout=timeout)
            diags = parse_verible(res["stdout"] + "\n" + res["stderr"])
        else:
            return {"ok": False, "error": f"Unknown lint tool '{t}'"}
        diags = [d for d in diags if d["code"] not in waive]
        return {
            "ok": not any(d["severity"] == "error" for d in diags),
            "tool": t, "command": " ".join(res["cmd"]),
            "summary": summarise(diags), "diagnostics": diags[:300],
            "truncated": len(diags) > 300,
            "raw_tail": runner.clip(res["stderr"] or res["stdout"], 4000) if not diags else "",
        }
    return {"ok": False, "error": "No lint tool found. Install verilator (preferred) or iverilog, "
                                  "or set EDAOPS_VERILATOR / EDAOPS_IVERILOG."}
