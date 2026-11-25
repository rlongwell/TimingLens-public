# Create portable native Vivado projects from each independent compute kernel.
set src [file normalize [lindex $argv 0]]
set name [lindex $argv 1]
set dest [file normalize [lindex $argv 2]]
create_project $name $dest -part xc7z020clg400-1
import_files -norecurse [concat [list [file join $src stream.v]] [glob [file join $src $name *.v]]]
import_files -fileset constrs_1 -norecurse [file join $src .. dense-zybo timing.xdc]
if {[file exists [file join $src $name ip.tcl]]} { source [file join $src $name ip.tcl] }
set_property top $name [get_filesets sources_1]
update_compile_order -fileset sources_1
close_project
