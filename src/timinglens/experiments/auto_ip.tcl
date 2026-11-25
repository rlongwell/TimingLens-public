# Only authored commands are executed. Native cell identity, arithmetic and interface
# are checked before changing one implementation parameter in the copied project.
lassign $argv operation project bd cell module a b latency construction
open_project $project
open_bd_design $bd
set m [get_bd_cells -quiet $cell]
if {[llength $m] != 1 || [get_property VLNV $m] ne "xilinx.com:ip:mult_gen:12.0"} {error "Multiplier identity changed"}
foreach {key val} [list PortAType Unsigned PortBType Unsigned PortAWidth $a PortBWidth $b PipeStages $latency MultType Parallel_Multiplier Multiplier_Construction $construction] {
    if {[get_property CONFIG.$key $m] ne $val} {error "Unexpected CONFIG.$key on $cell"}
}
set pins [lsort [get_property NAME [get_bd_pins -of_objects $m]]]
if {$pins ne {A B CLK P}} {error "Unsupported multiplier interface: $pins"}
if {$operation eq "apply"} {
    set next [expr {$construction eq "Use_LUTs" ? "Use_Mults" : "Use_LUTs"}]
    set_property CONFIG.Multiplier_Construction $next $m
    if {[get_property CONFIG.PipeStages $m] != $latency} {error "IP latency changed"}
    validate_bd_design
    save_bd_design
} elseif {$operation eq "simulate"} {
    generate_target simulation [get_files $bd]
} else {error "Unknown IP operation"}
close_project
