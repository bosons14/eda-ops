"""Streaming triage of large EDA tool logs (synthesis, P&R, STA, simulation).

Handles multi-GB logs line by line and groups messages by tool message ID so that
10,000 copies of the same warning become one row with a count.
"""

from __future__ import annotations

import gzip
import re
from collections import OrderedDict, deque
from pathlib import Path

SEV_RANK = {"fatal": 0, "error": 1, "critical": 2, "warning": 3, "info": 4}

# (regex, severity-group-name or fixed severity, id-group-name, tool family)
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Vivado / Vitis: CRITICAL WARNING: [Constraints 18-512] msg
    (re.compile(r"^(?P<sev>CRITICAL WARNING|WARNING|ERROR|INFO):\s*\[(?P<id>[^\]]+-\d+)\]\s*(?P<msg>.*)"), "vivado"),
    # OpenROAD / OpenSTA: [WARNING GRT-0097] msg
    (re.compile(r"^\[(?P<sev>ERROR|WARNING|CRITICAL|INFO)\s+(?P<id>[A-Z]{2,5}-\d+)\]\s*(?P<msg>.*)"), "openroad"),
    # Cadence Innovus/Tempus: **WARN: (IMPPSP-1003): msg  |  **ERROR: (TCLCMD-917): msg
    (re.compile(r"^\*\*(?P<sev>WARN|ERROR|INFO)\s*:\s*\((?P<id>[A-Z0-9_]+-\d+)\):?\s*(?P<msg>.*)"), "cadence"),
    # Cadence Genus / Xcelium: Warning : msg [ID-123]   |  xmelab: *W,CUVWSP (file,12|3): msg
    (re.compile(r"^(?P<sev>Error|Warning|Info)\s*:\s*(?P<msg>.*?)\s*\[(?P<id>[A-Z0-9_]+-\d+)\]"), "cadence"),
    (re.compile(r"^\w+:\s*\*(?P<sev>[EWFN]),(?P<id>[A-Z0-9_]+)(?:\s*\([^)]*\))?:\s*(?P<msg>.*)"), "xcelium"),
    # Synopsys DC/PT/ICC2/VCS: Warning: msg (LINT-1)  |  Error-[SE] Syntax error
    (re.compile(r"^(?P<sev>Error|Warning|Information|Fatal):\s*(?P<msg>.*?)\s*\((?P<id>[A-Z][A-Z0-9_]*-\d+)\)\s*$"), "synopsys"),
    (re.compile(r"^(?P<sev>Error|Warning|Lint|Note)-\[(?P<id>[A-Z0-9_-]+)\]\s*(?P<msg>.*)"), "vcs"),
    # Verilator: %Warning-WIDTH: file:1:2: msg
    (re.compile(r"^%(?P<sev>Warning|Error)(?:-(?P<id>[A-Z0-9_]+))?:\s*(?P<msg>.*)"), "verilator"),
    # Questa/ModelSim: ** Error (suppressible): (vlog-2388) msg   |  ** Warning: (vsim-3015) msg
    (re.compile(r"^\*\*\s*(?P<sev>Error|Warning|Fatal|Note)(?:\s*\([^)]*\))?:\s*(?:\((?P<id>[a-z]+-\d+)\))?\s*(?P<msg>.*)"), "questa"),
    # UVM: UVM_ERROR file(12) @ 100: reporter [ID] msg
    (re.compile(r"^(?P<sev>UVM_FATAL|UVM_ERROR|UVM_WARNING)\b.*?\[(?P<id>[^\]]+)\]\s*(?P<msg>.*)"), "uvm"),
    # Yosys / generic: Warning: msg  |  ERROR: msg
    (re.compile(r"^(?P<sev>ERROR|Error|WARNING|Warning|FATAL|Fatal|CRITICAL|Critical)\s*[:!]\s*(?P<msg>.+)"), "generic"),
]

