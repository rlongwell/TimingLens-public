module tb;
bit clk=0, rst=1, accept=0, load=0;
bit [3:0] amount=0;
bit [63:0] initial_value=0;
wire [63:0] a,b;
bit [63:0] rng=64'h923456789abcdef1;
counter_before before_dut(clk,rst,accept,load,amount,initial_value,a);
counter_after after_dut(clk,rst,accept,load,amount,initial_value,b);
bit [63:0] expected=0;
task tick;
  if (rst) expected=0;
  else if (load) expected=initial_value;
  else if (accept && (expected > 64'(amount))) expected=expected-64'(amount);
  #1 clk=1; #1;
  if (a !== b || a !== expected) $fatal(1,"sequential mismatch a=%h b=%h",a,b);
  clk=0;
endtask
initial begin
  tick(); rst=0;
  for (int n=0;n<16;n++) begin
    for (int k=0;k<6;k++) begin
      load=1; accept=0; amount=4'(n);
      case(k)
        0: initial_value=0;
        1: initial_value=64'(n);
        2: initial_value=64'(n+1);
        3: initial_value=64'(n-1);
        4: initial_value='1;
        5: initial_value=64'(16);
      endcase
      tick(); load=0; accept=1; tick(); accept=0; tick();
    end
  end
  for(int i=0;i<10000;i++) begin
    rng=rng^(rng<<13); rng=rng^(rng>>7); rng=rng^(rng<<17);
    initial_value=64'(rng); amount=rng[3:0];
    rst=(i%97==0); load=rng[5]; accept=rng[7]; tick();
  end
  $display("PASS: 10289 sequential comparisons including reset, stalls, load and boundaries");
  $finish;
end
endmodule
