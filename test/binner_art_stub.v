// Gate-level stand-in for the binner_art silicon-art macro (tools/make_art.py).
// The hardened netlist instantiates it but has no definition for it; it has no
// pins and no logic. RTL simulation gets the same empty module from project.v.
module binner_art ();
endmodule
