# BINNER simulated variation model (virtual population contract)

The virtual demo board draws each simulated chip from this generative model. The analysis pipeline must recover these parameters from the CSVs alone, and validation compares its estimates with `truth_<chip>.json`.

## Per-chip (die-to-die) parameters
- `s_n`, `s_p` ~ N(0, σ_d2d = 0.04): relative NMOS and PMOS drive shifts (0.04 = 4 % 1σ). They are drawn independently, with an optional correlation ρ = 0.5.
- `g_x`, `g_y` ~ N(0, 0.005): systematic linear gradient of the delay factor across the tile, per unit of normalised coordinate.
- `T_c` ~ U(22, 35) °C: operating temperature. It adds +0.15 %/°C of delay relative to 25 °C, identical for all structures.
- `t_ov` = 0.9 ns × (1 + 0.5·(s_n+s_p)/2 noise-free): Fmax flop overhead (clk-to-Q + setup + skew).

## Structure delay factor
Delay per stage for structure type k at location (x, y) (normalised to [-1, 1] across the tile, taken from the DEF ring centroid):

    d = d0_k · exp(-(w_nk·s_n + w_pk·s_p)) · (1 + g_x·x + g_y·y) · (1 + 0.0015·(T_c-25)) · (1 + ε)

| k | d0_k (per stage, ns) | w_n | w_p | stages |
|---|---|---|---|---|
| INV (R00..R15) | 0.100 | 0.5 | 0.5 | 25 |
| NAND | 0.135 | 0.7 | 0.3 | 25 |
| NOR | 0.160 | 0.25 | 0.75 | 25 |
| FO4 | 0.230 | 0.5 | 0.5 | 25 |
| DLY (chain stage) | 3.40 | 0.5 | 0.5 | per stage |

- ε ~ N(0, σ_wid = 0.008): within-die random mismatch, independent per ring (and per chain stage, with σ = 0.004).
- Ring half period = N·d, and f = 1 / (2·N·d).
- Chain tap delay D_k = Σ stage delays up to tap k, plus 0.6 ns mux overhead. Fmax_k = 1 / (D_k + t_ov).
- Measurement noise: counts are exact ±1 (quantisation). Ring jitter: none, beyond the ±1 LSB quantisation and a 0.02 % white per-measurement frequency noise (thermal/supply). PUF instability comes from that noise acting on pairs with small mismatch.

The default nominal values are placeholders, to be replaced by SDF-derived predictions (tools/sdf_predict.py) once the post-route SDF exists; the model structure stays the same.

## Recovery targets (validation)
The analysis must estimate, with bootstrap 90 % confidence intervals:
1. σ_d2d from the population spread of mean INV ring frequency.
2. Per-chip (s_n, s_p) from the INV/NAND/NOR frequency ratios (N/P skew).
3. Per-chip (g_x, g_y) and population σ_wid from the 16 identical rings (systematic vs random decomposition).
4. Chain per-stage delay and t_ov from the Fmax-vs-tap regression, cross-checked against the DCH ring regression.
5. PUF metrics: uniformity, inter-chip HD, intra-chip reliability and bit-aliasing, with expected values under the model.

Stated error targets for N = 20: σ_d2d within ±35 %, σ_wid within ±25 %, per-chip s_n − s_p within ±0.025, per-stage delay within ±2 %. Degradation at N = 8 is to be reported, not hidden.

**s_n − s_p target revised from ±0.01 to ±0.025 (2026-09-30).** The analysis pipeline's Monte-Carlo validation (`analysis/VALIDATION.md`) measured RMSE ≈0.025 at both N=20 and N=8 — unchanged by population size, meaning it is a per-die measurement-noise floor (from having only one NAND ring and one NOR ring per die), not a population-sampling limit that more chips or a smarter estimator would fix. See DECISIONS.md D-UTILIZATION's discussion of why adding redundant N/P-sensitive structures was not pursued (area cost, and the utilization target that motivated minimizing it was itself relaxed). The revised target reflects what the built chip can actually measure, not what a differently-designed chip could.
