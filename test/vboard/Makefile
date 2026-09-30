# BINNER virtual demo board -- runs bringup/binner_bringup.py, unmodified,
# against RTL simulation. See test/vboard/../../bringup/README.md.
#
# Usage (single chip / smoke test):
#   source ~/tools/binner_env.sh
#   BINNER_CHIP_ID=smoke01 make
#
# The population runner (test/vboard/run_population.py) invokes this same
# Makefile once per chip, with SIM_BUILD pointed at a per-chip build
# directory (so parallel chips don't clobber each other's Icarus build) and
# PLUSARGS carrying that chip's docs/VARIATION_MODEL.md draw.

SIM ?= icarus
COCOTB_HDL_TIMEUNIT ?= 1ns
COCOTB_HDL_TIMEPRECISION ?= 1fs
FST ?= -fst
TOPLEVEL_LANG ?= verilog
SRC_DIR = $(PWD)/../../src

PROJECT_SOURCES = project.v binner_ring.v binner_dchain.v binner_rcnt.v binner_sync.v binner_lfsr.v binner_spi.v binner_meas.v binner_fmax.v

SIM_BUILD ?= sim_build/rtl
COMPILE_ARGS += -DBINNER_BEHAV
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
COMPILE_ARGS += -I$(SRC_DIR)

VERILOG_SOURCES += $(PWD)/tb.v
TOPLEVEL = tb

COCOTB_TEST_MODULES = sim_tb

# Chip-specific variation draw, e.g. "+RING0_HP_FS=... +DSTG1_FS=... ...".
# Forwarded to the simulator ($value$plusargs in the behavioural RTL).
PLUSARGS ?=

include $(shell cocotb-config --makefiles)/Makefile.sim
