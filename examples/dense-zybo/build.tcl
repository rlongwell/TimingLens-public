# Invoke from an empty build directory with a frozen source directory argument.
set src [file normalize [lindex $argv 0]]
if {[file exists project] || [file exists routed.dcp]} {error "Select a fresh build directory"}
set_param general.maxThreads 4
create_project dense project -part xc7z020clg400-1
add_files [list [file join $src fabric.v] [file join $src calibration.v]]
update_compile_order -fileset sources_1
create_bd_design monitor
set clk [create_bd_port -dir I -type clk -freq_hz 125000000 clk]
create_bd_port -dir O -from 3 -to 0 digest
create_bd_port -dir O strobe
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 combine
set_property CONFIG.NUM_PORTS 13 [get_bd_cells combine]
for {set i 0} {$i < 13} {incr i} {
    set bank [create_bd_cell -type module -reference monitor_bank bank_$i]
    set_property CONFIG.BANK_ID $i $bank
    connect_bd_net $clk [get_bd_pins bank_$i/clk]
    connect_bd_net [get_bd_pins bank_$i/digest] [get_bd_pins combine/In$i]
}
create_bd_cell -type module -reference digest_output readout
connect_bd_net $clk [get_bd_pins readout/clk]
connect_bd_net [get_bd_pins combine/dout] [get_bd_pins readout/banks]
connect_bd_net [get_bd_pins readout/digest] [get_bd_ports digest]
connect_bd_net [get_bd_pins readout/strobe] [get_bd_ports strobe]
validate_bd_design
save_bd_design
set bd [get_files monitor.bd]
file copy $bd monitor.bd
set_property synth_checkpoint_mode None $bd
generate_target all $bd
add_files [make_wrapper -files $bd -top]
set_property top monitor_wrapper [current_fileset]
add_files -fileset constrs_1 [file join $src timing.xdc]
update_compile_order -fileset sources_1
synth_design -top monitor_wrapper -part xc7z020clg400-1 -flatten_hierarchy rebuilt
report_utilization -file synth_utilization.rpt
write_checkpoint synthesized.dcp
opt_design
place_design -directive Default
phys_opt_design -directive Default
route_design -directive Default
write_checkpoint routed.dcp
report_route_status -file route_status.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
check_timing -verbose -file check_timing.rpt
report_utilization -file utilization.rpt
report_utilization -hierarchical -file hierarchy.rpt
report_drc -file drc.rpt
report_timing -delay_type max -max_paths 12 -nworst 1 -input_pins -file setup_paths.rpt
report_timing -delay_type min -max_paths 3 -nworst 1 -input_pins -file hold_paths.rpt
