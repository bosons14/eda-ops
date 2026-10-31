#!/bin/sh
# Launch the eda-ops MCP server over stdio.
# Order: uv (no installs needed) -> a Python 3.10+ that already has `mcp` -> a private venv created on first run.
# stdout is the MCP protocol channel: everything else must go to stderr.
HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/eda_mcp.py"
log() { echo "eda-ops: $*" >&2; }

if [ -z "$EDAOPS_NO_UV" ] && command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --no-project --with "mcp>=1.2,<3" python "$SERVER"
fi

PY=""
for c in "$EDAOPS_PYTHON" python3 python; do
  [ -n "$c" ] || continue
  command -v "$c" >/dev/null 2>&1 || continue
  if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  log "needs Python 3.10+ or uv. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if "$PY" -c "import mcp" >/dev/null 2>&1; then
  exec "$PY" "$SERVER"
fi

VENV="${CLAUDE_PLUGIN_DATA:-${XDG_CACHE_HOME:-$HOME/.cache}/eda-ops}/venv"
VPY="$VENV/bin/python"
[ -x "$VENV/Scripts/python.exe" ] && VPY="$VENV/Scripts/python.exe"
if [ ! -x "$VPY" ] || ! "$VPY" -c "import mcp" >/dev/null 2>&1; then
  log "first run: creating $VENV and installing the 'mcp' package (one time, about 30 s)"
  rm -rf "$VENV"  # never build on top of a half-created venv from an earlier failed attempt
  "$PY" -m venv "$VENV" >&2 || {
    rm -rf "$VENV"
    log "python -m venv failed. Ubuntu/Debian: sudo apt install python3-venv (or python3.X-venv). Or install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1; }
  VPY="$VENV/bin/python"; [ -x "$VENV/Scripts/python.exe" ] && VPY="$VENV/Scripts/python.exe"
  "$VPY" -m pip install -q --disable-pip-version-check "mcp>=1.2,<3" >&2 || {
    rm -rf "$VENV"; log "pip install mcp failed (offline or behind a proxy?)"; exit 1; }
fi
exec "$VPY" "$SERVER"