_FATAL_SIGNS = [
    (re.compile(r"segmentation fault|sigsegv|core dumped", re.I), "Tool crashed (segfault)."),
    (re.compile(r"out of memory|std::bad_alloc|cannot allocate memory|memory exhausted", re.I), "Ran out of memory."),
    (re.compile(r"^\s*Killed\s*$|oom-killer", re.I), "Process killed (likely OOM killer)."),
    (re.compile(r"licen[cs]e.*(fail|unavailable|denied|not available|checkout)", re.I), "License checkout problem."),
    (re.compile(r"\babort(ed)?\b|internal error|assertion .* failed", re.I), "Tool internal error/abort."),
    (re.compile(r"timing (is )?not met|negative slack|failed to meet the timing", re.I), "Tool reports timing not met."),
    (re.compile(r"^\w+ failed\b|^Command failed|exited with errors|errors? encountered", re.I), "A tool command failed."),
    (re.compile(r"no space left on device|disk quota", re.I), "Disk full."),
]

_NORMALISE = [
    (re.compile(r"'[^']*'|\"[^\"]*\"|`[^']*'"), "<name>"),
    (re.compile(r"(/[\w.\-]+)+"), "<path>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
    (re.compile(r"-?\d+(\.\d+)?"), "<n>"),
    (re.compile(r"\s+"), " "),
]


def _sev(raw: str, family: str) -> str:
    r = raw.lower()
    if family == "xcelium":
        return {"e": "error", "w": "warning", "f": "fatal", "n": "info"}[r]
    if "fatal" in r:
        return "fatal"
    if "critical" in r:
        return "critical"
    if r.startswith("err") or r == "uvm_error":
        return "error"
    if r.startswith("warn") or r in ("uvm_warning", "lint"):
        return "warning"
    return "info"


def _normalise(msg: str) -> str:
    for pat, rep in _NORMALISE:
        msg = pat.sub(rep, msg)
    return msg.strip()[:160]


def _open(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", errors="replace")
    return path.open("r", errors="replace")


def triage(path: str, max_groups: int = 40, include_info: bool = False, tail_lines: int = 25,
           context: int = 2) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}
    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    tail: deque[str] = deque(maxlen=tail_lines)
    before: deque[str] = deque(maxlen=context)
    families: dict[str, int] = {}
    fatal_signs: list[dict] = []
    first_error: dict | None = None
    n = 0
    with _open(p) as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            tail.append(line)
            stripped = line.strip()
            for pat, hint in _FATAL_SIGNS:
                if len(fatal_signs) < 20 and pat.search(stripped):
                    fatal_signs.append({"line": n, "hint": hint, "text": stripped[:300]})
                    break
            for pat, family in _PATTERNS:
                m = pat.match(stripped)
                if not m:
                    continue
                sev = _sev(m["sev"], family)
                if sev == "info" and not include_info:
                    break
                mid = (m.groupdict().get("id") or "").strip()
                msg = (m["msg"] or "").strip()
                key = (sev, mid) if mid else (sev, _normalise(msg))
                g = groups.get(key)
                if g is None:
                    g = groups[key] = {"severity": sev, "id": mid, "family": family, "count": 0,
                                       "first_line": n, "last_line": n, "example": msg[:400],
                                       "context_before": list(before)}
                g["count"] += 1
                g["last_line"] = n
                families[family] = families.get(family, 0) + 1
                if first_error is None and sev in ("fatal", "error"):
                    first_error = {"line": n, "text": stripped[:400], "context_before": list(before)}
                break
            before.append(stripped[:300])
    ordered = sorted(groups.values(), key=lambda g: (SEV_RANK[g["severity"]], -g["count"]))
    totals: dict[str, int] = {}
    for g in groups.values():
        totals[g["severity"]] = totals.get(g["severity"], 0) + g["count"]
    return {
        "ok": True, "file": str(p), "lines": n,
        "detected_tools": sorted(families, key=families.get, reverse=True),
        "totals": totals, "unique_messages": len(groups),
        "first_error": first_error,
        "fatal_signs": fatal_signs,
        "groups": ordered[:max_groups], "groups_truncated": len(ordered) > max_groups,
        "tail": list(tail),
    }


def grep_id(path: str, message_id: str, limit: int = 50) -> dict:
    """Return every occurrence of one message ID (or substring) with line numbers."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}
    hits = []
    total = 0
    with _open(p) as fh:
        for n, line in enumerate(fh, 1):
            if message_id in line:
                total += 1
                if len(hits) < limit:
                    hits.append({"line": n, "text": line.strip()[:400]})
    return {"ok": True, "id": message_id, "total": total, "hits": hits}
