# BINNER post-route SDF timing prediction

Corners: 9 SDF files (max_ff_n40C_3v60, max_ss_125C_3v00, max_tt_025C_3v30, min_ff_n40C_3v60, min_ss_125C_3v00, min_tt_025C_3v30, nom_ff_n40C_3v60, nom_ss_125C_3v00, nom_tt_025C_3v30).

## N/P skew signature (NAND/NOR ring vs. average INV/PUF ring frequency)

| corner | puf avg freq (GHz) | nand/puf ratio | nor/puf ratio |
|---|---|---|---|
| max_ff_n40C_3v60 | 0.220 | 0.685 | 0.580 |
| max_ss_125C_3v00 | 0.068 | 0.662 | 0.543 |
| max_tt_025C_3v30 | 0.132 | 0.676 | 0.561 |
| min_ff_n40C_3v60 | 0.228 | 0.676 | 0.571 |
| min_ss_125C_3v00 | 0.071 | 0.654 | 0.536 |
| min_tt_025C_3v30 | 0.136 | 0.667 | 0.553 |
| nom_ff_n40C_3v60 | 0.224 | 0.680 | 0.575 |
| nom_ss_125C_3v00 | 0.070 | 0.658 | 0.539 |
| nom_tt_025C_3v30 | 0.134 | 0.672 | 0.556 |

## Per-ring oscillation frequency (typical corner value; min/max = OCV bounds from the SDF triples)

### max_ff_n40C_3v60

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 4.122 | 4.119 | 4.124 | 0.243 |
| g_puf[1] | INV | 25 | 4.104 | 4.100 | 4.107 | 0.244 |
| g_puf[2] | INV | 25 | 4.180 | 4.176 | 4.182 | 0.239 |
| g_puf[3] | INV | 25 | 4.392 | 4.388 | 4.395 | 0.228 |
| g_puf[4] | INV | 25 | 5.530 | 5.528 | 5.533 | 0.181 |
| g_puf[5] | INV | 25 | 4.774 | 4.773 | 4.778 | 0.209 |
| g_puf[6] | INV | 25 | 4.287 | 4.284 | 4.290 | 0.233 |
| g_puf[7] | INV | 25 | 5.951 | 5.948 | 5.953 | 0.168 |
| g_puf[8] | INV | 25 | 4.465 | 4.462 | 4.468 | 0.224 |
| g_puf[9] | INV | 25 | 4.086 | 4.083 | 4.089 | 0.245 |
| g_puf[10] | INV | 25 | 4.163 | 4.162 | 4.166 | 0.240 |
| g_puf[11] | INV | 25 | 4.320 | 4.316 | 4.322 | 0.231 |
| g_puf[12] | INV | 25 | 6.156 | 6.152 | 6.160 | 0.162 |
| g_puf[13] | INV | 25 | 5.006 | 5.005 | 5.008 | 0.200 |
| g_puf[14] | INV | 25 | 4.273 | 4.269 | 4.274 | 0.234 |
| g_puf[15] | INV | 25 | 4.150 | 4.146 | 4.153 | 0.241 |
| ring_nand | NAND | 25 | 6.631 | 5.715 | 7.548 | 0.151 |
| ring_nor | NOR | 25 | 7.834 | 6.767 | 8.906 | 0.128 |
| ring_fo4 | FO4 | 13 | 5.755 | 5.753 | 5.756 | 0.174 |

