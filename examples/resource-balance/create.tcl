# vivado -mode batch -source create.tcl -tclargs NEW_DIRECTORY memory|lutram|multiplier|fabric-products|reserved-dsp|small-region|overfull-dsp
lassign $argv out kind
if {$kind ni {memory lutram multiplier fabric-products reserved-dsp small-region overfull-dsp}} {
    error "Choose memory, lutram, multiplier, fabric-products, reserved-dsp, small-region or overfull-dsp"
}
if {[file exists $out]} {error "Choose a fresh project directory"}

# Expand the selected workload in the imported copy. Every project owns its RTL and XDC.
proc configure_source {name replacements} {
    set path [get_property NAME [get_files $name]]
    set f [open $path r]
    set rtl [read $f]
    close $f
    foreach {original replacement} $replacements {
        if {[string first $original $rtl] < 0} {error "Missing $name template fragment: $original"}
    }
    set f [open $path w]
    puts -nonewline $f [string map $replacements $rtl]
    close $f
}
set src [file dirname [file normalize [info script]]]
create_project banks $out -part xc7z020clg400-1
import_files -norecurse [file join $src ../dense-suite stream.v]
import_files -fileset constrs_1 -norecurse [file join $src ../dense-zybo timing.xdc]
if {$kind eq "fabric-products"} {
    import_files -norecurse [file join $src ../dense-suite pixel_gain pixel_gain.v]
    # Half-depth histories keep the independent block-RAM pool below this test's 65% target.
    configure_source stream.v [list {[0:1023]} {[0:511]} {[9:0] address} {[8:0] address}]
    source [file join $src ../dense-suite pixel_gain ip.tcl]
    set_property top pixel_gain [get_filesets sources_1]
    close_project
    return
}
import_files -norecurse [file join $src banks.v]
set lane {queue_store store(.clk(clk),.we(state[31]),.addr(state[13:8]),.din(state[7:0]),.dout(values[n]));}

if {$kind in {memory lutram}} {
    import_files -norecurse [file join $src queue_store.v]
    if {$kind eq "lutram"} {
        configure_source queue_store.v [list {"block"} {"distributed"} {[5:0]} {[8:0]} \
                                            {[0:63]} {[0:511]} {[7:0]} {[31:0]}]
        set wide_lane {wire [31:0] sample;
        assign values[n] = sample[31:24] ^ sample[23:16] ^ sample[15:8] ^ sample[7:0];
        queue_store store(.clk(clk),.we(state[31]),.addr(state[24:16]),.din(state),.dout(sample));}
        configure_source banks.v [list {LANES = 300} {LANES = 64} $lane $wide_lane]
    }
} else {
    set lanes [expr {$kind eq "overfull-dsp" ? 232 : 200}]
    if {$kind eq "small-region"} {set lanes 8}
    set multiplier_lane {wire [15:0] product;
        gain_tile store(.clk(clk),.sample_in(state[7:0]),.gain(state[23:16]),.value(product));
        assign values[n] = product[15:8] ^ product[7:0];}
    configure_source banks.v [list {LANES = 300} "LANES = $lanes" $lane $multiplier_lane]

    create_bd_design gain_tile
    create_bd_port -dir I -type clk -freq_hz 125000000 clk
    create_bd_port -dir I -from 7 -to 0 sample_in
    create_bd_port -dir I -from 7 -to 0 gain
    create_bd_port -dir O -from 15 -to 0 value
    set m [create_bd_cell -type ip -vlnv xilinx.com:ip:mult_gen:12.0 gain_product]
    set_property -dict [list CONFIG.PortAType Unsigned CONFIG.PortBType Unsigned \
                            CONFIG.PortAWidth 8 CONFIG.PortBWidth 8 \
                            CONFIG.Multiplier_Construction Use_Mults CONFIG.PipeStages 3] $m
    foreach {port pin} {clk CLK sample_in A gain B value P} {
        connect_bd_net [get_bd_ports $port] [get_bd_pins gain_product/$pin]
    }
    validate_bd_design
    save_bd_design
    set_property synth_checkpoint_mode None [get_files gain_tile.bd]
}
if {$kind eq "reserved-dsp"} {
    set f [open [get_property NAME [get_files timing.xdc]] a]
    set reserved {}
    foreach column {0 1} {
        for {set y 0} {$y < 20} {incr y} {lappend reserved DSP48_X${column}Y$y}
    }
    puts $f "set_property PROHIBIT true \[get_sites {$reserved}\]"
    close $f
}
if {$kind eq "small-region"} {
    # Four DSPs are available to this subsystem. All other DSPs are reserved.
    set f [open [get_property NAME [get_files timing.xdc]] a]
    puts $f {set_property PROHIBIT true [get_sites -filter {SITE_TYPE =~ DSP48* && NAME != DSP48_X0Y0 && NAME != DSP48_X0Y1 && NAME != DSP48_X0Y2 && NAME != DSP48_X0Y3}]}
    close $f
}
set_property top banks [get_filesets sources_1]
close_project
