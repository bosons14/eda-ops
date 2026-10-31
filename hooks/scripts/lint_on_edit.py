#!/usr/bin/env python3
"""PostToolUse hook: after Claude writes/edits a Verilog/SystemVerilog file, lint just that file and feed
real findings back to Claude so it can fix them in the same turn.

Silent (exit 0, no output) when the file is not RTL, no linter is installed, or the file is clean.
Disable with EDAOPS_HOOK_DISABLE=1. Extra Verilator flags via EDAOPS_HOOK_FLAGS.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

RTL_EXT = {".v", ".sv", ".svh", ".vh"}
# Messages caused by linting one file in isolation, not by the edit itself.
ISOLATION_NOISE = ("Cannot find file containing module", "Cannot find include file",
                   "Exiting due to", "DECLFILENAME", "MULTITOP", "is not defined", "Define or directive not defined")


def main() -> int:
    if os.environ.get("EDAOPS_HOOK_DISABLE") == "1":
        return 0
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path") or ""
    p = Path(path)
    if p.suffix.lower() not in RTL_EXT or not p.exists() or p.suffix.lower() in {".svh", ".vh"}:
        return 0

    verilator = shutil.which(os.environ.get("EDAOPS_VERILATOR", "verilator"))
    iverilog = shutil.which(os.environ.get("EDAOPS_IVERILOG", "iverilog"))
    flags = os.environ.get("EDAOPS_HOOK_FLAGS", "").split()
    stem = p.stem.lower()
    if stem.startswith("tb") or stem.endswith("_tb") or "test" in stem:
        flags += ["-Wno-BLKSEQ", "-Wno-INITIALDLY", "-Wno-STMTDLY"]  # testbench idioms
    if verilator:
        cmd = [verilator, "--lint-only", "-Wall", "-Wno-fatal", "-Wno-DECLFILENAME", "-Wno-MULTITOP",
               "-Wno-UNUSEDSIGNAL", "-Wno-UNUSEDPARAM", "--timing", "-y", str(p.parent), f"+incdir+{p.parent}", *flags, str(p)]
    elif iverilog:
        cmd = [iverilog, "-g2012", "-Wall", "-t", "null", "-y", str(p.parent), f"-I{p.parent}", str(p)]
    else:
        return 0
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=45, errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        return 0
    if verilator and "Invalid option: --timing" in proc.stderr:  # Verilator 4.x
        cmd.remove("--timing")
        try:
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=45, errors="replace")
        except (subprocess.TimeoutExpired, OSError):
            return 0
    # Only report diagnostics located in the edited file; siblings are reported when they are edited.
    lines = [l for l in (proc.stderr + proc.stdout).splitlines()
             if p.name in l]
    lines = [l for l in lines
             if (l.startswith("%") or ": error:" in l or ": warning:" in l)
             and not any(n in l for n in ISOLATION_NOISE)]
    if not lines:
        return 0
    shown = lines[:20]
    more = f"\n(+{len(lines) - 20} more)" if len(lines) > 20 else ""
    msg = (f"eda-ops lint on {p.name} found {len(lines)} issue(s) after this edit:\n"
           + "\n".join(shown) + more +
           "\nFix real issues (latches, width mismatches, blocking/non-blocking misuse, multi-driven nets) "
           "now; mention any you intentionally leave.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
