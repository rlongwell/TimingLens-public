"""TimingLens command line interface."""
from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version as package_version
import logging
from pathlib import Path
import sys

from .demo import TOPS, request_for
from .export.html import value
from .rules.library import Thresholds
from .service import collect, export_result, load, inspect_files
from .vivado.runner import Cancelled, Request, VivadoError, discover, probe, version

LOG = logging.getLogger("timinglens")


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(prog="timinglens", description="Deterministic Vivado timing and RTL analysis")
    sub = app.add_subparsers(dest="command", required=True)
    gui = sub.add_parser("gui", help="open the TimingLens desktop")
    gui.add_argument("session", nargs="?", type=Path, help="optional analysis.json to open")
    doctor = sub.add_parser("doctor", help="probe Python, Vivado, Tcl commands, and device support")
    doctor.add_argument("--vivado", help="path to the Vivado executable")
    comparison = sub.add_parser('compare', help='compare completed run records or native sessions offline')
    comparison.add_argument('--baseline', type=Path, required=True)
    comparison.add_argument('--candidate', type=Path, required=True)
    comparison.add_argument('--output', type=Path, required=True, help='new directory for portable run evidence and HTML report')
    automatic = sub.add_parser("auto-fix", help="route a project, try supported RTL and Xilinx IP fixes, and retain verified changes")
    automatic.add_argument("--project", required=True, type=Path, help="self-contained local Vivado .xpr")
    automatic.add_argument("--output", required=True, type=Path, help="new job directory for projects and measured evidence")
    automatic.add_argument("--vivado")
    automatic.add_argument("--max-paths", type=int, default=48)
    automatic.add_argument("--resource-limit", type=int, metavar="PERCENT",
                           help="also rebalance supported resource mappings above this device utilization budget")
    automatic.add_argument("--apply-to-source", action="store_true",
                           help="also atomically update the selected project's source after verification, retaining a backup")
    proof = sub.add_parser("verify-fix", help="select a measured arithmetic pipeline fix and prove the generated RTL in an isolated copy")
    proof.add_argument("--session", required=True, type=Path, help="TimingLens session with captured RTL")
    proof.add_argument("--output", required=True, type=Path, help="new directory for the generated source, diff and proof")
    proof.add_argument("--routed-pair", type=Path, nargs=2, metavar=("BASELINE_RUN", "CANDIDATE_RUN"),
                       help="also assess this exact edit against completed design-wide Experiment Lab run records")
    proof.add_argument("--module", help="select a particular recommended module")
    proof.add_argument("--yosys", help="Yosys executable with the functional SMT backend")
    proof.add_argument("--z3-library", help="libz3 path if Z3 is not discovered automatically")
    experiment = sub.add_parser('experiment', help='run a bundled counter fix in fresh isolated copies')
    experiment.add_argument('--example', choices=('counter32','counter64','counter32_250'), required=True)
    experiment.add_argument('--output', type=Path, help='new job directory; required unless previewing; never overwritten')
    experiment.add_argument('--vivado', help='Vivado 2024.2 executable')
    experiment.add_argument('--verilator', help='Verilator executable')
    experiment.add_argument('--timeout', type=float, default=900., help='timeout in seconds per tool process (1–7200)')
    experiment.add_argument('--preview', action='store_true', help='print the source-exact recipe without creating a job or running tools')
    experiment.add_argument('--sweep', action='store_true', help='try Default, Performance_Explore and Performance_ExtraTimingOpt sequentially')
    suggested=sub.add_parser('try-experiment',help='execute an allowlisted recommendation from captured example evidence')
    suggested.add_argument('--session',type=Path,required=True,help='native TimingLens analysis.json; referenced paths are not followed')
    suggested.add_argument('--plan',choices=('vivado.remap','vivado.fanout','vivado.extra_timing','rtl.priority_balanced','rtl.priority_sweep'),required=True)
    suggested.add_argument('--output',type=Path,help='new job directory; required unless previewing')
    suggested.add_argument('--preview',action='store_true')
    suggested.add_argument('--vivado');suggested.add_argument('--verilator');suggested.add_argument('--yosys',help='Yosys 0.69 executable for RTL equivalence')
    suggested.add_argument('--timeout',type=float,default=900.)
    live = sub.add_parser("analyze", help="collect and diagnose Vivado timing")
    choice = live.add_mutually_exclusive_group(required=True)
    choice.add_argument("--project", type=Path)
    choice.add_argument("--checkpoint", type=Path)
    live.add_argument("--run", default="", help="explicit Vivado project run name")
    live.add_argument("--build", choices=("none", "synth", "route"), default="none",
                      help="optionally build in an isolated copy of the project")
    live.add_argument("--source", "--file", action="append", default=[], type=Path, help="additional RTL, Tcl, XDC or BD context file; repeatable")
    inspection = sub.add_parser("inspect", help="analyze selected RTL, Tcl/BD/XDC and timing reports offline; never executes Tcl")
    inspection.add_argument("--files", nargs='+', type=Path, required=True)
    inspection.add_argument("--top", help="RTL top module for report-only hierarchy correlation")
    inspection.add_argument("--output", type=Path, required=True)
    imported = sub.add_parser("import", help="validate and analyze a TimingLens JSON session")
    imported.add_argument("--report", type=Path, required=True)
    imported.add_argument("--output", type=Path, help="optional JSON and HTML export destination")
    imported.add_argument("--resolve-local-sources", action="store_true",
                          help="read local source paths if their bytes match the session digest")
    demo = sub.add_parser("demo", help="run bundled SystemVerilog examples through Vivado")
    demo.add_argument("--run-vivado", action="store_true", required=True)
    demo.add_argument("--design", choices=(*TOPS, "all"), default="all")
    demo.add_argument("--build", choices=("synth", "route"), default="route")
    for command in (live, demo):
        command.add_argument("--vivado", help="path to the Vivado executable")
        command.add_argument("--output", type=Path, required=command == live, default=Path("results/demo"))
        command.add_argument("--max-paths", type=int, default=100)
        command.add_argument("--paths-per-endpoint", type=int, default=3)
        command.add_argument("--no-source-text", action="store_true", help="omit source snapshots from exported JSON")
    for command in (live, demo, imported, inspection):
        command.add_argument("--thresholds", type=Path, help="JSON override of deterministic rule thresholds")
    return app


