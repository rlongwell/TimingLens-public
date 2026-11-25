"""Draw the candidate's actual slice occupancy and timing slack from routed evidence."""
import argparse
import csv
import json
from pathlib import Path
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("sites", "comparison", "output"):
        parser.add_argument(key, type=Path)
    args = parser.parse_args()
    points = []
    with args.sites.open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            x, y = re.fullmatch(r"SLICE_X(\d+)Y(\d+)", row["site"]).groups()
            points.append((int(x), int(y), int(row["used"]), int(row["lut_sites"])))
    grid = np.zeros((max(p[1] for p in points)+1, max(p[0] for p in points)+1))
    for x, y, used, luts in points:
        grid[y, x] = 2 + luts if used else 1
    result = json.loads(args.comparison.read_text())
    metrics = {m["key"]:m for m in result["metrics"]}
    occupied = sum(p[2] for p in points)
    fig, (map_ax, bars) = plt.subplots(1, 2, figsize=(10.6, 5.3), gridspec_kw={"width_ratios":[1.1,1]})
    fig.patch.set_facecolor("#ffffff")
    fig.subplots_adjust(left=.075, right=.96, top=.78, bottom=.2, wspace=.39)
    fig.suptitle("125 MHz timing closure on the Zybo Z7-20", x=.065, y=.96, ha="left",
                 fontsize=19, fontweight="bold")
    fig.text(.065, .865, "104 parallel lanes  ·  Routed programmable logic  ·  8.000 ns clock period", fontsize=11)
    colors = ["#ffffff", "#dddddd", "#e2ecef", "#bfd7dc", "#81b1ba", "#458791", "#205864"]
    map_ax.imshow(grid, interpolation="nearest", origin="lower", vmin=0, vmax=6, cmap=ListedColormap(colors))
    map_ax.set_title(f"Revised placement  ·  {occupied/len(points):.1%} of slices occupied", fontsize=11, loc="left")
    map_ax.set_xlabel("Slice X"); map_ax.set_ylabel("Slice Y")
    map_ax.legend(handles=[Patch(color=c,label=str(n)) for n,c in enumerate(colors[2:])],
                  title="Occupied LUTs per slice", loc="upper center", bbox_to_anchor=(.5,-.18),
                  ncol=5, frameon=False, handlelength=1, columnspacing=1, fontsize=9)
    wns = metrics["setup.worst_slack_ns"]
    slack = [wns["before"],wns["after"]]
    y = [1,0]
    bars.barh(y,slack,color=["#bd6358","#367351"],height=.28)
    bars.axvline(0,linewidth=.9,color="#48525c")
    gap = max(1,max(abs(s) for s in slack))*.035
    for row, val in zip(y,slack):
        label = f"{val:+.3f} ns".replace("-", "−")
        bars.text(val/2, row+.19, label, ha="center", va="bottom", fontsize=12, fontweight="bold")
    bars.set_xlim(min(slack[0],0)-6*gap,max(slack[1],0)+7*gap)
    bars.set_ylim(-.55,1.6); bars.set_yticks(y,["Original","Revised"])
    bars.set_title("Worst setup slack",fontsize=11,loc="left"); bars.set_xlabel("Nanoseconds")
    for ax in (map_ax,bars):
        for side in ("top","right"): ax.spines[side].set_visible(False)
        ax.tick_params(labelsize=9)
    fig.savefig(args.output, dpi=180, bbox_inches="tight", pad_inches=.22)


if __name__ == "__main__":
    main()
