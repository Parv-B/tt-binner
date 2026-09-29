"""Unit tests for the statistical building blocks in binner_analysis.py, each
checked against hand-constructed data with a known answer."""
import math

import numpy as np
import pytest

import binner_analysis as ba


def test_plane_fit_recovers_known_gradient():
    rng = np.random.default_rng(1)
    placement = ba.placeholder_placement()
    xy = np.array([placement[f"R{i:02d}"] for i in range(16)])
    c, bx, by = 5.0, 0.01, -0.02
    lnf = c + bx * xy[:, 0] + by * xy[:, 1] + rng.normal(0, 1e-4, 16)
    beta, cov, resid, dof = ba.plane_fit(lnf, xy)
    assert beta == pytest.approx([c, bx, by], abs=5e-3)
    assert dof == 16 - 3


def test_reml_oneway_recovers_variance_components():
    rng = np.random.default_rng(2)
    sigma_a, sigma_e = 0.03, 0.008
    n_groups, n_per = 60, 16
    a = rng.normal(0, sigma_a, n_groups)
    groups = [a[i] + rng.normal(0, sigma_e, n_per) for i in range(n_groups)]
    sa, se, mu = ba.reml_oneway(groups)
    assert sa == pytest.approx(sigma_a, rel=0.25)
    assert se == pytest.approx(sigma_e, rel=0.25)


def test_reml_oneway_needs_at_least_two_groups():
    sa, se, mu = ba.reml_oneway([np.array([1.0, 2.0])])
    assert math.isnan(sa) and math.isnan(se)


def test_bootstrap_basic_properties():
    rng = np.random.default_rng(3)
    v = rng.normal(10, 1, 25)
    lo, hi, samples = ba.bootstrap(lambda idx: v[idx].mean(), len(v), B=500, rng=np.random.default_rng(0))
    assert lo < v.mean() < hi
    assert len(samples) <= 500

    # Degenerate case: fewer than 2 observations -> NaN, not a crash.
    lo, hi, samples = ba.bootstrap(lambda idx: v[idx].mean(), 1, B=100, rng=np.random.default_rng(0))
    assert math.isnan(lo) and math.isnan(hi)


def test_sd_chi2_ci_contains_true_sd_at_high_dof():
    # With many dof the chi-square CI for a sd should be narrow and centred near 1.
    lo, hi = ba.sd_chi2_ci(1.0, dof=500)
    assert lo < 1.0 < hi
    assert (hi - lo) < 0.2

    lo1, hi1 = ba.sd_chi2_ci(1.0, dof=5)
    assert (hi1 - lo1) > (hi - lo)  # low dof -> wider interval


def test_clopper_pearson_edges_and_monotonicity():
    lo0, hi0 = ba.clopper_pearson(0, 10)
    assert lo0 == 0.0 and hi0 < 1.0
    lo10, hi10 = ba.clopper_pearson(10, 10)
    assert hi10 == 1.0 and lo10 > 0.0
    lo5, hi5 = ba.clopper_pearson(5, 10)
    assert lo0 <= lo5 <= lo10
    assert hi0 <= hi10


def test_censored_fit_recovers_known_line():
    rng = np.random.default_rng(4)
    a_true, b_true = 0.9, 3.4   # ns, matching t_ov / t_stage order of magnitude
    n = np.array([3.0, 4, 5, 6, 8, 10, 12, 14])
    sig_ns = 0.02
    true_period = a_true + b_true * n
    # Simulate a PWM grid with a fine step so pass/fail intervals bracket the truth tightly.
    step = 0.01
    L = (np.floor(true_period / step) * step)
    U = L + step
    # _censored_fit takes L/U in seconds, sig in ns, and a0/b0 (initial guess) in SECONDS
    # (it rescales internally by 1e9 for numerical conditioning) -- mirrors chain_analysis's
    # own call, which feeds it WLS results already in seconds.
    a_fit, b_fit = ba._censored_fit(n, L * 1e-9, U * 1e-9, sig_ns, a_true * 1e-9, b_true * 1e-9)[0] * 1e9
    assert a_fit == pytest.approx(a_true, abs=0.05)
    assert b_fit == pytest.approx(b_true, abs=0.01)


def test_temp_factor_and_prior():
    model = ba.load_model()
    assert ba.temp_factor(model, 25.0) == pytest.approx(1.0)
    assert ba.temp_factor(model, 35.0) > 1.0
    T, sT = ba.temp_or_prior(model, float("nan"))
    lo, hi = model["temp_prior_C"]
    assert lo < T < hi
    assert sT > 0


def test_load_model_deep_merges_overrides(tmp_path):
    import json
    p = tmp_path / "model.json"
    p.write_text(json.dumps({"structures": {"INV": {"w_n": 0.6}}}), encoding="utf-8")
    m = ba.load_model(str(p))
    assert m["structures"]["INV"]["w_n"] == 0.6
    # Untouched siblings must survive the merge.
    assert m["structures"]["INV"]["w_p"] == ba.DEFAULT_MODEL["structures"]["INV"]["w_p"]
    assert m["structures"]["NAND"] == ba.DEFAULT_MODEL["structures"]["NAND"]


def test_load_placement_missing_file_falls_back_to_placeholder():
    p, is_ph, notes = ba.load_placement("does_not_exist.csv")
    assert is_ph
    assert notes
    assert set(ba.INV_ITEMS) <= set(p)


def test_load_placement_partial_file_fills_missing(tmp_path):
    p = tmp_path / "placement.csv"
    p.write_text("item,x_norm,y_norm\nR00,0.1,0.2\n", encoding="utf-8")
    placement, is_ph, notes = ba.load_placement(str(p))
    assert not is_ph
    assert placement["R00"] == (0.1, 0.2)
    assert "NAND" in placement  # backfilled from the placeholder
    assert any("missing" in n for n in notes)
