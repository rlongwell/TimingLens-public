# Independent Vivado STA. Run from the implementation directory, after routing.
open_checkpoint routed.dcp
set out [open native_paths.tsv w]
puts $out [join {family startpoint endpoint slack_ns levels logic_ns route_ns failing_endpoints path_cells} "\t"]
# The endpoint filters are declared in advance. Look up the actual primitives after route.
foreach {family pattern pin} {
    energy        */events/*energy_q_reg*        D
    priority      */events/*selected_q_reg*      D
    local_control */events/*phase_reg*           D
    stream_frame  */unpack/*frame_reg*           R
    fifo_ready    */source_samples/*sample_reg*  CE
} {
    set regs [get_cells -hier -filter "IS_SEQUENTIAL && NAME =~ $pattern"]
    set sinks [get_pins -of_objects $regs -filter "REF_PIN_NAME == $pin"]
    if {![llength $sinks]} {error "No $family endpoint pins matched $pattern"}
    set worst [get_timing_paths -delay_type max -to $sinks -max_paths 1 -nworst 1]
    set failing [get_timing_paths -quiet -delay_type max -to $sinks -slack_lesser_than 0 -max_paths 1024 -nworst 1]
    set row [list $family]
    foreach key {STARTPOINT_PIN ENDPOINT_PIN SLACK LOGIC_LEVELS DATAPATH_LOGIC_DELAY DATAPATH_NET_DELAY} {
        lappend row [get_property $key $worst]
    }
    lappend row [llength $failing]
    set cells {}
    foreach cell [get_cells -of_objects $worst] {
        lappend cells "[get_property NAME $cell]:[get_property REF_NAME $cell]"
    }
    lappend row [join $cells ,]
    puts $out [join $row "\t"]
    report_timing -of_objects $worst -file native_$family.rpt
}
close $out
