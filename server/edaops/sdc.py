"""Static review of SDC / XDC timing constraints without needing a timing tool."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

_TCL_BRACKET = re.compile(r"\[[^\[\]]*\]")


def _commands(text: str) -> list[tuple[int, str]]:
    """Split Tcl-ish text into (line_no, command) honouring '\\' continuations, ';' and comments."""
    cmds: list[tuple[int, str]] = []
    buf, start = "", 0
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not buf:
            start = i
            if line.lstrip().startswith("#"):
                continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        for part in _split_semicolons(buf):
            part = part.strip()
            if part and not part.startswith("#"):
                cmds.append((start, part))
        buf = ""
    if buf.strip():
        cmds.append((start, buf.strip()))
    return cmds


def _split_semicolons(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
        if ch == ";" and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _tokens(cmd: str) -> list[str]:
    # Collapse nested [get_ports ...] into a single token so option parsing is simple.
    flat = cmd
    for _ in range(5):
        new = _TCL_BRACKET.sub(lambda m: m.group(0).replace(" ", "\x00"), flat)
        if new == flat:
            break
        flat = new
    flat = flat.replace("{", "\"").replace("}", "\"")
    try:
        toks = shlex.split(flat, posix=True)
    except ValueError:
        toks = flat.split()
    return [t.replace("\x00", " ") for t in toks]


def _opts(toks: list[str]) -> tuple[dict, list[str]]:
    opts: dict = {}
    pos: list[str] = []
    flags_without_value = {"-add", "-asynchronous", "-logically_exclusive", "-physically_exclusive",
                           "-setup", "-hold", "-max", "-min", "-rise", "-fall", "-start", "-end",
                           "-datapath_only", "-invert", "-combinational", "-clock_fall",
                           "-add_delay", "-network_latency_included", "-source_latency_included",
                           "-reset_path", "-ignore_clock_latency", "-quiet"}
    i = 1
    while i < len(toks):
        t = toks[i]
        if t.startswith("-") and not re.fullmatch(r"-\d+(\.\d+)?", t):
            if t in flags_without_value or i + 1 >= len(toks):
                opts[t] = True
                i += 1
            else:
                opts.setdefault(t, [])
                if isinstance(opts[t], list):
                    opts[t].append(toks[i + 1])
                i += 2
        else:
            pos.append(t)
            i += 1
    return opts, pos


def _obj_name(tok: str) -> str:
    """'[get_ports {clk}]' -> 'clk' (first object only)."""
    m = re.search(r"get_\w+\s+\"?\{?\s*([^\s\]\}\"]+)", tok)
    return m.group(1) if m else tok


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _finding(sev, line, rule, msg, fix=""):
    return {"severity": sev, "line": line, "rule": rule, "message": msg, "fix": fix}


def review(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}
    text = p.read_text(errors="replace")
    cmds = _commands(text)
    findings: list[dict] = []
    clocks: dict[str, dict] = {}
    gen_clocks: dict[str, dict] = {}
    seen = {k: 0 for k in ("set_input_delay", "set_output_delay", "set_clock_uncertainty",
                           "set_load", "set_driving_cell", "set_input_transition",
                           "set_clock_groups", "set_false_path", "set_multicycle_path",
                           "set_max_delay", "set_case_analysis", "set_disable_timing",
                           "set_clock_transition", "set_clock_latency")}
    uncertain_clocks: set[str] = set()
    mcp_setup: list[tuple[int, str]] = []
    mcp_hold: list[str] = []
    xdc = p.suffix.lower() == ".xdc"

    for line, cmd in cmds:
        toks = _tokens(cmd)
        if not toks:
            continue
        name = toks[0]
        opts, pos = _opts(toks)
        if name in seen:
            seen[name] += 1

        if name == "create_clock":
            period = _first(opts.get("-period"))
            cname = _first(opts.get("-name")) or (_obj_name(pos[0]) if pos else f"<unnamed@{line}>")
            if period is None:
                findings.append(_finding("error", line, "CLK-NOPERIOD", f"create_clock '{cname}' has no -period."))
                continue
            try:
                per = float(period)
            except ValueError:
                per = None
                findings.append(_finding("info", line, "CLK-VARPERIOD", f"Clock '{cname}' period is an expression "
                                         f"({period}); cannot check its value statically."))
            if per is not None and per <= 0:
                findings.append(_finding("error", line, "CLK-BADPERIOD", f"Clock '{cname}' period {per} <= 0."))
            if not opts.get("-name"):
                findings.append(_finding("info", line, "CLK-NONAME", "create_clock without -name; the clock takes the "
                                         "port name. Explicit names make reports and exceptions robust.",
                                         "Add -name <clk>."))
            if not pos:
                findings.append(_finding("info", line, "CLK-VIRTUAL", f"Clock '{cname}' has no source object (virtual "
                                         "clock). Fine for I/O budgeting; make sure it is intended."))
            if cname in clocks and "-add" not in opts:
                findings.append(_finding("error", line, "CLK-DUP", f"Clock '{cname}' defined twice (first at line "
                                         f"{clocks[cname]['line']}); the second overrides the first.",
                                         "Remove the duplicate or use -add for multiple clocks on one source."))
            wf = opts.get("-waveform")
            clocks[cname] = {"line": line, "period": per, "freq_mhz": round(1000 / per, 3) if per else None,
                             "source": pos[0] if pos else None, "waveform": _first(wf) if wf else None}

        elif name == "create_generated_clock":
            cname = _first(opts.get("-name")) or (pos[0] if pos else f"<gen@{line}>")
            if not opts.get("-source") and not xdc:
                findings.append(_finding("error", line, "GCLK-NOSRC", f"Generated clock '{cname}' has no -source.",
                                         "Add -source [get_pins <master clock pin>]."))
            if not any(k in opts for k in ("-divide_by", "-multiply_by", "-edges", "-combinational", "-invert")) and not xdc:
                findings.append(_finding("warning", line, "GCLK-NORATIO", f"Generated clock '{cname}' has no "
                                         "-divide_by/-multiply_by/-edges; it defaults to divide-by-1."))
            gen_clocks[cname] = {"line": line, "source": _first(opts.get("-source")),
                                 "master": _first(opts.get("-master_clock"))}

        elif name in ("set_input_delay", "set_output_delay"):
            if not opts.get("-clock"):
                findings.append(_finding("error", line, "IO-NOCLK", f"{name} without -clock: the delay is "
                                         "unclocked and the path is effectively unconstrained.",
                                         "Add -clock <clk> (a virtual clock is fine)."))
            if not opts.get("-max") and not opts.get("-min"):
                findings.append(_finding("info", line, "IO-NOMINMAX", f"{name} without -max/-min applies the "
                                         "same value to setup and hold; hold checks may be optimistic or pessimistic."))
            if pos and any("all_inputs" in t for t in pos) and name == "set_input_delay":
                findings.append(_finding("warning", line, "IO-ALLINPUTS", "set_input_delay on [all_inputs] also "
                                         "constrains clock input ports.",
                                         "Use [remove_from_collection [all_inputs] [get_ports <clk>]]."))

        elif name == "set_clock_uncertainty":
            for t in pos + [str(v) for v in opts.get("-from", []) + opts.get("-to", [])]:
                for m in re.findall(r"get_clocks\s+\"?\{?([\w\*/]+)", t):
                    uncertain_clocks.add(m)
            if not any("get_clocks" in t for t in pos):
                uncertain_clocks.add("*")

        elif name == "set_false_path":
            tgt = " ".join(str(_first(opts.get(k)) or "") for k in ("-from", "-to", "-through"))
            if re.search(r"(get_\w+\s+\*\s*\])|(^|\s)\*(\s|$)", tgt):
                findings.append(_finding("warning", line, "FP-WILDCARD", "set_false_path with a bare '*' wildcard "
                                         "can silently remove large parts of the design from timing.",
                                         "Narrow the object list and review with report_exceptions."))
            if "get_clocks" in tgt and opts.get("-from") and opts.get("-to"):
                findings.append(_finding("info", line, "FP-CLK2CLK", "Clock-to-clock false path. If the clocks are "
                                         "asynchronous, set_clock_groups -asynchronous states intent more clearly "
                                         "and covers both directions."))
            if not opts.get("-from") and not opts.get("-to") and not opts.get("-through"):
                findings.append(_finding("error", line, "FP-EMPTY", "set_false_path without -from/-to/-through."))

        elif name == "set_multicycle_path":
            (mcp_hold.append(cmd) if "-hold" in opts else mcp_setup.append((line, cmd)))
            try:
                n = int(float(pos[0])) if pos else None
            except ValueError:
                n = None
            if n is not None and n > 4 and "-hold" not in opts:
                findings.append(_finding("info", line, "MCP-LARGE", f"Multicycle of {n} cycles: confirm the "
                                         "design really holds data stable this long (enable/handshake)."))

        elif name == "set_max_delay" and "-datapath_only" not in opts and opts.get("-from") and opts.get("-to"):
            if "get_clocks" in str(opts.get("-from")) or "get_clocks" in str(opts.get("-to")):
                findings.append(_finding("info", line, "MAXD-CDC", "set_max_delay between clocks without "
                                         "-datapath_only still includes clock skew; for CDC buses -datapath_only "
                                         "(Vivado) or a separate skew check is usual."))

    # Design-level checks.
    if not clocks and not gen_clocks:
        findings.append(_finding("error", None, "NO-CLOCKS", "No create_clock found: every register path is "
                                 "unconstrained."))
    for c in clocks:
        if "*" not in uncertain_clocks and c not in uncertain_clocks and clocks[c]["source"] is not None:
            findings.append(_finding("warning", clocks[c]["line"], "CLK-NOUNCERT", f"Clock '{c}' has no "
                                     "set_clock_uncertainty: jitter/skew margin is zero pre-CTS.",
                                     f"set_clock_uncertainty -setup <v> [get_clocks {c}]"))
    if not seen["set_input_delay"]:
        findings.append(_finding("warning", None, "NO-INDELAY", "No set_input_delay: input-to-register paths "
                                 "are unconstrained (or timed only against a default)."))
    if not seen["set_output_delay"]:
        findings.append(_finding("warning", None, "NO-OUTDELAY", "No set_output_delay: register-to-output "
                                 "paths are unconstrained."))
    if not xdc and not (seen["set_driving_cell"] or seen["set_input_transition"]):
        findings.append(_finding("info", None, "NO-DRIVE", "No set_driving_cell / set_input_transition: inputs "
                                 "are driven with ideal (zero) transition."))
    if not xdc and not seen["set_load"]:
        findings.append(_finding("info", None, "NO-LOAD", "No set_load on outputs: output pins see zero load."))
    if mcp_setup and len(mcp_hold) < len(mcp_setup):
        for line, cmd in mcp_setup[: len(mcp_setup) - len(mcp_hold)]:
            findings.append(_finding("warning", line, "MCP-NOHOLD", "set_multicycle_path -setup N without a "
                                     "matching -hold N-1 moves the hold check too, usually causing large false "
                                     "hold violations.", "Add set_multicycle_path -hold <N-1> with the same -from/-to."))
    if len(clocks) + len(gen_clocks) > 1 and not seen["set_clock_groups"]:
        findings.append(_finding("info", None, "MULTI-CLK", f"{len(clocks) + len(gen_clocks)} clocks and no "
                                 "set_clock_groups: all clock pairs are timed as synchronous. Confirm which "
                                 "are really related."))
    rank = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (rank[f["severity"]], f["line"] or 0))
    return {
        "ok": not any(f["severity"] == "error" for f in findings),
        "file": str(p), "format": "xdc" if xdc else "sdc", "commands": len(cmds),
        "clocks": clocks, "generated_clocks": gen_clocks,
        "exception_counts": {k: v for k, v in seen.items() if v},
        "findings": findings,
        "summary": {s: sum(f["severity"] == s for f in findings) for s in ("error", "warning", "info")},
    }