def _doctor(configured: str | None) -> int:
    print(f"Python {sys.version.split()[0]} at {sys.executable}")
    for package in ("pydantic", "pyslang", "PySide6"):
        try:
            print(f"{package} {package_version(package)}")
        except PackageNotFoundError:
            print(f"{package} unavailable")
    executable = discover(configured)
    print(f"Vivado executable {executable}")
    release = version(executable)
    print(f"Vivado version {release}" + (" (validated release)" if release == "2024.2" else " (outside validated release)"))
    results = probe(executable)
    for command, present in results.items():
        print(f"{command}: {'available' if present else 'unavailable'}")
    return 0 if all(results.values()) else 1


def _print_result(result, output=None) -> None:
    print(f"{result.session.top or result.session.name} · {result.session.stage} · {result.failing_paths} failing paths · "
          f"{len(result.findings)} findings · {len(result.investigations)} investigations")
    for kind, data in result.session.summary.items():
        print(f"  {kind}: worst slack {value(data.worst_slack_ns, ' ns')}, "
              f"total negative slack {value(data.total_negative_slack_ns, ' ns')}, "
              f"failing endpoints {value(data.failing_endpoints)}")
    print(f"  {result.coverage_note}")
    for warning in result.warnings:
        print(f"  Note: {warning}")
    if result.investigations:
        for plan in result.investigations[0].plans:
            print(f"  Candidate: {plan.title} [{plan.kind}]")
            for change in plan.changes:
                print(f"    {change.status}: {change.location.file}:{change.location.first}: {change.original} → {change.proposed}")
            for command in plan.commands:
                print(f"    {command}")
    for plan in result.project_plans:
        print(f"  Project candidate: {plan.title} [{plan.kind}]")
    if output:
        print(f"  {output.resolve() / 'report.html'}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.command == "gui":
            try:
                from .gui.app import launch
            except ModuleNotFoundError as error:
                raise VivadoError("Install TimingLens with the gui extra to use the desktop") from error
            return launch(args.session)
        if args.command == "doctor":
            return _doctor(args.vivado)
        if args.command == "auto-fix":
            from .experiments.auto_fix import AutoRequest, run_auto
            from .experiments.process import ProcessFailure
            try:
                job = run_auto(AutoRequest(args.project, args.output, args.vivado, args.apply_to_source, args.max_paths, args.resource_limit),
                               log=lambda text: LOG.info("%s", text))
            except ProcessFailure as error:
                raise ValueError(str(error)) from error
            print(f"{job.status}: {job.message}\n{job.directory / 'decision.json'}")
            return 0 if job.status in {"applied", "already_closed"} else 1
        if args.command == "verify-fix":
            from .experiments.pipeline_proof import prepare, verify
            result = load(args.session)
            plan = next((plan for issue in result.investigations for plan in issue.plans
                         if plan.id == "rtl.redistribute_arithmetic" and (not args.module or plan.scope == args.module)), None)
            if not plan:
                raise ValueError("No supported arithmetic pipeline rewrite matches the measured evidence.")
            candidate = prepare(result, plan)
            path = verify(candidate, args.output, yosys=args.yosys, z3_library=args.z3_library)
            print(f"{plan.title}\nCycle equivalence passed. {path.resolve()}")
            if args.routed_pair:
                from .experiments.io import export_comparison, load_run
                from .experiments.pipeline_proof import compare_routed
                comparison = compare_routed(candidate, path, *(load_run(file) for file in args.routed_pair))
                destination = args.output / "comparison"
                export_comparison(comparison, destination)
                print(f"{comparison.headline} Lab acceptance: {comparison.acceptance}. {destination.resolve() / 'report.html'}")
                return 0 if comparison.outcome == "improved" and comparison.acceptance == "review_ready" else 1
            return 0
        if args.command == 'try-experiment':
            from .experiments.recommendation import prepare_experiment
            from .experiments.recommendation_runner import RecommendationRequest,run_recommendation
            from .experiments.runner import JobFailure
            result=load(args.session)
            plan=next((p for group in result.investigations for p in group.plans if p.id==args.plan),None)
            prepared=prepare_experiment(result,plan)
            if args.preview:print(prepared.preview());return 0
            if args.output is None:raise ValueError('A new --output job directory is required.')
            import signal
            from threading import Event
            cancel=Event();previous=signal.signal(signal.SIGTERM,lambda *_:cancel.set())
            try:
                job=run_recommendation(RecommendationRequest(prepared,args.output,args.vivado,args.verilator,args.timeout,args.yosys),LOG.info,cancel=cancel)
            except JobFailure as error:
                LOG.error('TimingLens: %s',error);return 130 if error.status=='cancelled' else 1
            finally:signal.signal(signal.SIGTERM,previous)
            from .experiments.rtl_sweep_runner import RTLSweepResult
            if isinstance(job,RTLSweepResult):
                print('RTL sweep '+job.status+': '+str(job.sweep_path));return 0 if job.status=='completed' else 130 if job.status=='cancelled' else 1
            print('Completed recommendation experiment: '+str(job.directory))
            print(job.directory/'comparisons/register_paths/report.html');return 0
        if args.command == 'experiment':
            from .experiments.counters import plan_counter
            from .experiments.runner import CounterRequest, JobFailure, run_counter
            from .experiments.recipes import RECIPES
            strategies=tuple(RECIPES) if args.sweep else ('default',)
            if args.preview:
                plan=plan_counter(args.example)
                print(f'{plan.name} · {plan.document()["clock_period_ns"]:g} ns clock · OOC · identical constraints in both builds')
                print(plan.diff)
                print(f'{1+len(strategies)} routed builds: original RTL with Default, then identical candidate RTL for each recipe:')
                for strategy in strategies:
                    recipe=RECIPES[strategy]
                    print(recipe.name+': '+ '; '.join(recipe.commands()))
                return 0
            if args.output is None:raise ValueError('A new --output job directory is required to run an experiment.')
            import signal
            from threading import Event
            cancel = Event()
            previous_term = signal.signal(signal.SIGTERM,lambda *_:cancel.set())
            try:
                result = run_counter(CounterRequest(args.example,args.output,args.vivado,args.verilator,args.timeout,strategies),log=LOG.info,cancel=cancel)
            except JobFailure as error:
                LOG.error('TimingLens: %s',error)
                return 130 if error.status=='cancelled' else 1
            finally:
                signal.signal(signal.SIGTERM,previous_term)
            print(f'{result.status.capitalize()} counter experiment: {result.directory}')
            print(result.directory / ('sweep.html' if result.sweep else 'comparisons/register_paths/report.html'))
            return 0 if result.status=='completed' else 1
        if args.command == 'compare':
            from .experiments import compare, export_comparison, load_run
            result = compare(load_run(args.baseline), load_run(args.candidate))
            export_comparison(result, args.output)
            print(f'{result.outcome.upper()} · acceptance {result.acceptance}')
            print(result.headline)
            print(args.output.resolve() / 'report.html')
            return 0
        thresholds = Thresholds.model_validate_json(args.thresholds.read_bytes()) if args.thresholds else None
        if args.command == "import":
            result = load(args.report, thresholds, resolve_local_sources=args.resolve_local_sources)
            if args.output:
                export_result(result, args.output)
            _print_result(result, args.output)
        elif args.command == "inspect":
            result = inspect_files(args.files, thresholds, top=args.top)
            export_result(result, args.output)
            _print_result(result, args.output)
        else:
            options = dict(vivado=args.vivado, build=args.build, max_paths=args.max_paths,
                           paths_per_endpoint=args.paths_per_endpoint, embed_sources=not args.no_source_text)
            if args.command == "analyze":
                requests = [Request("project" if args.project else "checkpoint", args.project or args.checkpoint,
                                    args.output, run=args.run, sources=args.source, **options)]
            else:
                names = list(TOPS) if args.design == "all" else [args.design]
                requests = [request_for(name, args.output / name if len(names) > 1 else args.output, **options)
                            for name in names]
            for request in requests:
                result, _ = collect(request, thresholds, log=LOG.info)
                _print_result(result, request.output)
        return 0
    except (KeyboardInterrupt, Cancelled):
        LOG.error("TimingLens operation cancelled")
        return 130
    except (OSError, ValueError, VivadoError) as error:
        LOG.error("TimingLens: %s", error)
        return 1
