#!/usr/bin/env bash
# Build both integrated designs with the same script, run the scoreboard, collect
# TimingLens sessions, then generate the independent proof and Lab comparison.
set -euo pipefail
if [[ $# != 1 ]]; then
    echo "Usage: $0 NEW_OUTPUT_DIRECTORY" >&2
    exit 2
fi
src=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$src/../.." && pwd)
py=${TIMINGLENS_PYTHON:-"$repo/.venv/bin/python"}
vivado=${TIMINGLENS_VIVADO:-/opt/amd/xilinx/Vivado/2024.2/bin/vivado}
yosys=${TIMINGLENS_YOSYS:-"$(dirname "$py")/yowasp-yosys"}
export TIMINGLENS_VIVADO="$vivado"
mkdir -- "$1"
out=$(cd "$1" && pwd)
"$py" "$src/make_scoreboard.py" "$out/scoreboard"
for variant in original revised; do
    run="$out/$variant"
    mkdir -p "$run/src"
    cp "$src/fabric.v" "$src/timing.xdc" "$src/build.tcl" "$src/$variant/calibration.v" "$run/src/"
    (
        cd "$run"
        "$vivado" -mode batch -notrace -source src/build.tcl -tclargs src > implementation.log 2>&1
        "$vivado" -mode batch -notrace -source "$src/placement.tcl" -tclargs routed.dcp sites.tsv bank-timing.tsv > native-audit.log 2>&1
    )
    "$py" "$src/capture.py" "$run" "$run/timinglens"
    sim="$out/sim-$variant"
    mkdir "$sim"
    cp -a "$run/project" "$run/src" "$sim/"
    (
        cd "$sim"
        "$vivado" -mode batch -notrace -source "$src/sim.tcl" -tclargs project/dense.xpr "$out/scoreboard/tb.sv" > simulation.log 2>&1
    )
done
opts=()
if [[ -n ${TIMINGLENS_Z3_LIBRARY:-} ]]; then opts+=(--z3-library "$TIMINGLENS_Z3_LIBRARY"); fi
"$py" "$src/prove.py" "$out/original/src/calibration.v" "$out/revised/src/calibration.v" "$out/proof" --yosys "$yosys" "${opts[@]}"
"$py" "$src/compare_runs.py" "$out/original" "$out/revised" \
    "$out/original/timinglens/analysis.json" "$out/revised/timinglens/analysis.json" \
    "$out/sim-original/simulation.log" "$out/sim-revised/simulation.log" "$out/lab" --proof "$out/proof"