### max_ss_125C_3v00

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 13.352 | 13.343 | 13.359 | 0.075 |
| g_puf[1] | INV | 25 | 13.300 | 13.287 | 13.310 | 0.075 |
| g_puf[2] | INV | 25 | 13.518 | 13.509 | 13.527 | 0.074 |
| g_puf[3] | INV | 25 | 14.165 | 14.155 | 14.173 | 0.071 |
| g_puf[4] | INV | 25 | 17.608 | 17.600 | 17.618 | 0.057 |
| g_puf[5] | INV | 25 | 15.331 | 15.322 | 15.338 | 0.065 |
| g_puf[6] | INV | 25 | 13.838 | 13.829 | 13.846 | 0.072 |
| g_puf[7] | INV | 25 | 18.906 | 18.899 | 18.914 | 0.053 |
| g_puf[8] | INV | 25 | 14.394 | 14.386 | 14.405 | 0.069 |
| g_puf[9] | INV | 25 | 13.242 | 13.234 | 13.252 | 0.076 |
| g_puf[10] | INV | 25 | 13.472 | 13.463 | 13.479 | 0.074 |
| g_puf[11] | INV | 25 | 13.959 | 13.951 | 13.968 | 0.072 |
| g_puf[12] | INV | 25 | 19.482 | 19.470 | 19.494 | 0.051 |
| g_puf[13] | INV | 25 | 16.026 | 16.020 | 16.031 | 0.062 |
| g_puf[14] | INV | 25 | 13.791 | 13.783 | 13.798 | 0.073 |
| g_puf[15] | INV | 25 | 13.440 | 13.431 | 13.449 | 0.074 |
| ring_nand | NAND | 25 | 22.106 | 19.212 | 25.000 | 0.045 |
| ring_nor | NOR | 25 | 26.955 | 23.893 | 30.023 | 0.037 |
| ring_fo4 | FO4 | 13 | 18.265 | 18.260 | 18.268 | 0.055 |

### max_tt_025C_3v30

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 6.908 | 6.904 | 6.911 | 0.145 |
| g_puf[1] | INV | 25 | 6.877 | 6.870 | 6.883 | 0.145 |
| g_puf[2] | INV | 25 | 6.997 | 6.992 | 7.003 | 0.143 |
| g_puf[3] | INV | 25 | 7.342 | 7.337 | 7.349 | 0.136 |
| g_puf[4] | INV | 25 | 9.210 | 9.205 | 9.214 | 0.109 |
| g_puf[5] | INV | 25 | 7.982 | 7.976 | 7.986 | 0.125 |
| g_puf[6] | INV | 25 | 7.169 | 7.166 | 7.174 | 0.139 |
| g_puf[7] | INV | 25 | 9.905 | 9.902 | 9.909 | 0.101 |
| g_puf[8] | INV | 25 | 7.467 | 7.462 | 7.473 | 0.134 |
| g_puf[9] | INV | 25 | 6.839 | 6.835 | 6.844 | 0.146 |
| g_puf[10] | INV | 25 | 6.972 | 6.969 | 6.975 | 0.143 |
| g_puf[11] | INV | 25 | 7.227 | 7.222 | 7.230 | 0.138 |
| g_puf[12] | INV | 25 | 10.240 | 10.234 | 10.246 | 0.098 |
| g_puf[13] | INV | 25 | 8.355 | 8.352 | 8.358 | 0.120 |
| g_puf[14] | INV | 25 | 7.151 | 7.147 | 7.154 | 0.140 |
| g_puf[15] | INV | 25 | 6.944 | 6.939 | 6.950 | 0.144 |
| ring_nand | NAND | 25 | 11.227 | 9.746 | 12.712 | 0.089 |
| ring_nor | NOR | 25 | 13.547 | 11.898 | 15.198 | 0.074 |
| ring_fo4 | FO4 | 13 | 9.536 | 9.532 | 9.539 | 0.105 |

### min_ff_n40C_3v60

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 4.055 | 4.052 | 4.057 | 0.247 |
| g_puf[1] | INV | 25 | 4.039 | 4.035 | 4.041 | 0.248 |
| g_puf[2] | INV | 25 | 4.106 | 4.102 | 4.108 | 0.244 |
| g_puf[3] | INV | 25 | 4.257 | 4.252 | 4.259 | 0.235 |
| g_puf[4] | INV | 25 | 5.141 | 5.138 | 5.142 | 0.195 |
| g_puf[5] | INV | 25 | 4.547 | 4.546 | 4.550 | 0.220 |
| g_puf[6] | INV | 25 | 4.178 | 4.176 | 4.182 | 0.239 |
| g_puf[7] | INV | 25 | 5.484 | 5.481 | 5.487 | 0.182 |
| g_puf[8] | INV | 25 | 4.305 | 4.302 | 4.308 | 0.232 |
| g_puf[9] | INV | 25 | 4.035 | 4.033 | 4.038 | 0.248 |
| g_puf[10] | INV | 25 | 4.083 | 4.081 | 4.087 | 0.245 |
| g_puf[11] | INV | 25 | 4.206 | 4.203 | 4.209 | 0.238 |
| g_puf[12] | INV | 25 | 5.606 | 5.603 | 5.609 | 0.178 |
| g_puf[13] | INV | 25 | 4.729 | 4.727 | 4.730 | 0.211 |
| g_puf[14] | INV | 25 | 4.167 | 4.165 | 4.171 | 0.240 |
| g_puf[15] | INV | 25 | 4.071 | 4.068 | 4.074 | 0.246 |
| ring_nand | NAND | 25 | 6.492 | 5.598 | 7.392 | 0.154 |
| ring_nor | NOR | 25 | 7.679 | 6.640 | 8.716 | 0.130 |
| ring_fo4 | FO4 | 13 | 5.632 | 5.630 | 5.633 | 0.178 |

