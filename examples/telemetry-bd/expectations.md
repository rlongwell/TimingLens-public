# Test design and predeclared checks

Evaluate the existing diagnosis rules on one integrated IP Integrator top. The target is a 4 ns clock on the xc7z020clg400-1. Keep Default placement and routing and collect one worst path per endpoint. The input traffic is generated on chip. The only board-facing signals in the design are clock and registered status.

* **Energy capture.** A lane's registered metric feeds a multiply, offset and dependent multiply, then a register in a separate event block. Look for negative setup slack and DSP or cascaded-arithmetic evidence on paths to the energy register.
* **Priority capture.** Sixteen dynamic half-word comparisons select one of eight metrics for a register in the event block. Check whether TimingLens can identify the priority logic specifically, in addition to any general logic depth or routing diagnosis. RTL semantics alone do not prove that synthesis preserved a serial mux chain.
* **Local control.** Compare the short internal phase-register feedback path with the cross-block paths. Its contribution is measured using a targeted native query even when the global sample does not include it.
* **AXI stream boundaries.** Inspect the three real AXI stream connections separately. A late event path does not implicate the FIFO or its interfaces.
* **Scope.** The native design timing summary is authoritative for the whole implementation. Compare it with the exported session, and pair the targeted native paths with the tool's captured endpoints and corresponding rule evidence. Record missed or unconfirmed diagnoses.
