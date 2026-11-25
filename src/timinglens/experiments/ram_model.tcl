lassign $argv source_file part top style
read_verilog -sv $source_file
synth_design -mode out_of_context -part $part -top $top
set brams [get_cells -quiet -hier -filter {REF_NAME =~ RAMB* && IS_PRIMITIVE}]
set lutrams [get_cells -quiet -hier -filter {REF_NAME =~ RAM* && REF_NAME !~ RAMB* && IS_PRIMITIVE}]
if {$style eq "block" && (![llength $brams] || [llength $lutrams])} {error "Block RAM mapping was not inferred"}
if {$style eq "distributed" && (![llength $lutrams] || [llength $brams])} {error "Distributed RAM mapping was not inferred"}
write_verilog -mode funcsim -rename_top timinglens_memory model.v
