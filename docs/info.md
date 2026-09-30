## How it works

BINNER is a self-contained process-monitor and speed-binning tile for the TTGF26d
(GF180MCU) shuttle. It has no external inputs to process and no application-level
function; its only job is to let you measure how a specific fabricated die actually
behaves, from a fully digital SPI/pin interface. Four blocks, all built from the same
GF180MCU 7-track standard-cell library as the rest of the tile:

- **Ring bank.** 16 identical 25-stage inverter rings (used as RO-PUFs and for
  within-die/die-to-die variation statistics), plus one 25-stage NAND2 ring, one
  25-stage NOR2 ring, and one 13-stage fan-out-4-loaded INV ring. Comparing the
  NAND/NOR ring frequency against the INV rings gives an NMOS-vs-PMOS drive-strength
  skew signature. At most two rings run at a time (selected independently on channel
  A and channel B), and every ring's enable fan-in is hand-instantiated and
  `dont_touch`-protected so the hardening flow cannot resize or buffer-insert inside
  the structures being measured (verified post-route by `tools/netlist_audit.py`).
- **Delay chain / at-speed Fmax checker.** A 14-stage `DLYD_1` chain tapped at 8
  points (after 3, 4, 5, 6, 8, 10, 12, 14 stages). In Fmax mode, a launch flop loads
  pseudo-random LFSR data every cycle while armed, and 8 capture flops (one per tap)
  are checked simultaneously against a reference flop while the clock is swept in
  frequency -- a tap "fails" once its chain delay exceeds the clock period, giving a
  direct silicon Fmax measurement without any off-chip timing gear. The same chain,
  reconfigured through its tap-select mux as a feedback ring, becomes measurement
  source 19 and gives an independent, ring-oscillator-style cross-check of the same
  per-stage delay.
- **Paired counters and measurement controller.** Two independent ripple counters,
  each fed from an internal source through a synchroniser, count rising edges for a
  clock-domain gate of `2^GEXP` cycles (GEXP programmable). A small FSM starts,
  stops and acknowledges both channels symmetrically, so a paired measurement
  (e.g. an INV ring vs. the NAND ring) captures both counts from the same gate
  window. `SEEN`/`OVF`/`TIMEOUT` flags catch a dead source, a counter wrap, or a
  stuck handshake instead of returning silently-wrong data.
- **LFSR self-test and SPI register interface.** A 16-bit maximal-length (period
  65536) Fibonacci LFSR with de Bruijn zero-insertion doubles as a digital known-answer
  self-test and as the Fmax checker's pseudo-random launch data. All configuration and
  readout goes through a 19-register SPI slave (mode 0, MSB-first, write/read with
  address auto-increment); a pin-strap mode also lets the ring bank and counters run
  with no SPI activity at all, driven directly from `ui_in`.

See `docs/DATASHEET.md` in the source repository for the full architecture writeup
(block diagram, every design decision with alternatives considered, the complete
verification story, and falsifiable silicon predictions with uncertainty bands), and
`docs/SPEC.md` for the bit-exact register/protocol contract.

## How to test

The fastest path is the bring-up script, which runs unmodified against a real TT
demo board or against the project's own cocotb-based virtual demo board:

1. Flash/select this project on a TT ETR demo board (RP2350), then run
   `bringup/binner_bringup.py` (`mpremote run binner_bringup.py`, or
   `import binner_bringup; binner_bringup.main(chip_id="yourname01")`). It walks
   Stage 1 (ID/register/LFSR known-answer sanity), Stage 2 (paired ring-frequency
   measurements), Stage 3 (Fmax binary search per tap), Stage 4 (PUF fingerprint from
   16 ring pairs), and optional Stage 5 (temperature re-test), writing one
   `binner_<chip_id>.csv` (schema: `docs/CSV_SCHEMA.md`).
2. For a manual first check without the full script, read back the ID registers over
   bit-banged SPI mode 0 (`ui_in[0]`=CS_N, `ui_in[1]`=SCK, `ui_in[2]`=MOSI,
   `uo_out[3]`=MISO, `f_SCK <= f_clk/8`): register 0x00 should read `0x42` ('B'),
   0x01 `0x4E` ('N'), 0x02 the version `0x02`.
3. To measure a ring pair by hand: write SRCA/SRCB (register 0x04/0x05, ring index
   0-20), set TIMING.GEXP (0x06), set CTRL.RUN (0x03 bit 0), pulse CMD.START (0x07
   bit 0), poll STATUS.DONE (0x08 bit 1 / `uo_out[6]`), then read CNTA/CNTB
   (0x09-0x0C). Frequency = `count * f_clk / 2^GEXP`. Source 20 (`clk/2`) is a
   built-in known-answer check: `count` should equal `2^GEXP / 2` within +/-1.
4. Pin-strap mode needs no SPI: set `ui_in[3]`=1, pick a ring with `ui_in[6:4]`
   (bank via `ui_in[7]`), and watch `uo_out[1]`/`uo_out[2]` toggle at the selected
   ring's frequency divided by `2^(PINDIV+1)`.

`bringup/README.md` (in the repository) has full troubleshooting -- what to check if
the ID registers don't read back, if a measurement's `SEEN` bit never sets, or if
Fmax never finds a failing frequency.

## External hardware

None required beyond a Tiny Tapeout ETR demo board (RP2350-based) for SPI/pin
access and a means of varying the board's clock frequency for the Fmax sweep (the
demo board's own PWM clock generator is sufficient, up to its practical ceiling).
No analog test equipment, no external ADC/DAC, no off-board timing reference --
every measurement in this project is digital counting against the board's own clock.
