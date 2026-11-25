# Export actual programmable-logic slice locations from a routed checkpoint.
open_checkpoint [lindex $argv 0]
set all_slices [get_sites -filter {SITE_TYPE == SLICEL || SITE_TYPE == SLICEM}]
set used [dict create]
set luts [dict create]
set cells [get_cells -hierarchical -filter {IS_PRIMITIVE}]
foreach loc [get_property LOC $cells] bel [get_property BEL $cells] {
    if {[string match SLICE_* $loc]} {
        dict set used $loc 1
        if {[regexp {([ABCD])[56]LUT$} $bel -> letter]} {dict set luts $loc $letter 1}
    }
}
set output [open [lindex $argv 1] w]
puts $output "site\tused\tlut_sites"
foreach site [get_property NAME $all_slices] {
    set n 0
    if {[dict exists $luts $site]} {set n [dict size [dict get $luts $site]]}
    puts $output "$site\t[dict exists $used $site]\t$n"
}
close $output
set regs [all_registers]
set out [open [lindex $argv 2] w]
puts $out "bank\tstartpoint\tendpoint\tsetup_slack_ns"
for {set i 0} {$i < 13} {incr i} {
    set bank [filter $regs "NAME =~ */bank_$i/*"]
    if {![llength $bank]} {error "Missing bank $i in the implemented hierarchy"}
    set p [get_timing_paths -delay_type max -to $bank -max_paths 1 -nworst 1]
    puts $out [join [list $i [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p] [get_property SLACK $p]] "\t"]
}
close $out