### min_ss_125C_3v00

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 13.131 | 13.125 | 13.139 | 0.076 |
| g_puf[1] | INV | 25 | 13.099 | 13.089 | 13.108 | 0.076 |
| g_puf[2] | INV | 25 | 13.286 | 13.278 | 13.295 | 0.075 |
| g_puf[3] | INV | 25 | 13.759 | 13.751 | 13.767 | 0.073 |
| g_puf[4] | INV | 25 | 16.419 | 16.411 | 16.426 | 0.061 |
| g_puf[5] | INV | 25 | 14.636 | 14.628 | 14.643 | 0.068 |
| g_puf[6] | INV | 25 | 13.515 | 13.508 | 13.523 | 0.074 |
| g_puf[7] | INV | 25 | 17.473 | 17.466 | 17.482 | 0.057 |
| g_puf[8] | INV | 25 | 13.902 | 13.893 | 13.909 | 0.072 |
| g_puf[9] | INV | 25 | 13.072 | 13.065 | 13.080 | 0.076 |
| g_puf[10] | INV | 25 | 13.228 | 13.222 | 13.236 | 0.076 |
| g_puf[11] | INV | 25 | 13.611 | 13.602 | 13.621 | 0.073 |
| g_puf[12] | INV | 25 | 17.813 | 17.802 | 17.823 | 0.056 |
| g_puf[13] | INV | 25 | 15.188 | 15.182 | 15.195 | 0.066 |
| g_puf[14] | INV | 25 | 13.482 | 13.473 | 13.491 | 0.074 |
| g_puf[15] | INV | 25 | 13.215 | 13.206 | 13.224 | 0.076 |
| ring_nand | NAND | 25 | 21.659 | 18.845 | 24.471 | 0.046 |
| ring_nor | NOR | 25 | 26.415 | 23.441 | 29.384 | 0.038 |
| ring_fo4 | FO4 | 13 | 17.892 | 17.888 | 17.896 | 0.056 |

### min_tt_025C_3v30

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 6.786 | 6.783 | 6.790 | 0.147 |
| g_puf[1] | INV | 25 | 6.768 | 6.760 | 6.774 | 0.148 |
| g_puf[2] | INV | 25 | 6.875 | 6.870 | 6.879 | 0.145 |
| g_puf[3] | INV | 25 | 7.125 | 7.120 | 7.131 | 0.140 |
| g_puf[4] | INV | 25 | 8.573 | 8.568 | 8.577 | 0.117 |
| g_puf[5] | INV | 25 | 7.606 | 7.600 | 7.610 | 0.131 |
| g_puf[6] | INV | 25 | 6.995 | 6.991 | 6.999 | 0.143 |
| g_puf[7] | INV | 25 | 9.138 | 9.134 | 9.142 | 0.109 |
| g_puf[8] | INV | 25 | 7.201 | 7.196 | 7.207 | 0.139 |
| g_puf[9] | INV | 25 | 6.750 | 6.746 | 6.755 | 0.148 |
| g_puf[10] | INV | 25 | 6.837 | 6.834 | 6.841 | 0.146 |
| g_puf[11] | INV | 25 | 7.041 | 7.036 | 7.046 | 0.142 |
| g_puf[12] | INV | 25 | 9.344 | 9.339 | 9.350 | 0.107 |
| g_puf[13] | INV | 25 | 7.904 | 7.900 | 7.906 | 0.127 |
| g_puf[14] | INV | 25 | 6.984 | 6.979 | 6.988 | 0.143 |
| g_puf[15] | INV | 25 | 6.824 | 6.816 | 6.828 | 0.147 |
| ring_nand | NAND | 25 | 10.996 | 9.554 | 12.445 | 0.091 |
| ring_nor | NOR | 25 | 13.269 | 11.671 | 14.869 | 0.075 |
| ring_fo4 | FO4 | 13 | 9.331 | 9.329 | 9.334 | 0.107 |

