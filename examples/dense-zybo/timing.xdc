# Zybo Z7-20 PL oscillator and the JD header. The receiver samples the rising
# edge of the forwarded strobe. Both implementations use the same external budget.
set_property -dict {PACKAGE_PIN K17 IOSTANDARD LVCMOS33} [get_ports clk]
create_clock -name sys125 -period 8.000 [get_ports clk]
set_property -dict {PACKAGE_PIN T14 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 8} [get_ports strobe]
set_property -dict {PACKAGE_PIN T15 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 8} [get_ports {digest[0]}]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 8} [get_ports {digest[1]}]
set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 8} [get_ports {digest[2]}]
set_property -dict {PACKAGE_PIN U14 IOSTANDARD LVCMOS33 SLEW FAST DRIVE 8} [get_ports {digest[3]}]
set_property IOB TRUE [get_ports {digest[*]}]
create_generated_clock -name receive_strobe -source [get_ports clk] -divide_by 1 -invert [get_ports strobe]
set_output_delay -clock receive_strobe -max 0.750 [get_ports {digest[*]}]
set_output_delay -clock receive_strobe -min -0.350 [get_ports {digest[*]}]
