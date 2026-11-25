# Both sides of an automatic experiment execute this same controlled recipe.
set project [file normalize [lindex $argv 0]]
set limit [lindex $argv 1]
set_param general.maxThreads 2
open_project $project
if {[get_property -quiet PR_FLOW [current_project]] in {1 true}} {
    error "Automatic implementation requires a static project"
}
set top [get_property TOP [current_fileset]]
set part [get_property PART [current_project]]
set bds [get_files -quiet -filter {FILE_TYPE == "Block Designs"}]
foreach bd $bds {
    open_bd_design $bd
    validate_bd_design
    set_property synth_checkpoint_mode None $bd
    generate_target all $bd
}
synth_design -top $top -part $part -flatten_hierarchy rebuilt
set resources [file exists owner-modules.txt]
set here [file dirname [file normalize [info script]]]
source [file join $here .. vivado extract.tcl]
if {$resources} {
    source [file join $here resource_owners.tcl]
    write_checkpoint synthesized.dcp
}
if {[catch {
    opt_design
    place_design -directive Default
    phys_opt_design -directive Default
    route_design -directive Default
} detail options]} {
    if {!$resources || ![file exists allow-unplaced-baseline]} {return -options $options $detail}
    puts "TimingLens: implementation stopped: $detail"
    close_design
    open_checkpoint synthesized.dcp
    report_utilization -file utilization.rpt
    resource_owners owner-modules.txt
    report_drc -file drc.rpt
    tl::collect checkpoint [file normalize synthesized.dcp] $top $top {} $limit 1 0
    puts TIMINGLENS_UNPLACED_BASELINE
    return
}
write_checkpoint routed.dcp
report_utilization -file utilization.rpt
if {$resources} {resource_owners owner-modules.txt}
report_drc -file drc.rpt
tl::collect checkpoint [file normalize routed.dcp] $top $top {} $limit 1 0
puts TIMINGLENS_AUTO_ROUTE_COMPLETE
