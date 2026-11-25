"""Deterministic BD and constraint review from explicit project evidence.

Declarations are not proof of elaboration or functional intent. No XDC/BD edits
are executed. In particular a timing violation cannot establish a false path.
"""
import re

from .fixes import CHECKS, Evidence, FixPlan, Location, dfx_scope
from ..vivado.reports import detail_blocks

CDC = 'https://docs.amd.com/r/2024.2-English/ug903-vivado-using-constraints/About-CDC-Constraints'
MCP = 'https://docs.amd.com/r/2024.2-English/ug903-vivado-using-constraints/Relaxing-Setup-While-Maintaining-Hold'
AXIS = 'https://docs.amd.com/r/1.1-English/pg085-axi4stream-infrastructure/General-Options'
REVIEW = ('check_timing -verbose', 'report_clock_interaction', 'report_cdc -details',
          'report_exceptions -coverage', 'report_exceptions -ignored')
CONSTRAINT_CHECKS = (
    'Review the exact resolved object counts and exceptions coverage/ignored reports; zero matches or a wider scope than intended is a failure.',
    'Review min/max timing and CDC after the change, including reset release and every supported mode. Keep bounded datapath delay and bus-skew requirements where the crossing protocol requires them.',
    'An exception changes what is analyzed; it does not improve circuit speed. Record its functional justification separately from implementation timing gains.',
)


def _location(fact):
    return Location(fact.file, fact.line, fact.line, fact.subject + ' ' + ' '.join(fact.values))


def _clock(name):
    # Use equality filtering, not glob matching. Refuse names requiring escaping.
    if not re.fullmatch(r'[A-Za-z0-9_/.:|\[\]-]+', name):return None
    return '[get_clocks -filter {NAME == "' + name + '"}]'


def _pin(name):
    if not re.fullmatch(r'[A-Za-z0-9_/.:|\[\]-]+', name):return None
    return '[get_pins -hierarchical -filter {NAME == "' + name + '"}]'


def _clock_root(name, clocks):
    visited = set()
    while name in clocks and clocks[name].master:
        if name in visited:return None
        visited.add(name); name = clocks[name].master
    return name


def _bd_matches(result, link):
    """Require both interface signal prefixes in the measured path.

    Recognizes literal instance/interface net names with a boundary on each
    side; never equates similarly named modules or arbitrary ready signals.
    """
    def matches(endpoint, names):
        if '/' not in endpoint:return False
        instance, interface = endpoint.rsplit('/', 1)
        pattern = r'(?:^|/)' + re.escape(instance) + r'(?:/|_)' + re.escape(interface) + r'_(?:tready|tvalid|tdata|tkeep|tlast|tstrb|tuser|tid|tdest)(?:\b|_)'
        return any(re.search(pattern, n, re.I) for n in names)
    for path in result.session.paths:
        if path.analysis != 'setup' or path.slack_ns is None or path.slack_ns >= 0:continue
        names = [*path.pins, *path.nets]
        if matches(link.subject, names) and matches(link.values[0], names):yield path


def _stream_domains(link, facts, clock):
    """Only literal aclk/aresetn connections with a captured clock source.

    No transitive net merging, pin-name guessing or reset-safety inference.
    Ambiguous multiple declarations deliberately fail closed.
    """
    instances = [n.rsplit('/', 1)[0] for n in (link.subject, link.values[0])]
    found = []
    for pin in ('aclk', 'aresetn'):
        wanted = {f'{instance}/{pin}' for instance in instances}
        nets = [f for f in facts if f.kind == 'bd_pin_net' and wanted.intersection((f.subject, *f.values))]
        if len(nets) != 1 or not wanted.issubset({nets[0].subject, *nets[0].values}):
            return (), f'No unique shared {pin} net is declared for both interfaces.'
        found.append(nets[0])
    if not clock or not set(clock.sources).intersection((found[0].subject, *found[0].values)):
        return (), 'The declared aclk connection cannot be linked to a captured clock source.'
    return tuple(found), None


def _boundary_branches(result, path, link):
    """Measured net branches whose two pins straddle the declared instances."""
    instances = tuple(n.rsplit('/', 1)[0] for n in (link.subject, link.values[0]))
    def owner(pin):
        cell = result.session.pins[pin].cell or ''
        matches = [i for i in instances if cell.startswith(i+'/')]
        return matches[0] if len(matches) == 1 else None
    return tuple(a for a in path.arcs if a.kind=='net' and a.delay_ns is not None
                 and owner(a.source) and owner(a.sink) and owner(a.source)!=owner(a.sink))