### nom_ff_n40C_3v60

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 4.084 | 4.081 | 4.085 | 0.245 |
| g_puf[1] | INV | 25 | 4.069 | 4.066 | 4.073 | 0.246 |
| g_puf[2] | INV | 25 | 4.139 | 4.137 | 4.142 | 0.242 |
| g_puf[3] | INV | 25 | 4.317 | 4.315 | 4.322 | 0.232 |
| g_puf[4] | INV | 25 | 5.316 | 5.315 | 5.319 | 0.188 |
| g_puf[5] | INV | 25 | 4.649 | 4.647 | 4.651 | 0.215 |
| g_puf[6] | INV | 25 | 4.228 | 4.226 | 4.230 | 0.237 |
| g_puf[7] | INV | 25 | 5.698 | 5.695 | 5.698 | 0.176 |
| g_puf[8] | INV | 25 | 4.375 | 4.372 | 4.378 | 0.229 |
| g_puf[9] | INV | 25 | 4.059 | 4.056 | 4.060 | 0.246 |
| g_puf[10] | INV | 25 | 4.121 | 4.118 | 4.123 | 0.243 |
| g_puf[11] | INV | 25 | 4.259 | 4.257 | 4.262 | 0.235 |
| g_puf[12] | INV | 25 | 5.859 | 5.856 | 5.863 | 0.171 |
| g_puf[13] | INV | 25 | 4.855 | 4.854 | 4.858 | 0.206 |
| g_puf[14] | INV | 25 | 4.222 | 4.219 | 4.224 | 0.237 |
| g_puf[15] | INV | 25 | 4.109 | 4.107 | 4.113 | 0.243 |
| ring_nand | NAND | 25 | 6.555 | 5.650 | 7.460 | 0.153 |
| ring_nor | NOR | 25 | 7.752 | 6.698 | 8.807 | 0.129 |
| ring_fo4 | FO4 | 13 | 5.691 | 5.689 | 5.693 | 0.176 |

### nom_ss_125C_3v00

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 13.229 | 13.220 | 13.236 | 0.076 |
| g_puf[1] | INV | 25 | 13.191 | 13.181 | 13.202 | 0.076 |
| g_puf[2] | INV | 25 | 13.393 | 13.384 | 13.402 | 0.075 |
| g_puf[3] | INV | 25 | 13.945 | 13.935 | 13.954 | 0.072 |
| g_puf[4] | INV | 25 | 16.962 | 16.953 | 16.970 | 0.059 |
| g_puf[5] | INV | 25 | 14.946 | 14.937 | 14.952 | 0.067 |
| g_puf[6] | INV | 25 | 13.666 | 13.658 | 13.674 | 0.073 |
| g_puf[7] | INV | 25 | 18.125 | 18.115 | 18.134 | 0.055 |
| g_puf[8] | INV | 25 | 14.125 | 14.115 | 14.133 | 0.071 |
| g_puf[9] | INV | 25 | 13.150 | 13.141 | 13.158 | 0.076 |
| g_puf[10] | INV | 25 | 13.339 | 13.331 | 13.346 | 0.075 |
| g_puf[11] | INV | 25 | 13.768 | 13.760 | 13.777 | 0.073 |
| g_puf[12] | INV | 25 | 18.575 | 18.564 | 18.588 | 0.054 |
| g_puf[13] | INV | 25 | 15.569 | 15.564 | 15.575 | 0.064 |
| g_puf[14] | INV | 25 | 13.621 | 13.614 | 13.628 | 0.073 |
| g_puf[15] | INV | 25 | 13.320 | 13.312 | 13.330 | 0.075 |
| ring_nand | NAND | 25 | 21.856 | 19.010 | 24.713 | 0.046 |
| ring_nor | NOR | 25 | 26.662 | 23.644 | 29.673 | 0.038 |
| ring_fo4 | FO4 | 13 | 18.064 | 18.061 | 18.068 | 0.055 |

