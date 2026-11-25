"""Apply and validate a typed Xilinx IP parameter edit in a staged .bd."""
import json
import re
from pathlib import Path

from ..analysis.bd_multiplier import configurations
from .process import execute


def multiplier(result, plan):
    matches = [ip for source in result.session.sources for ip in configurations(source, both_mappings=True)
               if ip.file == plan.source_candidates[0].file and f"{ip.design}/{ip.cell}" == plan.scope]
    if len(matches) != 1:
        raise ValueError("The block-design recommendation no longer identifies one multiplier.")
    return matches[0]


def scoreboard(ip):
    width = ip.a + ip.b
    return f"""module timinglens_ip_check;
    logic clk = 0;
    always #4 clk = !clk;
    logic [{ip.a-1}:0] a;
    logic [{ip.b-1}:0] b;
    wire [{width-1}:0] p;
    {ip.module} dut(.CLK(clk), .A(a), .B(b), .P(p));
    logic [{width-1}:0] expected [0:{ip.latency-1}];
    logic [31:0] state = 32'h18abc937;
    function automatic [31:0] advance(input [31:0] x);
        begin x = x ^ (x << 13); x = x ^ (x >> 17); advance = x ^ (x << 5); end
    endfunction
    integer i, j;
    initial begin
        for (i=0; i<4096+{ip.latency}; i=i+1) begin
            @(negedge clk);
            state=advance(state); a=state; state=advance(state); a=(a << 32) | state;
            state=advance(state); b=state; state=advance(state); b=(b << 32) | state;
            case (i % 64)
                0: a=0;
                1: b=0;
                2: begin a='1; b='1; end
                3: begin a=1; b='1; end
            endcase
            for (j={ip.latency-1}; j>0; j=j-1) expected[j]=expected[j-1];
            expected[0]=a*b;
            @(posedge clk); #1;
            if (i>={ip.latency} && p !== expected[{ip.latency-1}])
                $fatal(1, "Product or latency mismatch at cycle %0d", i);
        end
        $display("TIMINGLENS_IP_PASS 4096 products");
        $finish;
    end
endmodule
"""


def run_ip(operation, project, bd, ip, directory, vivado, cancel, log, construction, script):
    directory.mkdir(parents=True, exist_ok=False)
    if operation == "simulate":
        (directory / "auto_ip_tb.sv").write_text(scoreboard(ip))
    transcript = directory / "vivado-output.log"
    args = [vivado, "-mode", "batch", "-notrace", "-source", script,
            "-tclargs", operation, project, bd, ip.cell, ip.module, ip.a, ip.b, ip.latency, construction]
    execute(args, directory, transcript, cancel, 900, log)
    if operation == "simulate":
        generated = project.with_suffix(".gen")
        wrappers = list(generated.glob(f"**/{ip.module}/sim/{ip.module}.vhd"))
        if len(wrappers) != 1:
            raise ValueError("Could not identify one generated Xilinx multiplier simulation model.")
        libs = re.findall(r"^LIBRARY (mult_gen_v[0-9_]+);", wrappers[0].read_text(), re.I | re.M)
        if len(libs) != 1:
            raise ValueError("The generated multiplier model has an unknown simulator library.")
        commands = (("xvhdl", "--work", "xil_defaultlib", wrappers[0]),
                    ("xvlog", "--sv", "--work", "xil_defaultlib", "auto_ip_tb.sv"),
                    ("xelab", "--mt", "2", "-L", "xil_defaultlib", "-L", libs[0],
                     "xil_defaultlib.timinglens_ip_check", "-s", "ip_check"),
                    ("xsim", "ip_check", "-runall"))
        for tool, *arguments in commands:
            transcript = directory / f"{tool}-output.log"
            execute([Path(vivado).parent/tool, *arguments], directory, transcript, cancel, 900, log)
        if "TIMINGLENS_IP_PASS 4096 products" not in transcript.read_text().splitlines():
            raise ValueError(f"XSim did not confirm the multiplier scoreboard. See {transcript}")
    return transcript


def mappings(ip):
    old = ip.construction
    return old, "Use_Mults" if old == "Use_LUTs" else "Use_LUTs"


