// Gate-level stand-in for the binner_art silicon-art macro (tools/make_art.py).
// The hardened netlist instantiates it but has no definition for it; it is a
// passive Metal4 load with one pin and no logic. RTL simulation gets the same
// empty module from project.v.
module binner_art (
    input wire A
);
endmodule
