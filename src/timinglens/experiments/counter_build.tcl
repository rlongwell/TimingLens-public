# Fixed OOC recipe for the bundled binary counters. No project hooks or hardware I/O.
proc counter_main {} {
    set_param general.maxThreads 2
    set source_file [file normalize design.sv]
    read_verilog -sv design.sv
    read_xdc timing.xdc
    synth_design -top counter -part xc7z020clg400-1 -mode out_of_context
    opt_design
    place_design -directive Default
    route_design -directive Default
    write_checkpoint routed.dcp
    report_utilization -file utilization.rpt
    report_drc -file drc.rpt
    set stats [open primitives.tsv w]
    puts $stats "LUT*\t[llength [get_cells -hier -filter {REF_NAME =~ LUT* && IS_PRIMITIVE == 1}]]"
    close $stats
    set stats [open registers.tsv w]
    foreach {check delay} {setup max hold min} {
        set paths [get_timing_paths -delay_type $delay -from [all_registers] -to [all_registers] -max_paths 10000 -nworst 1]
        if {[llength $paths] == 0 || [llength $paths] >= 10000} {error "Incomplete register timing population"}
        set worst 1e30
        set tns 0
        set failed 0
        set endpoints [dict create]
        foreach p $paths {
            set slack [get_property SLACK $p]
            set endpoint [get_property ENDPOINT_PIN $p]
            if {$slack < $worst} {set worst $slack}
            if {![dict exists $endpoints $endpoint] || $slack < [dict get $endpoints $endpoint]} {
                dict set endpoints $endpoint $slack
            }
        }
        dict for {endpoint slack} $endpoints {
            if {$slack < 0} {incr failed; set tns [expr {$tns + $slack}]}
        }
        puts $stats [format "%s\t%.3f\t%.3f\t%d\t%d" $check $worst $tns $failed [dict size $endpoints]]
    }
    close $stats
    source extract.tcl
    tl::collect demo $source_file counter counter {} 400 1 0
    file mkdir internal
    cd internal
    tl::collect demo $source_file counter counter {} 400 1 0 register_paths
    cd ..
    set done [open completed.txt w]
    puts $done "TIMINGLENS_COUNTER_BUILD_V1"
    close $done
}
if {[catch {counter_main} reason options]} {
    puts stderr "TimingLens counter runner: $reason"
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
