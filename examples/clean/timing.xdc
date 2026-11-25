create_clock -name clk -period 20.000 [get_ports clk]
set data_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set_input_delay -clock clk -max 0.300 $data_inputs
set_input_delay -clock clk -min 0.100 $data_inputs
set_output_delay -clock clk -max 0.300 [all_outputs]
set_output_delay -clock clk -min -0.100 [all_outputs]
