"""Locating EDA binaries and running them safely with timeouts and bounded output."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Each logical tool maps to candidate executable names, first match wins.
# Override any of them with an env var, e.g. EDAOPS_YOSYS=/opt/yosys/bin/yosys
TOOL_CANDIDATES: dict[str, list[str]] = {
    "verilator": ["verilator"],
    "iverilog": ["iverilog"],
    "vvp": ["vvp"],
    "yosys": ["yosys", "yowasp-yosys"],
    "sta": ["sta", "opensta"],
    "openroad": ["openroad"],
    "verible-lint": ["verible-verilog-lint"],
    "verible-format": ["verible-verilog-format"],
    "slang": ["slang"],
}

MAX_TEXT = 20_000  # characters of raw tool output returned to the model


def find_tool(tool: str) -> str | None:
    override = os.environ.get(f"EDAOPS_{tool.upper().replace('-', '_')}")
    if override:
        return override if (shutil.which(override) or Path(override).exists()) else None
    for name in TOOL_CANDIDATES.get(tool, [tool]):
        path = shutil.which(name)
        if path:
            return path
    return None


def tool_status() -> dict[str, str | None]:
    return {tool: find_tool(tool) for tool in TOOL_CANDIDATES}


def clip(text: str, limit: int = MAX_TEXT) -> str:
    """Keep the head and tail of long output; the middle is rarely the interesting part."""
    if len(text) <= limit:
        return text
    half = limit // 2
    dropped = len(text) - limit
    return f"{text[:half]}\n\n... [{dropped} characters omitted] ...\n\n{text[-half:]}"


def run(cmd: list[str], cwd: str | Path | None = None, timeout: int = 600,
        stdin: str | None = None) -> dict:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, input=stdin, capture_output=True, text=True,
            timeout=timeout, errors="replace",
        )
        return {"cmd": cmd, "returncode": proc.returncode,
                "stdout": proc.stdout, "stderr": proc.stderr, "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {"cmd": cmd, "returncode": None, "stdout": out, "stderr": err, "timed_out": True}
    except FileNotFoundError as exc:
        return {"cmd": cmd, "returncode": None, "stdout": "", "stderr": str(exc), "timed_out": False}


def resolve_files(files: list[str] | str, base: str | Path | None = None) -> list[str]:
    """Accept a list or a whitespace/comma separated string; expand globs; return absolute paths."""
    if isinstance(files, str):
        files = [f for f in files.replace(",", " ").split() if f]
    base_path = Path(base) if base else Path.cwd()
    out: list[str] = []
    for f in files:
        p = Path(f).expanduser()
        if not p.is_absolute():
            p = base_path / p
        if any(ch in f for ch in "*?["):
            out.extend(str(m) for m in sorted(p.parent.glob(p.name)))
        else:
            out.append(str(p))
    return out


def read_filelist(path: str | Path) -> tuple[list[str], list[str], list[str]]:
    """Parse a simple .f filelist: source files, +incdir+ dirs, +define+ macros. Nested -f is followed."""
    path = Path(path)
    files, incdirs, defines = [], [], []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.split("//")[0].strip()
        if not line or line.startswith("#"):
            continue
        for tok in line.split():
            tok = os.path.expandvars(tok)
            if tok.startswith("+incdir+"):
                incdirs += [str((path.parent / d).resolve()) for d in tok[8:].split("+") if d]
            elif tok.startswith("+define+"):
                defines += [d for d in tok[8:].split("+") if d]
            elif tok in ("-f", "-F"):
                continue
            elif tok.endswith(".f"):
                f2, i2, d2 = read_filelist(path.parent / tok)
                files += f2; incdirs += i2; defines += d2
            elif not tok.startswith(("-", "+")):
                files.append(str((path.parent / tok).resolve()))
    return files, incdirs, defines
