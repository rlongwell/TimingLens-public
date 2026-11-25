"""Choose one source-backed remap from measured Vivado pool capacity and primitive ownership."""
from collections import Counter
from dataclasses import dataclass
from math import ceil, isfinite
import json

from ..analysis.bd_multiplier import Multiplier, configurations
from ..analysis.fixes import FixPlan, Location
from ..analysis.inferred_memory import Memory, recognize
from .models import Check

LABELS = {"lut":"LUTs", "lutram":"memory-capable LUTs", "bram":"block RAM tiles", "dsp":"DSPs"}
ROWS = {"Slice LUTs":"lut", "CLB LUTs":"lut", "LUT as Memory":"lutram", "Block RAM Tile":"bram", "DSPs":"dsp"}


@dataclass(frozen=True)
class Pool:
    used: float
    available: float

    def exceeds(self, limit):
        return self.used * 100 > limit * self.available


def capacity(report):
    pools = {}
    headings = []
    for line in report.splitlines():
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if "Available" in cols and "Used" in cols:
            headings = cols
            continue
        key = ROWS.get(cols[0].rstrip("*"))
        if not key or not headings or len(cols) != len(headings):
            continue
        try:
            used, available = (float(cols[headings.index(k)].replace(",","")) for k in ("Used","Available"))
        except ValueError:
            continue
        if not all(isfinite(x) for x in (used, available)) or used < 0 or available < 0:
            raise ValueError(f"Invalid capacity for {LABELS[key]}.")
        pool = Pool(used, available)
        if key in pools and pools[key] != pool:
            raise ValueError(f"Conflicting utilization rows for {LABELS[key]}.")
        pools[key] = pool
    if pools.keys() != LABELS.keys():
        raise ValueError("The utilization report lacks complete LUT, distributed RAM, block RAM or DSP capacity.")
    return pools


def targets(sources):
    by_module = {}
    for source in sources:
        for target in configurations(source, both_mappings=True):
            by_module.setdefault(target.module, []).append(target)
        if memory := recognize(source):
            by_module.setdefault(memory.module, []).append(memory)
    return [items[0] for items in by_module.values() if len(items) == 1]


def owners(text):
    modules = {}
    for line in text.splitlines():
        module, instance, kind, count = line.split("\t")
        counts = modules.setdefault(module, {}).setdefault(instance, Counter())
        if kind in counts or not count.isdigit() or int(count) < 1:
            raise ValueError("Invalid primitive ownership record.")
        counts[kind] = int(count)
    return modules


@dataclass(frozen=True)
class Move:
    target: Memory | Multiplier
    source: str
    destination: str

    @property
    def description(self):
        return {"from": self.source, "to": self.destination, "module": self.target.module}

    @property
    def plan(self):
        mem = isinstance(self.target, Memory)
        scope = self.target.module if mem else f"{self.target.design}/{self.target.cell}"
        loc = Location(self.target.file, self.target.line, self.target.line, scope)
        return FixPlan("resource.memory" if mem else "resource.multiplier",
                       f"Move {scope} from {LABELS[self.source]} to {LABELS[self.destination]}",
                       "resource_balance", scope, (), "The mapped module occupies an over-budget resource.",
                       "Build and validate the alternative implementation.", source_candidates=(loc,))


def primitive_usage(counts, key):
    if key == "bram":
        return counts["ramb36"] + counts["ramb18"] / 2
    return counts[key]


def mappings(target):
    if isinstance(target, Multiplier):
        if target.construction == "Use_Mults":
            yield "dsp", "lut", 1
        else:
            yield "lut", "dsp", 1
        return

    bits = target.width * target.depth
    # Vivado chooses the original implementation for an unhinted or automatic RAM.
    # The native ownership inventory decides which direction applies.
    if target.style != "distributed":
        yield "bram", "lutram", ceil(bits / 64)
    if target.style != "block":
        yield "lutram", "bram", ceil(bits / 18432) / 2


def under_pressure(source, pools, limit):
    return pools[source].exceeds(limit) or (source == "lutram" and pools["lut"].exceeds(limit))