### nom_tt_025C_3v30

| ring | kind | N | period typ (ns) | period min (ns) | period max (ns) | freq typ (GHz) |
|---|---|---|---|---|---|---|
| g_puf[0] | INV | 25 | 6.841 | 6.837 | 6.845 | 0.146 |
| g_puf[1] | INV | 25 | 6.817 | 6.811 | 6.824 | 0.147 |
| g_puf[2] | INV | 25 | 6.926 | 6.921 | 6.931 | 0.144 |
| g_puf[3] | INV | 25 | 7.227 | 7.220 | 7.231 | 0.138 |
| g_puf[4] | INV | 25 | 8.862 | 8.858 | 8.866 | 0.113 |
| g_puf[5] | INV | 25 | 7.775 | 7.771 | 7.778 | 0.129 |
| g_puf[6] | INV | 25 | 7.075 | 7.071 | 7.079 | 0.141 |
| g_puf[7] | INV | 25 | 9.484 | 9.481 | 9.490 | 0.105 |
| g_puf[8] | INV | 25 | 7.319 | 7.312 | 7.325 | 0.137 |
| g_puf[9] | INV | 25 | 6.794 | 6.790 | 6.797 | 0.147 |
| g_puf[10] | INV | 25 | 6.898 | 6.894 | 6.902 | 0.145 |
| g_puf[11] | INV | 25 | 7.124 | 7.119 | 7.130 | 0.140 |
| g_puf[12] | INV | 25 | 9.749 | 9.743 | 9.756 | 0.103 |
| g_puf[13] | INV | 25 | 8.105 | 8.103 | 8.108 | 0.123 |
| g_puf[14] | INV | 25 | 7.059 | 7.054 | 7.062 | 0.142 |
| g_puf[15] | INV | 25 | 6.876 | 6.871 | 6.882 | 0.145 |
| ring_nand | NAND | 25 | 11.101 | 9.642 | 12.566 | 0.090 |
| ring_nor | NOR | 25 | 13.400 | 11.775 | 15.021 | 0.075 |
| ring_fo4 | FO4 | 13 | 9.422 | 9.419 | 9.424 | 0.106 |

## Fmax per tap (launch ck2q + worst-case chain delay + setup - clk skew)

### max_ff_n40C_3v60

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 0.833 | 5.916 | 0.277 | 0.000 | 7.026 | 0.142 | 14.019 | 0.071 |
| 1 | 4 | 0.833 | 7.978 | 0.264 | 0.000 | 9.075 | 0.110 | 18.004 | 0.056 |
| 2 | 5 | 0.833 | 10.029 | 0.265 | 0.000 | 11.127 | 0.090 | 21.940 | 0.046 |
| 3 | 6 | 0.833 | 12.172 | 0.293 | 0.000 | 13.298 | 0.075 | 26.169 | 0.038 |
| 4 | 8 | 0.833 | 16.210 | 0.272 | 0.000 | 17.315 | 0.058 | 34.026 | 0.029 |
| 5 | 10 | 0.833 | 20.213 | 0.270 | -0.001 | 21.317 | 0.047 | 41.804 | 0.024 |
| 6 | 12 | 0.833 | 24.203 | 0.267 | 0.000 | 25.303 | 0.040 | 49.547 | 0.020 |
| 7 | 14 | 0.833 | 28.185 | 0.265 | 0.000 | 29.283 | 0.034 | 57.287 | 0.017 |

