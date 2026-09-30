# BINNER specification (contract for RTL, tests, firmware, analysis)

Top module `tt_um_parv_b_binner`, Tiny Tapeout TTGF26d, GF180MCU 7-track cells at 3.3 V.
Version register = 0x02. If this document and the RTL disagree, that is a bug; report it.

## 1. Pins

| Pin | Dir | SPI mode (ui_in[3]=0) | Pin-strap mode (ui_in[3]=1) |
|---|---|---|---|
| ui_in[0] | in | SPI CS_N (active low) | keep high |
| ui_in[1] | in | SPI SCK | – |
| ui_in[2] | in | SPI MOSI | – |
| ui_in[3] | in | PINMODE = 0 | PINMODE = 1 |
| ui_in[6:4] | in | unused | ring select `s` |
| ui_in[7] | in | FMAX_RUN level (arms Fmax checker when CTRL.FMAX_EN=1) | bank: 0 → A = ring s, 1 → A = source 16+s |
| uo_out[0] | out | LFSR state bit 15 (serial stream when stepping) | same, LFSR steps every clk |
| uo_out[1] | out | channel A counter bit PINDIV (= source ÷ 2^(PINDIV+1) when counting) | same, counters free-run |
| uo_out[2] | out | channel B counter bit PINDIV | channel B = ring 8+s |
| uo_out[3] | out | SPI MISO (0 when CS_N high) | – |
| uo_out[4] | out | STATUS.BUSY | – |
| uo_out[5] | out | OR of FFAIL (any Fmax tap failed) | – |
| uo_out[6] | out | STATUS.DONE | – |
| uo_out[7] | out | debug bit: debug_byte[DBG[5:3]] | – |
| uio[7:0] | out/in | debug_byte when UIOOE=1; all inputs (uio_oe=0) otherwise. Reset: inputs. | – |

The SPI pins match RP2350 hardware SPI0 on the TT demo board (ui_in[0]=CSn, [1]=SCK, [2]=TX, uo_out[3]=RX).
Pin-strap mode needs no SPI at all: the rings, counters and LFSR run from pins alone. In pin mode, SPI reads still work.

