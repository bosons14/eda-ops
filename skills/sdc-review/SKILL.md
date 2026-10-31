---
name: sdc-review
description: >
  This skill should be used when the user asks to "review my SDC", "check my constraints", "review this
  XDC", "are my timing constraints correct", "write constraints for this design", "add a generated
  clock", or runs /sdc-review. Covers clocks, generated clocks, I/O delays, uncertainty, exceptions
  (false paths, multicycles, max delay) and clock groups in SDC and Vivado XDC.
metadata:
  version: "0.1.0"
---

# SDC / XDC review

Constraints decide what "timing clean" means. A wrong constraint hides real failures; review them with
the same rigour as RTL.

## Procedure

1. **Run the static checker.** Call `review_sdc` (eda-ops MCP) on each constraints file. It returns the
   clock table (name, period, MHz, source), exception counts, and findings with line numbers.
2. **Cross-check against the design** when RTL is available:
   - Every clock input port / PLL output / clock divider in RTL has a `create_clock` or
     `create_generated_clock`. Grep RTL for `posedge`/`negedge` signals and list their sources.
   - Generated clocks reference the right master pin and ratio (a `cnt[0]` divider is `-divide_by 2`).
   - Every top-level data port has an input or output delay, against the clock that actually samples it.
   - Clock relationships: decide which clocks are synchronous (same source) and which are asynchronous;
     asynchronous groups must be declared with `set_clock_groups -asynchronous` and the crossings must
     have synchronizers in RTL (see the `rtl-review` skill CDC reference).
3. **Judge each exception** - every `set_false_path`, `set_multicycle_path`, `set_max_delay`,
   `set_disable_timing`, `set_case_analysis` needs a functional justification. Flag:
   - wildcards that match far more than intended,
   - multicycle setup without the matching hold,
   - false paths used to paper over real synchronous paths,
   - exceptions that reference objects that may not exist after synthesis (renamed registers).
4. **Explain the findings** using `references/sdc-cheatsheet.md` for correct command forms.
5. **Write fixes** as a patch to the constraints file, keeping the user's structure and comments.
   Prefer explicit names (`-name`) and collections over wildcards. When writing constraints from
   scratch, follow the template order in the cheatsheet.

## Output format

- Clock table (name | period | MHz | source | group).
- Findings table ordered error > warning > info: line | rule | issue | fix.
- Patch (diff) when fixes are requested.
- Open questions the user must answer (e.g. board input delay values) - never invent I/O budgets;
  mark them as TODO with a reasonable placeholder such as 40-60% of the period and say so.