def check_edit(original, revised, ip):
    before = json.loads(original)
    after = json.loads(revised)
    for doc, expect in zip((before, after), mappings(ip)):
        params = doc["design"]["components"][ip.cell]["parameters"]
        if params.pop("Multiplier_Construction", {}).get("value", "Use_LUTs") != expect:
            raise ValueError("Unexpected multiplier construction in the saved block design.")
    if after != before:
        raise ValueError("Vivado changed additional block-design configuration. See the retained candidate.")


def child_xci(layout, rel, ip):
    xci = rel.parent / "ip" / ip.module / (ip.module + ".xci")
    if xci not in layout.files:
        raise ValueError("The native child XCI is missing from the captured block design.")
    return xci


def check_xci(original, revised, ip):
    before, after = json.loads(original), json.loads(revised)
    for doc, construction in zip((before, after), mappings(ip)):
        model = "1" if construction == "Use_Mults" else "0"
        try:
            item = doc["ip_inst"]
            if (item["xci_name"], item["cell_name"], item["component_reference"]) != (
                    ip.module, ip.cell, "xilinx.com:ip:mult_gen:12.0"):
                raise ValueError("Native XCI identity changed.")
            params = item["parameters"]
            for group, name, value in (("component_parameters", "Multiplier_Construction", construction),
                                       ("model_parameters", "C_MULT_TYPE", model)):
                entry, = params[group][name]
                if entry.pop("value") != value:
                    raise ValueError("Unexpected multiplier setting in the child XCI.")
        except (KeyError, TypeError) as error:
            raise ValueError("Unexpected Xilinx multiplier XCI format.") from error
    if before != after:
        raise ValueError("Additional multiplier parameters changed in the child XCI.")


def simulate_copy(layout, project, rel, ip, directory, vivado, cancel, log, construction, script):
    import shutil
    work = directory/"project"
    target = layout.clone(work)
    for dep in (rel, child_xci(layout, rel, ip)):
        shutil.copy2(project.parent / dep, work / dep)
    return run_ip("simulate",target,work/rel,ip,directory/"xsim",vivado,cancel,log,construction,script)


def routed_dsps(directory, vivado, module, cancel, log):
    folder = directory / "dsp-inspection"
    folder.mkdir(exist_ok=False)
    script = directory.parent / "recipe/experiments/auto_dsp_cells.tcl"
    execute([vivado, "-mode", "batch", "-notrace", "-source", script, "-tclargs", directory/"routed.dcp", module],
            folder, folder/"vivado-output.log", cancel, 600, log)
    return folder / "dsp-ownership.txt"


def pipeline_advisories(before, after, owned):
    """Qualify new warning families only when their full native detail is present."""
    from collections import Counter

    def warnings(run):
        matches = re.findall(r"^([A-Za-z0-9_]+-\d+)#\d+ Warning[ \t]*\n[^\n]*\n([^\n]+)",
                             run.session.reports.get("drc.rpt", ""), re.M)
        if len(matches) != run.metrics.get("drc.warnings"):
            raise ValueError("Incomplete DRC warning detail prevents automatic classification.")
        return matches

    previous = Counter(rule for rule, _ in warnings(before))
    current = warnings(after)
    counts = Counter(rule for rule, _ in current)
    increases = {key for key, count in counts.items() if count > previous[key]}
    unknown = increases - {"DPIP-1", "DPOP-2"}
    if unknown:
        raise ValueError("Additional DRC warnings require review: " + ", ".join(sorted(unknown)))
    for key, detail in current:
        if key not in increases:
            continue
        words = detail.split()
        if len(words) < 3 or words[0] != "DSP" or words[1] not in owned:
            raise ValueError(f"{key} also affects a DSP outside the verified multiplier.")
    return {key: counts[key] for key in sorted(increases)}


def warning_check(before, after):
    """Keep the warning-family decision in the portable Lab record, including rejections."""
    from .models import Check
    owned = set(after.attachments.get("validation/dsp-ownership.txt", "").splitlines())
    scope = "Change in each DRC warning family under Vivado’s native rule deck."
    try:
        qualified = pipeline_advisories(before, after, owned)
    except ValueError as error:
        return Check(name="drc_warning_review", status="failed", scope=scope, evidence=str(error)), {}
    detail = "No DRC warning family increased."
    if qualified:
        notes = ", ".join(f"{rule} ({count})" for rule, count in qualified.items())
        detail = f"All additional warnings are scoped pipeline advisories on verified DSPs: {notes}."
    return Check(name="drc_warning_review", status="passed", scope=scope, evidence=detail), qualified