## 2. Reset and clocking
- `rst_n` is asserted asynchronously and released synchronously (2 flops). Every flop has a reset. After reset, all rings are off and uio pins are inputs.
- The tile is power-gated by the TT mux. State is lost when it is deselected, so always reset after selecting it.
- SPI is oversampled in the clk domain: **f_SCK ≤ f_clk/8** (use ≤ f_clk/16).
- Ring measurements and all normal register/control-plane operation: any clk from 1 Hz to 20 MHz (signoff target; verified across tt/ss/ff corners — see DECISIONS.md D-CLOCK-PERIOD). The Fmax sweep raises clk far above this (up to ~125 MHz, the demo board's practical ceiling) but only the launch flop and sticky-fail logic need to function there; no SPI transaction happens while clk is swept (see §6 step-by-step) and the Fmax capture flops are exempted from setup timing by design (they are meant to fail at speed). Do not perform SPI reads/writes while clk is above 20 MHz.

## 3. SPI protocol (mode 0: CPOL=0, CPHA=0; MSB first)
CS_N goes low, then byte 0 = `{W, A[6:0]}` (W=1 write, W=0 read), then data bytes, then CS_N goes high.
- Write: each data byte is written to A, A+1, … (auto-increment).
- Read: MISO shifts out reg[A], reg[A+1], … during the data bytes. MISO is 0 during byte 0. Reads have no side effects.
- Unmapped addresses read 0x00. Writes to read-only or unmapped addresses are ignored.

## 4. Register map (v0.2 — squeezed after the first hardening run; see DECISIONS.md D-REGMAP)

| Addr | Name | Access | Reset | Bits |
|---|---|---|---|---|
| 0x00 | ID0 | RO | 0x42 | 'B' |
| 0x01 | ID1 | RO | 0x4E | 'N' |
| 0x02 | VER | RO | 0x02 | |
| 0x03 | CTRL | RW | 0x00 | [0] RUN, [1] FREE, [2] LFSR_RUN, [3] LFSR_GATED, [4] FMAX_EN, [5] FMAX_INV, [6] UIOOE |
| 0x04 | SRCA | RW | 0x00 | [4:0] channel A source, [7:5] DTAP (delay-chain tap for source 19) |
| 0x05 | SRCB | RW | 0x08 | [4:0] channel B source, [7:5] DBG (debug byte select) |
| 0x06 | TIMING | RW | 0x5A | [3:0] GEXP (gate = 2^GEXP clk cycles, default 1024), [7:4] PINDIV (counter bit on uo_out[1]/[2]) |
| 0x07 | CMD | WO (reads 0) | – | write 1 to trigger: [0] START, [1] CLEAR, [2] LFSR_RESEED, [3] FMAX_CLEAR |
| 0x08 | STATUS | RO | 0x00 | [0] BUSY, [1] DONE, [2] OVF_A, [3] OVF_B, [4] SEEN_A, [5] SEEN_B, [6] TIMEOUT, [7] FMAX_ARMED (also on uo_out[7]) |
| 0x09/0x0A | CNTA_L/H | RO | 0 | channel A ring-domain counter — static from DONE until next START/CLEAR; live (debug only) in FREE mode |
| 0x0B/0x0C | CNTB_L/H | RO | 0 | channel B counter, same semantics |
| 0x0D/0x0E | LFSR_L/H | RO | 0xACE1 | live LFSR state |
| 0x0F | FFAIL | RO | 0x00 | sticky Fmax fail flag per tap [7:0] |
| 0x10 | FCAP | RO | 0x00 | raw Fmax capture flops (debug) |
| 0x11 | MISC | RO | – | [0] PINMODE, [1] ACK_A sync, [2] ACK_B sync, [3] FMAX_RUN pin (sync), [4] FMAX checker valid, [5] ena, [6] cnt_en, [7] ring_clr |

Unmapped addresses (0x12-0x7F) read 0x00 and ignore writes. CTRL/SRCA/SRCB/TIMING are freely readable back for full configuration readback.

Debug byte select (SRCB[7:5]): 0 LFSR[7:0], 1 LFSR[15:8], 2 CNTA[7:0], 3 CNTB[7:0], 4 STATUS, 5 FFAIL, 6 MISC, 7 CNTA[15:8].

## 5. Sources and measurement
Sources (SRCA/SRCB): 0–15 identical 25-stage INV rings (NAND2 enable + 24 INV_1); 16 NAND2 ring (25 stages); 17 NOR2 ring (25); 18 FO4 INV ring (13 stages, each loaded by 3 dummy INV_1); 19 delay-chain ring (tap DTAP); 20 clk/2; 21–31 constant 0.

A source ring oscillates only when `ena & (CTRL.RUN | PINMODE)` and it is selected by SRCA or SRCB. At most two rings run at a time.

**Source 19 (delay-chain ring) must not have its tap (SRCA[7:5]/DTAP) changed while it is running.** The tap-select mux is a purely asynchronous combinational tree inside the ring's own live feedback loop; switching it while the ring is oscillating is an async-mux-in-a-loop hazard that can mode-lock the ring onto an unintended shorter path through the tree (observed in simulation: see DECISIONS.md D-DTAP-RETUNE). To change DTAP, disable the ring first (CTRL.RUN=0, or deselect source 19 from both channels), write the new DTAP, then re-enable. This costs one extra measurement cycle per tap and is otherwise free.

Measurement (paired): write SRCA and SRCB, set TIMING.GEXP, set CTRL.RUN, then write CMD.START.
1. The ring-domain counters are cleared (2 cycles).
2. Both channels count rising edges of their source for exactly 2^GEXP clk cycles; each count is synchronised into the ring domain with 2 flops, symmetrically at start and stop.
3. The controller waits for each channel's acknowledge to fall, then sets DONE; CNTA/CNTB (the ring-domain counters themselves) are then static and readable directly.

Frequency: `f_src = CNT * f_clk / (2^GEXP)`, ±1 count.
- Known answer: source 20 (clk/2) gives CNT = 2^GEXP/2 ± 1.
- Validity: SEEN_x = 1 means channel x counted. SEEN_x = 0 means the source is dead or too slow, so the result is invalid. OVF_x = 1 means the 16-bit counter wrapped; use a shorter gate. TIMEOUT = 1 means the acknowledge did not fall within 63 cycles.
- Poll STATUS.DONE (or pin uo_out[6]) before reading CNTA/CNTB. A measurement takes 2^GEXP + about 10 clk cycles.

## 6. Fmax (at-speed) checker
- An 8-tap chain of DLYD_1 cells. Taps sit after 3, 4, 5, 6, 8, 10, 12 and 14 stages, and all 8 are checked simultaneously.
- The launch flop loads pseudo-random LFSR data each cycle while armed. Tap k fails if the capture flop k value differs from the reference flop, i.e. the tap delay plus overhead exceeds T_clk.
- Armed = CTRL.FMAX_EN & sync(ui_in[7]) & !PINMODE. FFAIL is sticky until CMD.FMAX_CLEAR.

Procedure per frequency f:
1. At a safe clk (e.g. 10 MHz), set CTRL.FMAX_EN and write CMD.FMAX_CLEAR. Hold ui_in[7] low. uo_out[7] (FMAX_ARMED) confirms the checker is active once armed.
2. Switch clk to f and wait for it to settle.
3. Raise ui_in[7] for the test window (e.g. ≥ 10 ms), then lower it.
4. Switch clk back to the safe frequency and read FFAIL.

FMAX_INV=1 must make every tap fail; this is the polarity self-test.

The same chain, selected as source 19, forms a ring through the tap mux. Its period is 2·(t_overhead + t_chain(tap)), and it gives a direct measurement of stage delay.

## 7. LFSR
16-bit Fibonacci LFSR, x^16+x^15+x^13+x^4+1, with de Bruijn zero insertion (period 65536, no lock-up). next = `{q[14:0], q15^q14^q12^q3^(q[14:0]==0)}`. Reset/reseed value 0xACE1.

Known-answer: CMD.LFSR_RESEED, then CTRL.LFSR_GATED=1, TIMING.GEXP=k (N = 2^k), CMD.START; after DONE, LFSR = the state after N steps from 0xACE1.

## 8. Simulation hooks (RTL only, `BINNER_BEHAV` defined)
- Ring `IDX` half period in femtoseconds: plusarg `+RING<IDX>_HP_FS=<int>`. IDX 0–18 are the rings; the default is 2.5 ns + IDX·1 ps.
- Delay-chain stage i (1..14) delay: `+DSTG<i>_FS=<int>` (default 3.4 ns). Mux overhead: `+DCHAIN_OVH_FS` (default 0.6 ns).
- Gate-level simulation (GATES=yes) must keep all rings disabled: CTRL.RUN=0, or select only sources 20–31. Use source 20 to exercise the counters.
