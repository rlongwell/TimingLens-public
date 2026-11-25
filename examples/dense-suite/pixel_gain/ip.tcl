create_bd_design gain_tile
create_bd_port -dir I -type clk -freq_hz 125000000 clk
create_bd_port -dir I -from 19 -to 0 sample_in
create_bd_port -dir I -from 15 -to 0 gain
create_bd_port -dir O -from 35 -to 0 value
set mul [create_bd_cell -type ip -vlnv xilinx.com:ip:mult_gen:12.0 gain_product]
set_property -dict [list CONFIG.PortAType Unsigned CONFIG.PortBType Unsigned CONFIG.PortAWidth 20 CONFIG.PortBWidth 16 CONFIG.Multiplier_Construction Use_LUTs CONFIG.PipeStages 1] $mul
connect_bd_net [get_bd_ports clk] [get_bd_pins gain_product/CLK]
connect_bd_net [get_bd_ports sample_in] [get_bd_pins gain_product/A]
connect_bd_net [get_bd_ports gain] [get_bd_pins gain_product/B]
connect_bd_net [get_bd_ports value] [get_bd_pins gain_product/P]
validate_bd_design
save_bd_design
set_property synth_checkpoint_mode None [get_files gain_tile.bd]
