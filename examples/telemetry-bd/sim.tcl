# Use a separate copy of the generated project when running concurrently with implementation.
open_project [lindex $argv 0]
set sim [get_filesets sim_1]
set tb [file join [file dirname [file normalize [info script]]] tb.sv]
if {![llength [get_files -quiet -of_objects $sim $tb]]} {add_files -fileset sim_1 $tb}
set_property top tb $sim
set_property xsim.simulate.runtime 0ns $sim
launch_simulation -simset sim_1 -mode behavioral
run all
close_sim
set project [current_project]
set log [file join [get_property DIRECTORY $project] [get_property NAME $project].sim sim_1 behav xsim simulate.log]
set f [open $log]
set transcript [read $f]
close $f
if {![string match "*PASS telemetry BD:*" $transcript]} {error "Scoreboard did not reach its pass marker. See $log"}
close_project
