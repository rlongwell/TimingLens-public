# Pass a copy of the generated project and the independently generated scoreboard.
open_project [lindex $argv 0]
set sim [get_filesets sim_1]
add_files -fileset sim_1 [file normalize [lindex $argv 1]]
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
if {![string match "*PASS: 2560 consecutive frames*" $transcript]} {error "Missing scoreboard pass marker in $log"}
close_project