def suggest_project(result):
    facts = result.project_context.facts
    session = result.session
    clocks = {c.name: c for c in session.clocks}
    plans = []
    constraints = [f for f in facts if f.kind == 'constraint']
    # List existing exceptions for audit, including paths that disappear from
    # the timing report entirely. Never infer that no violations means safe XDC.
    exceptions = [f for f in constraints if f.subject in {'set_false_path', 'set_clock_groups', 'set_multicycle_path', 'set_case_analysis', 'set_disable_timing'}]
    if exceptions:
        plans.append(FixPlan('constraints.audit', 'Audit the supplied timing exceptions', 'constraint_review', 'Supplied XDC/Tcl',
            tuple(f'{f.file}:{f.line}: {f.values[0]}' for f in exceptions),
            'Exceptions can remove paths from timing reports, so an empty failure list cannot validate these constraints.',
            'Check each exception against the functional modes and elaborated objects. Narrow broad wildcards and one-sided false paths only after identifying the intended endpoints. Confirm each multicycle setup relaxation has the correct hold relationship; a simple N−1 hold applies only to the appropriate clock-edge relationship.',
            commands=REVIEW, checks=CONSTRAINT_CHECKS, source_candidates=tuple(map(_location, exceptions)), references=(CDC, MCP),
            next_steps=('Match each exception to the intended operating modes and exact hardware objects.',
                        'Check coverage, ignored exceptions and multicycle hold relationships in Vivado.',
                        'Keep only exceptions with an independent functional justification; recheck CDC and timing.')))
    for fact in (f for f in facts if f.kind == 'async_intent'):
        destination, reason = fact.values
        pair = f'{fact.subject} → {destination}'
        found = fact.subject in clocks and destination in clocks
        common = found and _clock_root(fact.subject, clocks) == _clock_root(destination, clocks)
        a, b = _clock(fact.subject), _clock(destination)
        evidence = [f'Declared intent at {fact.file}:{fact.line}: {pair}; {reason}',
                    'Both clock names exist in the timing capture.' if found else 'One or both declared clocks are absent from the timing capture.']
        templates = ()
        if found and not common and a and b:
            templates = ('# Conditional template only: after every crossing has been checked and no bounded-delay path is overridden.',
                         f'# set_clock_groups -asynchronous -group {a} -group {b}')
        plans.append(FixPlan('constraints.async', 'Review asynchronous clock intent: ' + pair, 'constraint_review', pair, tuple(evidence),
            'The clock model shows a common root, which conflicts with treating these clocks as unrelated; inspect phase/clock generation before any exception.' if common else
            'User-declared asynchronous intent is a reason to review CDC and timing relationships, not proof that all crossing circuits are safe.',
            'Inspect synchronizers/handshakes/FIFOs and both directions of this clock pair. If any crossing needs set_max_delay -datapath_only, do not use a broad clock group: it overrides that bound. Use reviewed path-specific constraints and bus-skew bounds where required. A false path is only appropriate for paths functionally excluded from the timed relationship.',
            commands=(*REVIEW, *templates), prerequisites=('Confirm the supplied intent against actual clock sources and all supported modes.',),
            checks=CONSTRAINT_CHECKS, limitations=('No CDC topology proof or automatic exception approval is performed. The template is deliberately commented out.',),
            source_candidates=(_location(fact),), references=(CDC,),
            next_steps=('Confirm that these clocks are genuinely asynchronous in every supported mode.',
                        'Inspect synchronization and handshake circuitry in both directions.',
                        'Review narrowly scoped exceptions only after preserving any required maximum-delay and bus-skew bounds.')))
    for fact in (f for f in facts if f.kind == 'multicycle_intent'):
        destination, cycles, reason = fact.values
        paths = [p for p in session.paths if p.startpoint == fact.subject and p.endpoint == destination]
        same = paths and all(p.start_clock and p.start_clock == p.end_clock for p in paths)
        # The same clock can still have opposite-edge endpoints. Restrict the
        # template to explicitly captured rising→rising setup paths.
        raw = detail_blocks(session.reports.get('setup-paths.rpt', ''))
        same_edge = same and all(p.analysis == 'setup' and len(re.findall(r'\(rising edge-triggered cell', raw.get(p.id, ''))) == 2 for p in paths)
        a, b = _pin(fact.subject), _pin(destination)
        commands = REVIEW
        if same_edge and a and b:
            commands += (f'# Only after enable/stability assertions prove the {cycles}-cycle contract:',
                         f'# set_multicycle_path {cycles} -setup -from {a} -to {b}',
                         f'# set_multicycle_path {int(cycles)-1} -hold -from {a} -to {b}')
        plans.append(FixPlan('constraints.multicycle', f'Review {cycles}-cycle intent: {fact.subject} → {destination}', 'constraint_review', 'Explicit endpoint pair',
            (f'{fact.file}: {reason}', f'{len(paths)} captured matching paths; same-clock rising-edge model verified: {bool(same_edge)}.'),
            'A computation taking several cycles does not itself justify relaxing every path through it. The destination must ignore intermediate values and the launch/capture schedule must support this particular edge shift.',
            'Prove source stability and destination enable spacing with assertions across reset, stalls, aborts and mode changes. Inspect the launch/capture waveforms and then scope the paired setup/hold exception to exact endpoints. When edge evidence is missing, no numeric XDC template is emitted.',
            commands=commands, checks=CONSTRAINT_CHECKS, source_candidates=(_location(fact),), references=(MCP,),
            next_steps=(f'Prove the {cycles}-cycle source-stability and destination-enable contract.',
                        'Inspect the exact launch/capture edge relationship for this endpoint pair.',
                        'Review paired setup/hold constraints, then verify every operating mode.')))
    links = [f for f in facts if f.kind == 'bd_link']
    for link in links:
        matched = list(_bd_matches(result, link))
        if not matched:continue
        path = min(matched, key=lambda p:p.slack_ns)
        if not result.coverage[path.id].complete:continue
        pair = f'{link.subject} ↔ {link.values[0]}'
        same_clock = path.start_clock and path.start_clock == path.end_clock
        domains, missing = _stream_domains(link, facts, clocks.get(path.start_clock))
        if same_clock and missing:
            plans.append(FixPlan('bd.domain_review', 'Establish clock/reset connections on '+pair,
                'evidence_review', pair,
                (f'{link.file}:{link.line} declares this interface link.',
                 f'{path.id}: {path.slack_ns:.3f} ns setup slack; both interface signal prefixes occur on the measured path.'),
                'The timing path uses one clock, but that does not establish the clock/reset wiring of the proposed AXI boundary.',
                'Supply the literal scalar BD clock/reset nets or inspect the generated BD. Confirm interface direction, aclk, reset polarity and synchronous reset release before choosing a register-slice placement.',
                source_candidates=(_location(link),), unknowns=(missing,),
                limitations=('No register-slice placement or BD rewiring is proposed while clock/reset connectivity is unresolved.',),
                evidence_links=(Evidence(f'{path.id}:bd-boundary','measured','Both interface signal prefixes occur on this failing path.',(path.id,)),
                                Evidence(f'{path.id}:bd-domain','unsupported',missing))))
            continue
        branches = _boundary_branches(result,path,link)
        boundary_delay = sum(a.delay_ns for a in branches)
        if same_clock and (not path.datapath_ns or boundary_delay < .45 or boundary_delay/path.datapath_ns < .2):
            plans.append(FixPlan('bd.boundary_review', 'Locate the slow logic before adding a slice on '+pair,
                'evidence_review', pair,
                (f'{path.id}: {path.slack_ns:.3f} ns setup slack; {boundary_delay:.3f} ns measured on {len(branches)} captured boundary net branches.',),
                'Both interface names on a path do not establish a buffering opportunity. The captured cross-instance branches do not meet the slow-boundary gate.',
                'Inspect the internal logic and existing launch/capture registers. A slice before an already registered transmitter cannot split a long combinational cone inside the receiver. Identify the exact slow branch or protocol combinational chain before choosing a placement.',
                source_candidates=tuple(map(_location,(link,*domains))), rule_version='2',
                applicability=('A slice placement needs a measured cross-instance branch of at least 0.45 ns and 20% of the selected datapath.',),
                unknowns=('Combinational ready/valid ownership and legal extra latency have not been established.',),
                evidence_links=(Evidence(f'{path.id}:boundary-delay','measured',f'{boundary_delay:.3f} ns on the captured cross-instance branches.',(path.id,),tuple(a.resource for a in branches)),)))
            continue
        plans.append(FixPlan('bd.register_slice' if same_clock else 'bd.cdc_review',
            ('Evaluate an AXI4-Stream register slice on ' if same_clock else 'Review clock crossing on ') + pair,
            'block_design_hypothesis', pair,
            (f'{link.file}:{link.line} declares this interface link.', f'{path.id}: {path.slack_ns:.3f} ns setup slack; both interface signal prefixes occur on the measured path.',
             f'Launch clock: {path.start_clock}; capture clock: {path.end_clock}.',
             f'Measured cross-instance net delay: {boundary_delay:.3f} ns on {len(branches)} branches.'),
            'A fully registered AXI4-Stream slice can break the forward and backpressure combinational paths, but only if this declared link survives elaboration as matched.' if same_clock else
            'Different or unknown clocks require clock/CDC evidence before selecting a buffer. A same-clock register slice cannot make an asynchronous transfer safe.',
            'At this interface, evaluate axis_register_slice in fully registered mode using the installed IP customization options. Preserve all enabled sidebands and add the matching clock/reset. Revalidate the BD and compare the specific failing path.' if same_clock else
            'Establish the two clock domains first. For a genuinely asynchronous stream, evaluate axis_clock_converter or an independent-clock axis_data_fifo with its supplied CDC constraints; select depth from traffic bounds, not timing slack.',
            prerequisites=('Cross-probe both named interfaces in the generated design; names from project text are candidates, not elaboration proof.',
                           'Preserve the DFX boundary and locked static interface; a static BD change requires rebuilding/revalidating every compatible RM.' if dfx_scope(result) else 'Confirm latency and reset behavior with the downstream protocol.'),
            checks=(*CHECKS, 'Assert valid/data stability during backpressure, no lost/duplicate beats, aligned TLAST/TKEEP, and correct reset/flush behavior. Measure added cycles and resources.'),
            limitations=('No automatic BD rewiring or unverified numeric IP configuration values are emitted.',
                         'Declared scalar nets do not prove reset polarity, synchronous release, CDC safety or correspondence to this checkpoint.'),
            source_candidates=tuple(map(_location,(link,*domains))), references=(AXIS, CDC),
            unknowns=('Verify interface direction, reset polarity/release and checkpoint correspondence before implementation.',),
            rule_version='2',
            evidence_links=(Evidence(f'{path.id}:stream-path','measured',f'{path.id}: setup slack {path.slack_ns} ns; clock pair {path.start_clock} → {path.end_clock}.',(path.id,)),
                            *(Evidence(f'{path.id}:bd:{i}','syntax',f'{f.subject} connects to {", ".join(f.values)}',location=_location(f)) for i,f in enumerate((link,*domains)))),
            next_steps=(f'Cross-probe the declared connection: {pair}.',
                        'Evaluate a fully registered AXI4-Stream slice, preserving all enabled sidebands.' if same_clock else 'Establish the clock relationship; evaluate a clock converter or independent-clock FIFO only if asynchronous.',
                        'Verify backpressure, latency, reset and packet boundaries, then compare timing and resources.')))
    for fact in (f for f in facts if f.kind == 'buffer_intent'):
        sink, burst, capacity, reason = fact.values
        matching = [l for l in links if {l.subject, l.values[0]} == {fact.subject, sink}]
        if not matching or int(burst) <= int(capacity):continue
        plans.append(FixPlan('bd.fifo', f'Review buffering on {fact.subject} → {sink}', 'block_design_hypothesis', 'Declared stream link',
            (f'{fact.file}: declared maximum unthrottled burst {burst} beats; available capacity {capacity} beats. Reason: {reason}',
             f'Link also appears in {matching[0].file}:{matching[0].line}.'),
            'The declared burst exceeds available buffering. This supports a capacity review independently of setup timing; a deeper FIFO cannot fix a sustained input rate above the output rate.',
            f'Evaluate axis_data_fifo or an equivalent protocol-correct FIFO at this link. The declared burst alone needs at least {burst} beats of total free buffering if the consumer can stall for the whole burst; add in-flight/backpressure latency and margin after validating traffic bounds. Use independent clocks only for a verified asynchronous crossing.',
            prerequisites=('Validate the burst and stall bounds; these values are user assertions, not measured traffic.',),
            checks=('Simulate maximum burst, full/empty transitions, simultaneous read/write, backpressure delay, TLAST boundaries, reset, and overflow/underflow assertions.', *CHECKS),
            limitations=('The burst bound does not prove an adequate depth for arbitrary stall duration or continuous traffic.',),
            source_candidates=(_location(fact),_location(matching[0])), references=(AXIS,),
            next_steps=(f'Confirm the {burst}-beat unthrottled burst and {capacity}-beat buffering assumptions.',
                        'Size a FIFO for the burst, worst consumer stall and in-flight beats; check sustained input/output rates.',
                        'Test full/empty behavior and packet/reset handling, then measure resource and timing costs.')))
    return tuple(plans)
