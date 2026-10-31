# eda-ops

**An EDA toolkit for Claude Code.** It turns Claude into a working partner for RTL design, verification and
timing closure. It runs real open-source EDA tools and parses their output into structured data, so
Claude reasons from evidence instead of guessing from a wall of log text.

```
/plugin marketplace add bosons14/eda-ops
/plugin install eda-ops@eda-ops
```

## What it does

| You ask | eda-ops does |
|---|---|
| "Review my RTL before I push" | Lints with Verilator/Icarus, triages each warning as bug / risk / noise, checks CDC, reset, FSM and synthesizability, confirms latches with Yosys |
| "Why is timing failing?" | Parses OpenSTA / OpenROAD / PrimeTime / Tempus reports: WNS, TNS, violating endpoints, logic depth, dominant stage, clock-crossing flags, root-cause patterns, ranked fix plan |
| "Check my constraints" | Static SDC/XDC review: clocks and frequencies, generated clocks, I/O delays, uncertainty, risky false paths, multicycle setup/hold pairing, clock groups |
| "Why did synthesis fail?" | Streams multi-GB (or `.gz`) logs from Vivado, DC, Genus, Innovus, OpenROAD, Questa, Xcelium, VCS, Verilator, UVM, Yosys: groups by message ID, finds the first error and flags crashes, OOM, licence and disk problems |
| "How big is this? Did my change help?" | Yosys synthesis QoR: cells, area (with a liberty file), sequential cells, inferred latches, multi-drivers, variant comparison |
| "Write a testbench for this" | Builds self-checking testbenches and runs them with Icarus or Verilator to a PASS/FAIL verdict |

It also lints automatically: whenever Claude edits a `.v`/`.sv` file, a hook lints that file and
feeds real issues straight back, so Claude fixes latches and width bugs in the same turn.

## Components

**MCP server `eda-ops`** (Python, stdio): `eda_tool_status`, `lint_rtl`, `synthesize`, `simulate`,
`parse_timing_report`, `run_sta`, `triage_log`, `grep_log`, `review_sdc`.

**Skills**: `rtl-review`, `timing-closure`, `sdc-review`, `eda-log-triage`, `synthesis-qor`, `rtl-testbench`.
Each one triggers from natural requests and can also be run as a slash command, e.g. `/eda-ops:timing-closure`.

**Agents**: `rtl-reviewer` (an independent pre-merge reviewer) and `timing-closure-engineer` (multi-report,
multi-corner root-causing).

**Hook**: lint-on-edit for Verilog/SystemVerilog (PostToolUse on Write/Edit).

## Setup

You need Python 3.10+. Nothing else is required: if [uv](https://docs.astral.sh/uv/) is installed the server runs through it, otherwise the first launch creates a private virtual environment (`~/.cache/eda-ops/venv`) and installs the `mcp` package into it automatically (about 30 s, one time).

The EDA tools are optional. Each feature uses whatever is installed, and the parsers (timing, logs, SDC)
need no tools at all:

| Tool | Used for | Install |
|---|---|---|
| Verilator ≥ 5 | lint, hook, simulation | `apt install verilator` / `brew install verilator` |
| Icarus Verilog | lint fallback, simulation | `apt install iverilog` / `brew install icarus-verilog` |
| Yosys | synthesis, QoR, netlists | `apt install yosys`, or `pip install yowasp-yosys` (portable) |
| OpenSTA or OpenROAD | `run_sta` | build from source, or use the OpenROAD flow scripts container |
| Verible | style lint (`tool: "verible-lint"`) | GitHub releases |

Ask Claude to "check which EDA tools are available" to see what was detected.

### Environment variables

| Variable | Purpose |
|---|---|
| `EDAOPS_<TOOL>` (e.g. `EDAOPS_YOSYS=/opt/yosys/bin/yosys`) | Override a tool path |
| `EDAOPS_PROJECT_DIR` | Base directory for relative paths (defaults to the Claude Code project) |
| `EDAOPS_PYTHON` | Python interpreter to use when uv is not installed |
| `EDAOPS_HOOK_DISABLE=1` | Turn off lint-on-edit |
| `EDAOPS_HOOK_FLAGS` | Extra Verilator flags for the hook (e.g. `-Wno-WIDTH`) |

## Try it

The `examples/` folder contains a deliberately buggy ALU, a clean FIFO with a self-checking testbench, a
CDC bug, an OpenSTA timing report, a Vivado log and a flawed SDC. Open the plugin folder in Claude Code
and ask:

- "Review examples/rtl/alu.sv"
- "Analyze examples/reports/opensta_checks.rpt and tell me how to fix it"
- "Review examples/constraints/top.sdc"
- "Why did examples/reports/vivado_synth.log fail?"
- "Is the CDC in examples/rtl/cdc_bad.sv safe?"

## Troubleshooting

- **`Failed to reconnect to eda-ops: CONNECTION_CLOSED`**: run `sh ~/.claude/plugins/cache/eda-ops/eda-ops/*/server/run.sh < /dev/null` in a terminal and read the `eda-ops:` message it prints. The usual causes are no Python 3.10+, or `python3-venv` missing on Ubuntu (`sudo apt install python3-venv`).
- **Native Windows**: use WSL2. The launcher is a POSIX shell script.

## Development

```
python -m pytest -q tests        # parser tests always run; tool tests skip when a tool is missing
```

The parsers in `server/edaops/` are plain Python with no dependencies, so you can reuse them in your own
flows.

## Limits

- The SDC review is static. It cannot know your board timing or whether a path is truly false; it flags
  what needs a human decision.
- Generic-gate synthesis without a liberty file is for relative comparison, not area signoff.
- Commercial tools are supported through their logs and reports. eda-ops does not launch them.

## License

MIT © Subhendra Basu
