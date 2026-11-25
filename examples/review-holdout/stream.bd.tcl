# Review context only. TimingLens must never execute this text.
connect_bd_intf_net [get_bd_intf_pins tx/M_AXIS] [get_bd_intf_pins rx/S_AXIS]
connect_bd_net [get_bd_ports clk] [get_bd_pins tx/aclk] [get_bd_pins rx/aclk]
connect_bd_net [get_bd_ports resetn] [get_bd_pins tx/aresetn] [get_bd_pins rx/aresetn]
