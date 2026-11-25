# Guided desktop workflow

TimingLens now opens on **Start here**. Choose design files to stage a Vivado project or checkpoint for analysis, or stage reports, RTL and constraints for offline analysis. Selection alone never runs a tool. Multiple Vivado designs are rejected with a clear message; additional context can accompany one design.

The primary navigation is Start here, Overview, Fix recommendations and Experiment Lab. **Show tools and details** exposes the timing graph, source browser, file staging and experiment runners. Following a source/path link reveals the relevant navigation automatically. The visible Light / Dark theme switch preserves current edits.

**Review counter experiment** selects the existing 32-bit, 250 MHz profile. Review the syntax-highlighted RTL change, inspect Validation and recipe, then select **Validate and run experiment**. Vivado location, output parent and timeout are under Advanced settings. The runner reports validation, baseline implementation, candidate implementation and comparison as four understandable stages. Cancel retains staged evidence.

The guided 250 MHz experiment opens the whole-core (global out-of-context) comparison automatically. Register-only evidence remains available through Compare registers. Existing 2 ns stress profiles keep their original default register comparison, and every verdict still uses the original comparison policy.

The Lab shows baseline → candidate setup slack, failing setup endpoints and physical LUT use above the detailed tables. Missing values say Not supplied. The next-step message identifies failed checks, regressions or untested checks, including integrated design validation. These summaries never turn missing checks into passes or change acceptance rules.

All source changes and tool runs remain isolated. This workflow does not program a board or alter the original design.
