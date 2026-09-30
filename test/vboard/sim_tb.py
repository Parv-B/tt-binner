# SPDX-FileCopyrightText: (c) 2026 Parv Bhadra
# SPDX-License-Identifier: Apache-2.0
"""cocotb entry point for the BINNER virtual demo board.

Runs bringup/binner_bringup.py -- completely unmodified -- against the RTL
simulation, using the fake `ttboard`/`machine`/`rp2` modules in
test/vboard/fakemp/ and cocotb 2.1's private bridge/resume mechanism
(cocotb._bridge; verified against the actual installed API, see the module
docstring in test/vboard/fakemp/ttboard/_sim_bridge.py -- `cocotb.bridge`/
`cocotb.resume` as named in the task brief do not exist in this cocotb 2.1.0
build, the real names are `cocotb._bridge.bridge`/`cocotb._bridge.resume`).

Per-chip configuration comes from environment variables, set by
test/vboard/run_population.py (or defaulted here for a single-chip smoke
test run directly via `make`):
  BINNER_CHIP_ID    chip_id passed to binner_bringup.main()
  BINNER_OUT_DIR    directory the CSV is written into
  BINNER_TRUTH_JSON path to a truth_<chip>.json (see test/vboard/variation.py);
                     only T_c is read back here (for core_temp()) -- the
                     +RING*/+DSTG*/+DCHAIN_OVH_FS plusargs that actually
                     shape the RTL's behavioural delays are consumed
                     directly by the Verilog $value$plusargs calls in
                     src/binner_ring.v / src/binner_dchain.v, not by this
                     Python file.
  BINNER_REDUCED    "1" for the reduced-effort knob (see binner_bringup.main)
"""

import json
import os
import sys

import cocotb
from cocotb._bridge import bridge
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

_HERE = os.path.dirname(os.path.abspath(__file__))
_FAKEMP = os.path.join(_HERE, "fakemp")
_BRINGUP_DIR = os.path.join(_HERE, "..", "..", "bringup")

if _FAKEMP not in sys.path:
    sys.path.insert(0, _FAKEMP)
if _BRINGUP_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_BRINGUP_DIR))


async def _power_up(dut):
    """Everything the TT mux / RP2350 board itself is responsible for
    before firmware ever touches the tile: default clock running, ena high,
    pins idle, then an initial reset pulse -- mirrors test/test.py's
    reset() and the "always reset after selecting the tile" firmware fact.
    """
    clock = Clock(dut.clk, 100, unit="ns")  # 10 MHz boot default
    cocotb.start_soon(clock.start())
    dut.ena.value = 1
    dut.ui_in.value = 0x01  # CS_N idle high, PINMODE=0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)


@bridge
def _run_bringup(chip_id, out_dir, config_path, reduced):
    """Runs on a bridge OS thread. binner_bringup.main() is a plain
    blocking function -- it never knows it's talking to a simulator.
    """
    import binner_bringup

    def log(msg):
        print("[binner_bringup %s] %s" % (chip_id, msg))

    return binner_bringup.main(
        chip_id=chip_id,
        config_path=config_path,
        out_dir=out_dir,
        reduced=reduced,
        log_fn=log,
    )


@cocotb.test()
async def test_vboard_bringup(dut):
    chip_id = os.environ.get("BINNER_CHIP_ID", "sim_smoke")
    out_dir = os.environ.get("BINNER_OUT_DIR", ".")
    truth_path = os.environ.get("BINNER_TRUTH_JSON", "")
    reduced = os.environ.get("BINNER_REDUCED", "0") == "1"
    config_path = os.environ.get(
        "BINNER_CONFIG", os.path.join(os.path.abspath(_BRINGUP_DIR), "config.ini")
    )

    variation = {}
    if truth_path and os.path.isfile(truth_path):
        with open(truth_path) as f:
            truth = json.load(f)
        variation = {"T_c": truth.get("T_c", 27.0)}
    else:
        variation = {"T_c": 27.0}

    from ttboard import _sim_bridge
    _sim_bridge.init(dut, variation)

    import _install
    _install.install()

    await _power_up(dut)

    csv_path = await _run_bringup(chip_id, out_dir, config_path, reduced)
    dut._log.info("bring-up wrote %s", csv_path)
    assert os.path.isfile(csv_path), "binner_bringup did not produce a CSV"
