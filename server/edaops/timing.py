"""Static timing report parsing (OpenSTA / OpenROAD / PrimeTime / Tempus 'report_checks'-style)."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

_NUM = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_START = re.compile(r"^\s*Startpoint:\s*(?P<pin>\S+)(?:\s*\((?P<desc>.*)\))?")
_END = re.compile(r"^\s*Endpoint:\s*(?P<pin>\S+)(?:\s*\((?P<desc>.*)\))?")
_GROUP = re.compile(r"^\s*Path Group:\s*(?P<g>\S+)")
_TYPE = re.compile(r"^\s*Path Type:\s*(?P<t>\S+)")
_SLACK = re.compile(rf"^\s*(?P<v>{_NUM})\s+slack\s*\((?P<s>[A-Z ]+)\)", re.I)
_SLACK_PT = re.compile(rf"^\s*slack\s*\((?P<s>[A-Z ]+)\)\s+(?P<v>{_NUM})", re.I)
_ARRIVAL = re.compile(rf"(?P<v>{_NUM})\s+data arrival time")
_ARRIVAL_PT = re.compile(rf"data arrival time\s+(?P<v>{_NUM})")
_REQUIRED = re.compile(rf"(?P<v>{_NUM})\s+data required time")
_REQUIRED_PT = re.compile(rf"data required time\s+(?P<v>{_NUM})")
_CLOCKED_BY = re.compile(r"clocked by\s+(\S+?)[\)'\s]")
_EDGE = {"^", "v", "r", "f"}

# Lines in the capture/launch section whose values matter for diagnosis.
_KEY_TERMS = {
    "clock network delay": "clock_network_delay",
    "clock uncertainty": "clock_uncertainty",
    "library setup time": "setup_time",
    "library hold time": "hold_time",
    "clock reconvergence pessimism": "crpr",
    "input external delay": "input_delay",
    "output external delay": "output_delay",
}


def _nums(s: str) -> list[float]:
    return [float(x) for x in re.findall(_NUM, s)]


def _parse_stage(line: str) -> dict | None:
    """A cell/net stage: '...numbers... <edge> pin (CELL)' (OpenSTA) or 'pin (CELL) ...numbers... r' (PT)."""
    toks = line.split()
    if len(toks) < 3:
        return None
    # OpenSTA style: numbers, edge marker, pin, (cell)
    for i, t in enumerate(toks):
        if t in ("^", "v") and i >= 1 and i + 1 < len(toks):
            nums = [float(x) for x in toks[:i] if re.fullmatch(_NUM, x)]
            if not nums:
                return None
            pin = toks[i + 1]
            cell = toks[i + 2].strip("()") if i + 2 < len(toks) and toks[i + 2].startswith("(") else ""
            delay = nums[-2] if len(nums) >= 2 else 0.0
            return {"pin": pin, "cell": cell, "edge": "rise" if t == "^" else "fall",
                    "delay": delay, "time": nums[-1], "fanout": None}
    # PrimeTime style: pin (CELL)  [fanout cap trans] incr  path  r|f
    if toks[-1] in ("r", "f") and len(toks) >= 4 and toks[1].startswith("("):
        nums = [float(x) for x in toks[2:-1] if re.fullmatch(_NUM, x.rstrip("*&"))]
        if len(nums) >= 2:
            return {"pin": toks[0], "cell": toks[1].strip("()"), "edge": "rise" if toks[-1] == "r" else "fall",
                    "delay": nums[-2], "time": nums[-1], "fanout": None}
    return None


def _parse_block(lines: list[str]) -> dict:
    p: dict = {"startpoint": None, "endpoint": None, "group": None, "path_type": None,
               "launch_clock": None, "capture_clock": None, "slack": None, "status": None,
               "arrival": None, "required": None, "stages": [], "terms": {}}
    in_capture = False
    for line in lines:
        if m := _START.match(line):
            p["startpoint"] = m["pin"]
            if m["desc"] and (c := _CLOCKED_BY.search(m["desc"] + " ")):
                p["launch_clock"] = c.group(1)
            p["start_desc"] = m["desc"] or ""
            continue
        if m := _END.match(line):
            p["endpoint"] = m["pin"]
            if m["desc"] and (c := _CLOCKED_BY.search(m["desc"] + " ")):
                p["capture_clock"] = c.group(1)
            p["end_desc"] = m["desc"] or ""
            continue
        if m := _GROUP.match(line):
            p["group"] = m["g"]; continue
        if m := _TYPE.match(line):
            p["path_type"] = m["t"]; continue
        if p["arrival"] is None and (m := _ARRIVAL.search(line) or _ARRIVAL_PT.search(line)):
            p["arrival"] = float(m["v"]); in_capture = True; continue
        if p["required"] is None and (m := _REQUIRED.search(line) or _REQUIRED_PT.search(line)):
            p["required"] = float(m["v"]); continue
        if m := _SLACK.match(line) or _SLACK_PT.match(line):
            p["slack"] = float(m["v"]); p["status"] = m["s"].strip().upper(); continue
        if "unconstrained" in line.lower() and "slack" in line.lower():
            p["status"] = "UNCONSTRAINED"; continue
        low = line.lower()
        for term, key in _KEY_TERMS.items():
            if term in low:
                n = _nums(line.split(term)[0]) or _nums(line)
                if n:
                    side = "capture" if in_capture else "launch"
                    p["terms"][f"{side}_{key}"] = n[0] if len(n) == 1 else n[-2]
                break
        else:
            if not in_capture and (st := _parse_stage(line)):
                p["stages"].append(st)
    if p["slack"] is not None and p["status"] is None:
        p["status"] = "VIOLATED" if p["slack"] < 0 else "MET"
    # Classify path endpoints for the reader.
    sd, ed = p.get("start_desc", "").lower(), p.get("end_desc", "").lower()
    s_kind = "input" if "input port" in sd else "reg"
    e_kind = "output" if "output port" in ed else "reg"
    # Logic depth = combinational cells between launch and capture: drop the launch flop's CK and Q pins
    # (or the input port) and the endpoint pin.
    data_stages = [s for s in p["stages"] if s["cell"]]
    head = 2 if s_kind == "reg" else 1
    gates = data_stages[head:-1] if len(data_stages) > head else []
    p["logic_depth"] = len(gates)
    p["top_stages"] = sorted(gates or data_stages, key=lambda s: s["delay"], reverse=True)[:5]
    p["path_class"] = f"{s_kind}2{e_kind}"
    p["cross_clock"] = bool(p["launch_clock"] and p["capture_clock"] and p["launch_clock"] != p["capture_clock"])
    p.pop("start_desc", None); p.pop("end_desc", None)
    return p


def parse_report(text: str) -> list[dict]:
    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for line in text.splitlines():
        if _START.match(line):
            if cur:
                blocks.append(cur)
            cur = [line]
        elif cur is not None:
            cur.append(line)
            if _SLACK.match(line) or _SLACK_PT.match(line):
                blocks.append(cur); cur = None
    if cur:
        blocks.append(cur)
    return [_parse_block(b) for b in blocks]


def summarise(paths: list[dict], top_n: int = 10) -> dict:
    constrained = [p for p in paths if p["slack"] is not None]
    out: dict = {"paths_parsed": len(paths), "unconstrained": sum(p["status"] == "UNCONSTRAINED" for p in paths)}
    for kind in ("max", "min"):
        ps = [p for p in constrained if (p["path_type"] or "max") == kind]
        if not ps:
            continue
        viol = [p for p in ps if p["slack"] < 0]
        # TNS counts each endpoint once (worst slack per endpoint), matching tool behaviour.
        worst_by_ep: dict[str, float] = {}
        for p in ps:
            ep = p["endpoint"] or "?"
            worst_by_ep[ep] = min(worst_by_ep.get(ep, p["slack"]), p["slack"])
        groups: dict[str, list[float]] = defaultdict(list)
        for p in ps:
            groups[p["group"] or "default"].append(p["slack"])
        label = "setup" if kind == "max" else "hold"
        out[label] = {
            "wns": round(min(p["slack"] for p in ps), 4),
            "tns": round(sum(s for s in worst_by_ep.values() if s < 0), 4),
            "violating_paths": len(viol),
            "violating_endpoints": sum(s < 0 for s in worst_by_ep.values()),
            "by_group": {g: {"wns": round(min(v), 4), "violations": sum(x < 0 for x in v)} for g, v in groups.items()},
            "cross_clock_violations": sum(p["cross_clock"] for p in viol),
            "worst_paths": [_brief(p) for p in sorted(ps, key=lambda p: p["slack"])[:top_n]],
        }
    out["patterns"] = _patterns(constrained)
    return out


def _brief(p: dict) -> dict:
    return {k: p[k] for k in ("startpoint", "endpoint", "group", "launch_clock", "capture_clock",
                              "slack", "arrival", "required", "logic_depth", "path_class",
                              "cross_clock", "terms", "top_stages")}


def _patterns(paths: list[dict]) -> list[str]:
    """Heuristic observations that point at the likely root cause class."""
    notes: list[str] = []
    viol = [p for p in paths if p["slack"] < 0 and (p["path_type"] or "max") == "max"]
    hold = [p for p in paths if p["slack"] < 0 and p["path_type"] == "min"]
    if viol:
        deep = [p for p in viol if p["logic_depth"] >= 15]
        if deep:
            notes.append(f"{len(deep)}/{len(viol)} setup violators have logic depth >= 15: "
                         "consider pipelining or restructuring logic.")
        cc = [p for p in viol if p["cross_clock"]]
        if cc:
            pairs = sorted({f"{p['launch_clock']}->{p['capture_clock']}" for p in cc})
            notes.append(f"{len(cc)} setup violators cross clock domains ({', '.join(pairs[:5])}): "
                         "verify these are real synchronous paths; if asynchronous, constrain with "
                         "set_clock_groups -asynchronous or set_max_delay -datapath_only, and check CDC synchronizers.")
        io = [p for p in viol if p["path_class"] != "reg2reg"]
        if io and len(io) >= len(viol) / 2:
            notes.append("Most setup violators are I/O paths: check set_input_delay/set_output_delay budgets "
                         "before touching logic.")
        starts = defaultdict(int)
        for p in viol:
            starts[p["startpoint"]] += 1
        hot = [(s, n) for s, n in starts.items() if n >= 3]
        if hot:
            s, n = max(hot, key=lambda x: x[1])
            notes.append(f"Startpoint {s} launches {n} violating paths: likely a high-fanout net; consider "
                         "register duplication or buffering.")
        cells = defaultdict(float)
        for p in viol:
            for st in p["top_stages"][:1]:
                cells[st["cell"]] += 1
        if cells:
            c, n = max(cells.items(), key=lambda x: x[1])
            if n >= max(3, len(viol) / 3):
                notes.append(f"Cell type {c} is the largest single delay on {int(n)} violators: check drive "
                             "strength / load (upsizing, buffering).")
        unc = [p["terms"].get("capture_clock_uncertainty") for p in viol if p["terms"].get("capture_clock_uncertainty")]
        if unc and all(u is not None for u in unc):
            worst = min(viol, key=lambda p: p["slack"])
            u = worst["terms"].get("capture_clock_uncertainty")
            if u and abs(worst["slack"]) < abs(u):
                notes.append("Worst setup violation is smaller than the clock uncertainty margin: check whether "
                             "uncertainty is over-constrained for this stage of the flow.")
    if hold:
        notes.append(f"{len(hold)} hold violations: fix after setup closure and with propagated clocks; "
                     "if clocks are still ideal, hold results are not meaningful yet.")
    return notes


def parse_file(path: str, top_n: int = 10) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}
    text = p.read_text(errors="replace")
    paths = parse_report(text)
    if not paths:
        return {"ok": False, "error": "No timing paths found. Expected 'Startpoint:/Endpoint:/slack' blocks "
                                      "from report_checks / report_timing."}
    return {"ok": True, "file": str(p), **summarise(paths, top_n)}