### max_ss_125C_3v00

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 3.021 | 22.927 | 1.084 | 0.000 | 27.032 | 0.037 | 53.362 | 0.019 |
| 1 | 4 | 3.021 | 30.881 | 1.045 | 0.000 | 34.947 | 0.029 | 68.755 | 0.015 |
| 2 | 5 | 3.021 | 38.807 | 1.049 | 0.000 | 42.877 | 0.023 | 83.975 | 0.012 |
| 3 | 6 | 3.021 | 47.035 | 1.129 | 0.000 | 51.185 | 0.020 | 100.143 | 0.010 |
| 4 | 8 | 3.021 | 62.649 | 1.065 | 0.000 | 66.735 | 0.015 | 130.508 | 0.008 |
| 5 | 10 | 3.021 | 78.148 | 1.067 | -0.001 | 82.237 | 0.012 | 160.624 | 0.006 |
| 6 | 12 | 3.021 | 93.611 | 1.055 | 0.000 | 97.687 | 0.010 | 190.620 | 0.005 |
| 7 | 14 | 3.021 | 109.048 | 1.044 | 0.000 | 113.113 | 0.009 | 220.598 | 0.005 |

### max_tt_025C_3v30

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 1.475 | 10.945 | 0.508 | 0.000 | 12.928 | 0.077 | 25.671 | 0.039 |
| 1 | 4 | 1.475 | 14.750 | 0.486 | 0.000 | 16.711 | 0.060 | 33.033 | 0.030 |
| 2 | 5 | 1.475 | 18.537 | 0.488 | 0.000 | 20.500 | 0.049 | 40.305 | 0.025 |
| 3 | 6 | 1.475 | 22.481 | 0.532 | 0.000 | 24.488 | 0.041 | 48.075 | 0.021 |
| 4 | 8 | 1.475 | 29.942 | 0.498 | 0.000 | 31.915 | 0.031 | 62.595 | 0.016 |
| 5 | 10 | 1.475 | 37.343 | 0.497 | -0.001 | 39.316 | 0.025 | 76.981 | 0.013 |
| 6 | 12 | 1.475 | 44.723 | 0.491 | 0.000 | 46.689 | 0.021 | 91.308 | 0.011 |
| 7 | 14 | 1.475 | 52.089 | 0.488 | 0.000 | 54.052 | 0.019 | 105.626 | 0.009 |

### min_ff_n40C_3v60

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 0.822 | 5.899 | 0.275 | 0.000 | 6.996 | 0.143 | 13.912 | 0.072 |
| 1 | 4 | 0.822 | 7.953 | 0.264 | 0.000 | 9.039 | 0.111 | 17.887 | 0.056 |
| 2 | 5 | 0.822 | 9.997 | 0.265 | 0.000 | 11.084 | 0.090 | 21.818 | 0.046 |
| 3 | 6 | 0.822 | 12.117 | 0.288 | 0.000 | 13.227 | 0.076 | 25.992 | 0.038 |
| 4 | 8 | 0.822 | 16.136 | 0.270 | -0.001 | 17.229 | 0.058 | 33.807 | 0.030 |
| 5 | 10 | 0.822 | 20.126 | 0.269 | -0.001 | 21.218 | 0.047 | 41.561 | 0.024 |
| 6 | 12 | 0.822 | 24.106 | 0.266 | 0.000 | 25.194 | 0.040 | 49.287 | 0.020 |
| 7 | 14 | 0.822 | 28.076 | 0.263 | 0.000 | 29.161 | 0.034 | 56.999 | 0.018 |

### min_ss_125C_3v00

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 2.984 | 22.873 | 1.077 | 0.000 | 26.934 | 0.037 | 53.007 | 0.019 |
| 1 | 4 | 2.984 | 30.801 | 1.045 | 0.000 | 34.830 | 0.029 | 68.359 | 0.015 |
| 2 | 5 | 2.984 | 38.703 | 1.047 | 0.000 | 42.734 | 0.023 | 83.566 | 0.012 |
| 3 | 6 | 2.984 | 46.853 | 1.121 | 0.000 | 50.958 | 0.020 | 99.555 | 0.010 |
| 4 | 8 | 2.984 | 62.405 | 1.066 | -0.001 | 66.456 | 0.015 | 129.791 | 0.008 |
| 5 | 10 | 2.984 | 77.864 | 1.062 | -0.001 | 81.911 | 0.012 | 159.828 | 0.006 |
| 6 | 12 | 2.984 | 93.294 | 1.053 | 0.000 | 97.331 | 0.010 | 189.767 | 0.005 |
| 7 | 14 | 2.984 | 108.691 | 1.039 | 0.000 | 112.714 | 0.009 | 219.661 | 0.005 |

