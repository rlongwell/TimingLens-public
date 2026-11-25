# Enumerate the worst setup path to every failing endpoint independently of TimingLens.
# This can run after probe.tcl or in a new Vivado process from the build directory.
if {![llength [get_designs -quiet]]} {open_checkpoint routed.dcp}
set table [open native_failing.tsv w]
puts $table "startpoint\tendpoint\tslack_ns"
foreach path [get_timing_paths -delay_type max -nworst 1 -max_paths 10000 -slack_lesser_than 0 -sort_by slack] {
    puts $table [join [list [get_property STARTPOINT_PIN $path] [get_property ENDPOINT_PIN $path] [get_property SLACK $path]] "\t"]
}
close $table
