# Run in an empty output directory. Sources stay beside this script.
set root [file dirname [file normalize [info script]]]
if {[file exists project] || [file exists routed.dcp]} {error "Choose a fresh build directory"}
set_param general.maxThreads 3
create_project telemetry project -part xc7z020clg400-1
add_files [file join $root telemetry.v]
update_compile_order -fileset sources_1
create_bd_design telemetry_fabric
set clk [create_bd_port -dir I -type clk -freq_hz 250000000 clk]
create_bd_port -dir O status
proc rtl {name ref} {create_bd_cell -type module -reference $ref $name}
proc ip {name id} {create_bd_cell -type ip -vlnv xilinx.com:ip:$id $name}
proc wire {a b} {connect_bd_net [get_bd_pins $a] [get_bd_pins $b]}
proc stream {a b} {connect_bd_intf_net [get_bd_intf_pins $a] [get_bd_intf_pins $b]}
rtl boot power_on
rtl source_samples sample_source
ip input_fifo axis_data_fifo:2.0
set_property -dict [list CONFIG.TDATA_NUM_BYTES 32 CONFIG.FIFO_DEPTH 1024 CONFIG.FIFO_MEMORY_TYPE block] [get_bd_cells input_fifo]
ip stream_slice axis_register_slice:1.1
set_property CONFIG.TDATA_NUM_BYTES 32 [get_bd_cells stream_slice]
rtl unpack frame_unpack
ip metrics_concat xlconcat:2.1
set_property CONFIG.NUM_PORTS 8 [get_bd_cells metrics_concat]
rtl selector priority_pick
rtl energy energy_mix
rtl events event_log
foreach pin {boot/clk source_samples/clk input_fifo/s_axis_aclk stream_slice/aclk unpack/clk events/clk} {
    connect_bd_net $clk [get_bd_pins $pin]
}
foreach pin {source_samples/resetn input_fifo/s_axis_aresetn stream_slice/aresetn unpack/resetn} {
    wire boot/resetn $pin
}
stream source_samples/M_AXIS input_fifo/S_AXIS
stream input_fifo/M_AXIS stream_slice/S_AXIS
stream stream_slice/M_AXIS unpack/S_AXIS
for {set i 0} {$i < 8} {incr i} {
    ip word_$i xlslice:1.0
    set_property -dict [list CONFIG.DIN_WIDTH 256 CONFIG.DIN_FROM [expr {32*$i+31}] CONFIG.DIN_TO [expr {32*$i}] CONFIG.DOUT_WIDTH 32] [get_bd_cells word_$i]
    rtl lane_$i correlation_lane
    wire unpack/frame word_$i/Din
    wire word_$i/Dout lane_$i/sample_word
    connect_bd_net $clk [get_bd_pins lane_$i/clk]
    wire lane_$i/metric metrics_concat/In$i
}
wire metrics_concat/dout selector/metrics
wire events/threshold selector/threshold
wire lane_0/metric energy/a
wire lane_1/metric energy/b
wire lane_2/metric energy/c
wire selector/winner events/winner
wire energy/energy events/energy
connect_bd_net [get_bd_pins events/status] [get_bd_ports status]
validate_bd_design
save_bd_design
set bd [get_files telemetry_fabric.bd]
file copy $bd telemetry_fabric.bd
write_bd_tcl -force recreate_bd.tcl
set_property synth_checkpoint_mode None $bd
generate_target all $bd
add_files [make_wrapper -files $bd -top]
set_property top telemetry_fabric_wrapper [current_fileset]
add_files -fileset constrs_1 [file join $root timing.xdc]
update_compile_order -fileset sources_1
synth_design -top telemetry_fabric_wrapper -part xc7z020clg400-1 -flatten_hierarchy none
opt_design
place_design -directive Default
route_design -directive Default
write_checkpoint routed.dcp
report_route_status -file route_status.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
check_timing -verbose -file check_timing.rpt
report_utilization -file utilization.rpt
report_utilization -hierarchical -file hierarchy.rpt
report_drc -file drc.rpt
report_timing -delay_type max -max_paths 12 -nworst 1 -input_pins -file worst_paths.rpt