### min_tt_025C_3v30

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 1.456 | 10.918 | 0.505 | 0.000 | 12.879 | 0.078 | 25.490 | 0.039 |
| 1 | 4 | 1.456 | 14.710 | 0.487 | 0.000 | 16.653 | 0.060 | 32.832 | 0.030 |
| 2 | 5 | 1.456 | 18.485 | 0.488 | 0.000 | 20.429 | 0.049 | 40.099 | 0.025 |
| 3 | 6 | 1.456 | 22.389 | 0.526 | 0.000 | 24.371 | 0.041 | 47.774 | 0.021 |
| 4 | 8 | 1.456 | 29.818 | 0.497 | -0.001 | 31.772 | 0.031 | 62.225 | 0.016 |
| 5 | 10 | 1.456 | 37.199 | 0.495 | -0.001 | 39.151 | 0.026 | 76.572 | 0.013 |
| 6 | 12 | 1.456 | 44.562 | 0.491 | 0.000 | 46.509 | 0.022 | 90.869 | 0.011 |
| 7 | 14 | 1.456 | 51.908 | 0.486 | 0.000 | 53.850 | 0.019 | 105.146 | 0.010 |

### nom_ff_n40C_3v60

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 0.827 | 5.907 | 0.276 | 0.000 | 7.010 | 0.143 | 13.960 | 0.072 |
| 1 | 4 | 0.827 | 7.965 | 0.264 | 0.000 | 9.056 | 0.110 | 17.941 | 0.056 |
| 2 | 5 | 0.827 | 10.012 | 0.265 | 0.000 | 11.104 | 0.090 | 21.874 | 0.046 |
| 3 | 6 | 0.827 | 12.142 | 0.291 | 0.000 | 13.260 | 0.075 | 26.073 | 0.038 |
| 4 | 8 | 0.827 | 16.170 | 0.271 | 0.000 | 17.268 | 0.058 | 33.908 | 0.029 |
| 5 | 10 | 0.827 | 20.166 | 0.269 | -0.001 | 21.263 | 0.047 | 41.673 | 0.024 |
| 6 | 12 | 0.827 | 24.151 | 0.267 | 0.000 | 25.245 | 0.040 | 49.408 | 0.020 |
| 7 | 14 | 0.827 | 28.126 | 0.264 | 0.000 | 29.217 | 0.034 | 57.132 | 0.018 |

### nom_ss_125C_3v00

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 3.000 | 22.897 | 1.080 | 0.000 | 26.977 | 0.037 | 53.169 | 0.019 |
| 1 | 4 | 3.000 | 30.836 | 1.045 | 0.000 | 34.881 | 0.029 | 68.539 | 0.015 |
| 2 | 5 | 3.000 | 38.749 | 1.048 | 0.000 | 42.797 | 0.023 | 83.751 | 0.012 |
| 3 | 6 | 3.000 | 46.935 | 1.125 | 0.000 | 51.060 | 0.020 | 99.823 | 0.010 |
| 4 | 8 | 3.000 | 62.515 | 1.063 | 0.000 | 66.578 | 0.015 | 130.115 | 0.008 |
| 5 | 10 | 3.000 | 77.991 | 1.064 | -0.001 | 82.056 | 0.012 | 160.187 | 0.006 |
| 6 | 12 | 3.000 | 93.436 | 1.054 | 0.000 | 97.490 | 0.010 | 190.153 | 0.005 |
| 7 | 14 | 3.000 | 108.850 | 1.041 | 0.000 | 112.891 | 0.009 | 220.085 | 0.005 |

### nom_tt_025C_3v30

