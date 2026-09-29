# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
# femtosecond precision for the behavioural ring/delay models
COCOTB_HDL_TIMEUNIT ?= 1ns
COCOTB_HDL_TIMEPRECISION ?= 1fs
FST ?= -fst # Use more efficient FST format
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../src
PROJECT_SOURCES = project.v binner_ring.v binner_dchain.v binner_rcnt.v binner_sync.v binner_lfsr.v binner_spi.v binner_meas.v binner_fmax.v

# `make`            : RTL, full behavioural regression (default; also CI test.yaml).
# `make GATES=yes`  : gate-level, post-route powered netlist (CI gl_test).
# `make struct`     : structural, hand-instantiated PDK cells with real specify-
#                      block timing (1.0 ns/arc, see docs/SPEC.md and
#                      test/COVERAGE.md item 9); not run by CI, developer-only.
ifeq ($(MAKECMDGOALS),struct)
STRUCT_MODE = yes
endif

ifeq ($(STRUCT_MODE),yes)

# Structural simulation: same PROJECT_SOURCES, but WITHOUT -DBINNER_BEHAV (so
# binner_ring.v / binner_dchain.v / binner_fmax.v use their hand-instantiated
# PDK-cell branches) and WITHOUT -DFUNCTIONAL (so the PDK's specify blocks are
# active: every comb/seq arc in this library is (1.0,1.0) ns). No
# -DUSE_POWER_PINS: project.v never wires VDD/VSS/VNW/VPW to the cells it
# hand-instantiates, matching the cells' non-power-pin port list. No -DGL_TEST:
# project.v (unlike a hardened gate_level_netlist.v) has no VPWR/VGND ports.
SIM_BUILD				= sim_build/struct
# PDK library FIRST: our sources set `default_nettype none, and Verilog
# compiler directives are not file-scoped, so if the library compiled after
# them its internal timing-check gate networks (implicit nets in the
# specify-adjacent notifier logic) fail to elaborate under `default_nettype
# none. This is the same ordering the GATES=yes branch below already uses.
VERILOG_SOURCES += $(PDK_ROOT)/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/verilog/gf180mcu_fd_sc_mcu7t5v0.v
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
PLUSARGS 				+= +STRUCT
# REQUIRED, not optional: Icarus ignores specify-block path delays unless told
# to generate them (`iverilog -g-help` lists `specify|no-specify`; default is
# no-specify). Without this, every comb/seq arc in the PDK's specify blocks is
# a NOP -- the hand-instantiated ring loops become zero-delay combinational
# loops and iverilog spins forever re-evaluating them at the same timestamp
# (confirmed: 97% CPU, simulated time never advances). See test/COVERAGE.md
# item 9 for what -gspecify does and does not fix.
COMPILE_ARGS    += -gspecify
COCOTB_TEST_MODULES = test_struct

else ifneq ($(GATES),yes)

# RTL simulation (ring oscillators and delay chain replaced by behavioural
# models with plusarg-controlled delays, see docs/SPEC.md section 8):
SIM_BUILD				= sim_build/rtl
COMPILE_ARGS    += -DBINNER_BEHAV
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
COCOTB_TEST_MODULES = test,test_reset,test_spi,test_lfsr,test_meas,test_ring,test_pinmode,test_fmax

else

# Gate level simulation:
SIM_BUILD				= sim_build/gl
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DUSE_POWER_PINS
COMPILE_ARGS    += -DSIM
COMPILE_ARGS    += -DUNIT_DELAY=\#1
VERILOG_SOURCES += $(PDK_ROOT)/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/verilog/gf180mcu_fd_sc_mcu7t5v0.v

# this gets copied in by the GDS action workflow
VERILOG_SOURCES += $(PWD)/gate_level_netlist.v
COCOTB_TEST_MODULES = test,test_reset,test_spi,test_lfsr,test_meas,test_ring,test_pinmode,test_fmax

endif

# Allow sharing configuration between design and testbench via `include`:
COMPILE_ARGS 		+= -I$(SRC_DIR)

# Include the testbench sources:
VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb

# include cocotb's make rules to take care of the simulator setup. Defines the
# default goal (`all: sim`), which plain `make` / `make GATES=yes` use.
include $(shell cocotb-config --makefiles)/Makefile.sim

# `make struct` is a phony alias for the same `sim` rule: STRUCT_MODE is
# already selected above from MAKECMDGOALS. Declared after the include so it
# does not become the default goal.
.PHONY: struct
struct: sim