def proposals(candidates, ownership, pools, limit):
    ranked, skipped = [], []
    for target in candidates:
        instances = ownership.get(target.module, {})
        for src, dst, minimum in mappings(target):
            if not under_pressure(src, pools, limit):
                continue
            affected = [counts for counts in instances.values() if primitive_usage(counts, src) > 0]
            if not affected:
                skipped.append(f"No owned {LABELS[src]} were measured for {target.module}.")
                continue
            # This optimistic screen rejects known shortages. The routed build supplies actual usage.
            needed = sum(max(0, minimum - primitive_usage(counts, dst)) for counts in affected)
            consumers = (dst, "lut") if dst == "lutram" else (dst,)
            if any((pools[key].used + needed) * 100 > pools[key].available * limit for key in consumers):
                skipped.append(f"Insufficient {LABELS[dst]} headroom for {target.module} at {limit}% "
                               f"(at least {needed:g} additional units).")
                continue
            relief = sum(primitive_usage(counts, src) for counts in affected)
            pool_key = "lut" if src == "lutram" and not pools[src].exceeds(limit) else src
            capacity = pools[pool_key].available
            excess = pools[pool_key].used - capacity * limit / 100
            # Prefer the smallest single edit likely to meet the budget. If none
            # covers the excess, try the largest attributable reduction first.
            rank = (relief < excess, abs(relief - excess) / max(capacity, 0.5))
            ranked.append((rank, Move(target, src, dst)))
    ranked.sort(key=lambda item: (item[0], item[1].target.module))
    return [move for _, move in ranked], skipped


def verify_move(move, before, after, old_owners, new_owners, limit):
    if any(before[k].available != after[k].available for k in LABELS):
        raise ValueError("Device resource capacities changed.")
    if not under_pressure(move.source, before, limit):
        raise ValueError("The original resource was within budget.")
    if after[move.source].used >= before[move.source].used:
        raise ValueError("The selected resource did not decrease.")
    name = move.target.module
    old, new = old_owners.get(name, {}), new_owners.get(name, {})
    affected = {k for k,v in old.items() if primitive_usage(v,move.source)>0}
    if not affected or not affected <= new.keys() or any(
            primitive_usage(new[k],move.destination) <= primitive_usage(old[k],move.destination) or
            primitive_usage(new[k],move.source) >= primitive_usage(old[k],move.source) for k in affected):
        raise ValueError("The native netlist does not confirm the requested mapping on every affected instance.")
    over = [LABELS[k] for k in LABELS if after[k].exceeds(limit)]
    if over:
        raise ValueError(f"The routed candidate exceeds the {limit}% resource limit for " + ", ".join(over))


def measurements(pools):
    return {key: {"used":p.used,"available":p.available,"percent":round(100*p.used/p.available,3) if p.available else None}
            for key,p in pools.items()}


def record_budget(directory, baseline, move, pools, ownership, candidate):
    """Write the standalone receipt and return the Lab check for this routed experiment."""
    limit = baseline["limit_percent"]
    after = capacity(candidate.session.reports["utilization.rpt"])
    error = ""
    if move:
        try:
            verify_move(move, pools, after, ownership, owners((directory / "resource-owners.tsv").read_text()), limit)
        except ValueError as exc:
            error = str(exc)
    elif any(after[k].available != pools[k].available for k in LABELS):
        error = "Device resource capacities changed."
    elif any(pool.exceeds(limit) for pool in after.values()):
        error = "The timing candidate exceeds the configured resource budget."

    measured = measurements(after)
    change = move.description if move else None
    receipt = {**baseline, "move": change, "after": measured, "resource_check": error or "passed"}
    path = directory / "resource-budget.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    evidence = error or "All monitored pools meet the requested budget."
    if move and not error:
        counts = ", ".join(f"{LABELS[k]} {pools[k].used:g} → {after[k].used:g} of {after[k].available:g}"
                           for k in (move.source, move.destination))
        evidence = f"{move.target.module}: {counts}. Verified the mapping in every affected instance."
    check = Check(name="resource_budget", status="failed" if error else "passed",
                  scope=f"Routed resource usage against a {limit}% budget.", evidence=evidence)
    return path, measured, check