| tap | chain stage | ck2q (ns) | chain (ns) | setup (ns) | clk skew (ns) | T_min (ns) | Fmax (GHz) | ring period (ns) | ring freq (GHz) |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3 | 1.465 | 10.931 | 0.506 | 0.000 | 12.902 | 0.078 | 25.574 | 0.039 |
| 1 | 4 | 1.465 | 14.729 | 0.486 | 0.000 | 16.680 | 0.060 | 32.924 | 0.030 |
| 2 | 5 | 1.465 | 18.510 | 0.488 | 0.000 | 20.463 | 0.049 | 40.194 | 0.025 |
| 3 | 6 | 1.465 | 22.432 | 0.530 | 0.000 | 24.427 | 0.041 | 47.914 | 0.021 |
| 4 | 8 | 1.465 | 29.876 | 0.497 | 0.000 | 31.838 | 0.031 | 62.396 | 0.016 |
| 5 | 10 | 1.465 | 37.267 | 0.496 | -0.001 | 39.229 | 0.025 | 76.761 | 0.013 |
| 6 | 12 | 1.465 | 44.637 | 0.491 | 0.000 | 46.593 | 0.021 | 91.072 | 0.011 |
| 7 | 14 | 1.465 | 51.992 | 0.487 | 0.000 | 53.944 | 0.019 | 105.368 | 0.009 |

## Assumptions and limitations

- **Hand-rolled, not OpenSTA.** This is a from-first-principles sanity check built directly off the SDF's own IOPATH/INTERCONNECT/TIMINGCHECK arcs; it is meant to cross-check the CI's OpenSTA-derived setup/hold/Fmax results (see docs/reports/<sha>/metrics_summary), not replace them.
- **Edge polarity.** SDF rise/fall triples are indexed by the *output* transition. Every ring stage cell here (INV1, and NAND2/NOR2 with the other input held static during oscillation) is inverting on its dynamic input, so the predictor flips the tracked edge at every ring stage and the dfbg_notouch_ NAND in the delay-chain ring-mode loop, and keeps it fixed through non-inverting DLY/MUX2 stages. Getting this wrong would silently halve or double the predicted period.
- **Two trips per period.** All four ring kinds (INV/PUF, NAND, NOR, FO4) use an ODD stage count (N_STG=25 or N_FO4=13), so one trip around the loop inverts polarity and a full period is two trips; likewise the delay-chain ring-mode loop has exactly one inversion (the dfbg NAND) per trip.
- **Chain (Fmax) worst-case polarity.** The Fmax launch value comes from an LFSR bit, i.e. either polarity is equally likely on any given chain traversal. chain_delay_to_tap() therefore sums max(rise, fall) at every DLY stage -- a conservative bound, not the delay of one specific toggle sequence. The ring-mode chain computation (used for the ring-period column), by contrast, tracks one consistent edge through the whole loop, since a real oscillator settles into a fixed edge-alternation pattern.
- **Launch ck2q** is likewise reported as max(rise, fall) clk-to-Q, for the same reason.
- **Clock skew** between the launch and each capture flop is estimated from the *typical* value of the single largest clock-network INTERCONNECT hop feeding each flop's CLK pin in the SDF's top-level CELL block (its total clock latency from the clock root is not represented as a single INTERCONNECT entry in this SDF format, so this is a *relative* last-hop estimate only, not full insertion delay -- treat clk_skew_ns as a rough, possibly noisy, correction, not a sign-off number).
- **Interconnect between logic stages is not separately added.** IOPATH delays in this SDF are reported as pin-to-pin cell delays only; net RC is captured in the separate INTERCONNECT records keyed by exact driver/load pin pairs. Resolving those per-stage (rather than only for the CLK network, as done above) needs the exact yosys-assigned generate-block path for every stage, which this script resolves via the parsed netlist -- if a stage's expected INTERCONNECT entry is absent (observed occasionally for very short, near-zero, same-row hops) it is silently treated as 0 ns and counted in the warnings list below rather than failing the run.
- **GF180 PDK corner limitation.** gf180mcu_fd_sc_mcu7t5v0 ships only `tt`/`ss`/`ff` timing corners (crossed here with LibreLane's `min`/`nom`/`max` parasitic-extraction corners = 9 SDF files total). There is no `fs` (fast-NMOS/slow-PMOS) or `sf` (slow-NMOS/fast-PMOS) corner in this PDK, so this predictor -- like the CI's own STA -- cannot see N/P-mismatch-driven setup/hold pessimism that asymmetric process corners would expose; the NAND/PUF and NOR/PUF frequency ratios above are the closest available proxy for that mismatch (they respond to the *relative* NMOS/PMOS drive strength baked into each corner's ss/ff/tt model, just not to the two skewed corners that don't exist for this PDK).
