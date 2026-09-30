"""Tests for assay_engine. Fast (a few seconds) and deterministic (fixed seeds)."""
import numpy as np
import pytest
from scipy import stats

from assay_engine import (
    auto_threshold,
    auto_threshold_by_relation,
    clopper_pearson_interval,
    compare_models,
    extra_needed,
    gate_change,
    lower_bound,
    precision_bands,
    precision_bands_by_relation,
    report,
    upper_bound,
    wilson_interval,
)


# --------------------------------------------------------------------------- helpers
def judg(conf, correct, relation="duplicate"):
    return {"relation": relation, "confidence": float(conf), "correct": bool(correct)}


def block(n, lo, hi, n_correct, relation="duplicate"):
    """n judgments with confidences evenly spread in [lo, hi) and n_correct of
    them correct, the mistakes spread evenly through the block."""
    confs = np.linspace(lo, hi, n, endpoint=False)
    return [judg(c, (i + 1) * n_correct // n > i * n_correct // n, relation) for i, c in enumerate(confs)]


def simulate(rng, n, precision, relation="duplicate"):
    conf = rng.uniform(0.3, 1.0, n)
    ok = rng.random(n) < precision
    return [judg(c, o, relation) for c, o in zip(conf, ok)]


def make_pairs(rng, n, acc_a, acc_b, cost_a=1.0, cost_b=0.4, share=0.8):
    """Paired outcomes: with prob `share` both models see the same item difficulty."""
    pairs = []
    for i in range(n):
        u = rng.random()
        a = u < acc_a
        b = (u < acc_b) if rng.random() < share else (rng.random() < acc_b)
        pairs.append({"item": i, "correct_a": a, "correct_b": b,
                      "cost_a": cost_a * rng.uniform(0.8, 1.2), "cost_b": cost_b * rng.uniform(0.8, 1.2)})
    return pairs


# --------------------------------------------------------------------------- bounds
def test_wilson_known_value():
    lo, hi = wilson_interval(10, 20)
    assert lo == pytest.approx(0.2993, abs=1e-4)
    assert hi == pytest.approx(0.7007, abs=1e-4)


def test_clopper_pearson_known_values():
    lo, hi = clopper_pearson_interval(5, 10)
    assert lo == pytest.approx(0.1871, abs=1e-4)
    assert hi == pytest.approx(0.8129, abs=1e-4)
    # 0/10 and 10/10 have closed forms: 1 - (a/2)^(1/n) and (a/2)^(1/n).
    assert clopper_pearson_interval(0, 10) == pytest.approx((0.0, 1 - 0.025 ** 0.1))
    assert clopper_pearson_interval(10, 10) == pytest.approx((0.025 ** 0.1, 1.0))


def test_clopper_pearson_inverts_binomial_test():
    k, n = 37, 50
    lo, hi = clopper_pearson_interval(k, n, alpha=0.1)
    assert stats.binom.sf(k - 1, n, lo) == pytest.approx(0.05, abs=1e-9)  # P(X >= k | lo)
    assert stats.binom.cdf(k, n, hi) == pytest.approx(0.05, abs=1e-9)     # P(X <= k | hi)


def test_one_sided_bounds():
    # Perfect record: CP one-sided lower bound is alpha^(1/n).
    assert lower_bound(59, 59) == pytest.approx(0.05 ** (1 / 59))
    assert lower_bound(59, 59) >= 0.95 > lower_bound(58, 58)
    assert upper_bound(0, 30) == pytest.approx(1 - 0.05 ** (1 / 30))
    # One-sided at alpha equals the two-sided limit at 2 * alpha.
    assert lower_bound(40, 50, alpha=0.05) == pytest.approx(clopper_pearson_interval(40, 50, alpha=0.10)[0])
    assert lower_bound(40, 50, 0.05, "wilson") == pytest.approx(wilson_interval(40, 50, alpha=0.10)[0])


def test_empty_sample():
    assert wilson_interval(0, 0) == (0.0, 1.0)
    assert clopper_pearson_interval(0, 0) == (0.0, 1.0)
    assert lower_bound(0, 0) == 0.0 and upper_bound(0, 0) == 1.0
    with pytest.raises(ValueError):
        lower_bound(5, 3)


@pytest.mark.parametrize("method", ["cp", "wilson"])
def test_bounds_monotone(method):
    n = 100
    lows = [lower_bound(k, n, method=method) for k in range(n + 1)]
    ups = [upper_bound(k, n, method=method) for k in range(n + 1)]
    assert all(np.diff(lows) > 0) and all(np.diff(ups) > 0)
    for k in range(n + 1):  # bounds bracket the point estimate
        assert lows[k] <= k / n <= ups[k]
    # Same observed precision, more data -> tighter bounds.
    by_n = [lower_bound(0.9 * m, m, method=method) for m in (10, 50, 100, 500, 2000)]
    assert all(np.diff(by_n) > 0)
    # Smaller alpha (more confidence) -> lower lower-bound.
    assert lower_bound(90, 100, 0.01, method) < lower_bound(90, 100, 0.05, method) < lower_bound(90, 100, 0.2, method)
    # CP is the conservative one.
    assert lower_bound(90, 100) < lower_bound(90, 100, method="wilson")


# --------------------------------------------------------------------------- bands
def synthetic_three_bands():
    # High confidence: 200 items, 199 right  -> clearly >= 95% -> auto
    # Middle:          100 items, 70 right   -> useful but not proven -> suggest
    # Low:             100 items, 30 right   -> below the 50% floor -> silent
    return block(100, 0.30, 0.55, 30) + block(100, 0.55, 0.85, 70) + block(200, 0.85, 1.0, 199)


def test_band_actions_fixed_edges():
    bands = precision_bands(synthetic_three_bands(), edges=[0.3, 0.55, 0.85, 1.0])
    assert [b["n"] for b in bands] == [100, 100, 200]
    assert [b["action"] for b in bands] == ["silent", "suggest", "auto"]
    assert bands[2]["precision"] == pytest.approx(0.995)
    assert bands[2]["lower"] >= 0.95 and bands[2]["need_n"] == 0
    assert bands[0]["need_n"] is None and bands[1]["need_n"] is None  # precision < target


def test_band_default_fixed_edges_and_empty_band():
    js = block(100, 0.72, 0.84, 95) + [judg(0.2, True)]  # 0.2 is below the first edge
    bands = precision_bands(js, edges=[0.5, 0.7, 0.85, 0.95, 1.0])
    assert [b["n"] for b in bands] == [0, 100, 0, 0]
    assert bands[0]["precision"] is None and bands[0]["action"] == "silent"
    assert bands[1]["action"] == "suggest"


def test_band_quantile_edges():
    js = synthetic_three_bands()
    bands = precision_bands(js)
    assert len(bands) == 5
    assert sum(b["n"] for b in bands) == len(js)
    assert all(b["n"] >= 20 for b in bands)
    assert bands[-1]["action"] == "auto" and bands[0]["action"] == "silent"
    # Too little data for 5 bands of 20 -> fewer bands.
    assert len(precision_bands(js[:45])) == 2


def test_bands_skip_none_and_unlabelled():
    js = block(100, 0.9, 1.0, 100)
    js += [{"relation": "none", "confidence": 0.99, "correct": False},
           {"relation": "duplicate", "confidence": 0.99, "correct": None}]
    bands = precision_bands(js, edges=[0.0, 1.0])
    assert bands[0]["n"] == 100 and bands[0]["action"] == "auto"


def test_need_n():
    # 98% observed on 50 items: not proven yet, but will be with more.
    extra = extra_needed(49, 50, 0.95)
    assert extra is not None and extra > 0
    N = 50 + extra
    assert lower_bound(0.98 * N, N) >= 0.95 > lower_bound(0.98 * (N - 1), N - 1)
    assert extra_needed(58, 58, 0.95) == 1  # a perfect record needs 59
    assert extra_needed(90, 100, 0.95) is None
    assert extra_needed(199, 200, 0.95) == 0


def test_block_helper():
    js = block(10, 0.0, 1.0, 7)
    assert sum(j["correct"] for j in js) == 7


def test_auto_threshold_finds_cutoff():
    res = auto_threshold(synthetic_three_bands())
    assert res is not None
    # Cumulative: the 99.5% band can carry a slice of the 70% band below it,
    # but not much of it.
    assert 0.75 < res["threshold"] <= 0.85
    assert res["lower"] >= 0.95
    assert res["n"] >= 200
    assert res["threshold"] == min(j["confidence"] for j in synthetic_three_bands()
                                   if j["confidence"] >= res["threshold"])
    # Everything at or above the threshold really does pass.
    js = [j for j in synthetic_three_bands() if j["confidence"] >= res["threshold"]]
    k = sum(j["correct"] for j in js)
    # Reported bound is at alpha / 2: alpha is split over the two default walks.
    assert lower_bound(k, len(js), alpha=0.025) == pytest.approx(res["lower"])
    assert (k, len(js)) == (res["k"], res["n"])


def test_auto_threshold_none_when_nothing_qualifies():
    rng = np.random.default_rng(1)
    assert auto_threshold(simulate(rng, 500, 0.80)) is None
    assert auto_threshold(block(58, 0.9, 1.0, 58)) is None  # perfect, but too few to prove 95%
    assert auto_threshold([]) is None


def test_auto_threshold_robust_to_one_confident_mistake():
    # 400 items at 99%+, but the single most confident prediction is wrong.
    js = block(400, 0.5, 0.99, 398) + [judg(0.999, False)]
    assert auto_threshold(js, tolerate=(0,)) is None  # the plain walk dies at once
    res = auto_threshold(js)  # default also starts a walk that tolerates a few mistakes
    assert res is not None and res["threshold"] < 0.6


def test_auto_threshold_sequential_vs_scan():
    # The scan mode may only ever find a cutoff at or below the sequential one.
    rng = np.random.default_rng(3)
    for _ in range(20):
        js = [judg(c, rng.random() < 0.6 + 0.4 * c) for c in rng.uniform(0, 1, 800)]
        seq, scan = auto_threshold(js, tolerate=(0,)), auto_threshold(js, sequential=False)
        if seq is not None:
            assert scan is not None and scan["threshold"] <= seq["threshold"]


def test_by_relation():
    js = block(200, 0.8, 1.0, 199, "duplicate") + block(200, 0.8, 1.0, 150, "related")
    th = auto_threshold_by_relation(js)
    assert th["duplicate"] is not None and th["related"] is None and th["part_of"] is None
    bands = precision_bands_by_relation(js, edges=[0.8, 1.0])
    assert bands["duplicate"][0]["action"] == "auto"
    assert bands["related"][0]["action"] == "suggest"
    assert bands["part_of"][0]["n"] == 0


def test_calibration_false_auto_rate():
    """True precision = target - 3 points: 'auto' must be declared <= ~5% of the time."""
    rng = np.random.default_rng(2026)
    target, trials = 0.95, 300
    thr_hits = band_hits = 0
    for _ in range(trials):
        js = simulate(rng, 300, target - 0.03)
        thr_hits += auto_threshold(js, target=target) is not None
        band_hits += precision_bands(js, target=target, edges=[0.0, 1.0])[0]["action"] == "auto"
    assert thr_hits / trials <= 0.05
    assert band_hits / trials <= 0.05


def test_calibration_power_when_truly_good():
    """The flip side: at 99% true precision with 300 items, auto is usually found."""
    rng = np.random.default_rng(7)
    hits = sum(auto_threshold(simulate(rng, 300, 0.99)) is not None for _ in range(100))
    assert hits >= 80


# --------------------------------------------------------------------------- compare
def test_compare_certifies_equal_cheaper_model():
    rng = np.random.default_rng(0)
    res = compare_models(make_pairs(rng, 3000, 0.8, 0.8))
    assert res["verdict"] == "CERTIFY", res
    assert res["quality_lo_pp"] > -2.0
    assert res["cost_hi"] < 0 and res["cost_rel"] == pytest.approx(-0.6, abs=0.03)
    assert res["method"] == "paired bootstrap"


def test_compare_rejects_worse_model():
    rng = np.random.default_rng(1)
    res = compare_models(make_pairs(rng, 1000, 0.8, 0.7))
    assert res["verdict"] == "REJECT"
    assert res["quality_hi_pp"] < -2.0
    assert res["quality_pp"] == pytest.approx(100 * (res["acc_b"] - res["acc_a"]))


def test_compare_rejects_more_expensive_model():
    rng = np.random.default_rng(2)
    res = compare_models(make_pairs(rng, 1000, 0.8, 0.8, cost_a=1.0, cost_b=1.5))
    assert res["verdict"] == "REJECT" and res["cost_lo"] > 0


def test_compare_insufficient_at_small_n():
    rng = np.random.default_rng(3)
    res = compare_models(make_pairs(rng, 60, 0.8, 0.8, share=0.3))
    assert res["verdict"] == "INSUFFICIENT"
    assert res["need_n"] is not None and res["need_n"] > 0
    tiny = compare_models(make_pairs(rng, 10, 0.8, 0.8))
    assert tiny["verdict"] == "INSUFFICIENT" and tiny["need_n"] >= 20
    assert compare_models([])["verdict"] == "INSUFFICIENT"


def test_compare_is_paired_and_deterministic():
    rng = np.random.default_rng(4)
    pairs = make_pairs(rng, 400, 0.8, 0.8)
    assert compare_models(pairs, seed=5) == compare_models(pairs, seed=5)
    # A percentile bootstrap alone gives a false zero-width interval here. The
    # exact matched-pair safeguard keeps uncertainty about unseen disagreements.
    same = [dict(p, correct_b=p["correct_a"]) for p in pairs]
    res = compare_models(same)
    assert res["quality_lo_pp"] < 0 < res["quality_hi_pp"]
    assert res["quality_safeguard"] == "exact matched-pair bounds (Bonferroni)"


def test_compare_does_not_certify_small_identical_sample():
    pairs = [{"item": i, "correct_a": True, "correct_b": True, "cost_a": 1.0, "cost_b": .4}
             for i in range(30)]
    res = compare_models(pairs)
    assert res["verdict"] == "INSUFFICIENT"
    assert res["quality_lo_pp"] < -2.0 < res["quality_hi_pp"]
    assert res["need_n"] and res["need_n"] > 0


# --------------------------------------------------------------------------- gate
def test_gate_counts_and_keep():
    before = [True] * 150 + [False] * 50
    after = before.copy()
    for i in range(150, 161):  # 11 fixes, no breaks
        after[i] = True
    res = gate_change(before, after)
    assert (res["fixed"], res["broke"]) == (11, 0)
    assert res["verdict"] == "KEEP"
    assert res["delta"] == pytest.approx(11 / 200)
    assert res["acc_before"] == 0.75 and res["acc_after"] == pytest.approx(0.805)
    assert "fixes 11, breaks 0" in report.describe_gate(res)


def test_gate_mixed_counts_and_items():
    before = {"A-1": True, "A-2": False, "A-3": False, "A-4": True, "A-5": True}
    after = [{"item": "A-1", "correct": False}, {"item": "A-2", "correct": True},
             {"item": "A-3", "correct": True}, {"item": "A-4", "correct": True},
             {"item": "A-9", "correct": True}]  # A-9 not in before: ignored; A-5 not in after: ignored
    res = gate_change(before, after)
    assert res["n"] == 4
    assert (res["fixed"], res["broke"]) == (2, 1)
    assert res["fixed_items"] == ["A-2", "A-3"] and res["broke_items"] == ["A-1"]
    assert res["verdict"] == "UNPROVEN"


def test_gate_discard_and_unproven():
    before = [True] * 150 + [False] * 50
    worse = before.copy()
    for i in range(12):
        worse[i] = False
    res = gate_change(before, worse)
    assert res["verdict"] == "DISCARD" and res["broke"] == 12 and res["upper"] < 0
    same = gate_change(before, before)
    assert same["verdict"] == "UNPROVEN" and same["fixed"] == same["broke"] == 0
    assert same["need_n"] is None
    slight = before.copy()
    slight[150] = slight[151] = True
    slight[0] = False
    res = gate_change(before, slight)
    assert res["verdict"] == "UNPROVEN" and res["need_n"] > 0
    with pytest.raises(ValueError):
        gate_change([True, False], [True])


def test_gate_margin():
    before = [False] * 20 + [True] * 180
    after = [True] * 200  # 20 fixes: +10 pp
    assert gate_change(before, after)["verdict"] == "KEEP"
    assert gate_change(before, after, margin=0.10)["verdict"] == "UNPROVEN"


# --------------------------------------------------------------------------- report
def test_report_strings():
    res = {"threshold": 0.91, "n": 214, "k": 208, "precision": 208 / 214, "lower": 0.951}
    assert report.describe_threshold(res) == (
        "Auto-act at confidence ≥ 0.91: precision 97.2% (proven ≥ 95.1%, n=214)")
    assert "No confidence level" in report.describe_threshold(None)
    bands = precision_bands(synthetic_three_bands(), edges=[0.3, 0.55, 0.85, 1.0])
    table = report.bands_table(bands)
    assert table.count("\n") == 4 and "auto" in table and "silent" in table
    assert "→ auto" in report.describe_band(bands[2])
    js = synthetic_three_bands()
    assert "relation" in report.bands_table(precision_bands_by_relation(js, edges=[0.3, 1.0]))
    assert "none proven" in report.thresholds_table(auto_threshold_by_relation(js))
    rng = np.random.default_rng(0)
    cmp = compare_models(make_pairs(rng, 500, 0.8, 0.8))
    assert report.describe_compare(cmp).startswith(cmp["verdict"])
    assert "**" + cmp["verdict"] + "**" in report.compare_table(cmp)
    assert "fixes (wrong → right)" in report.gate_table(gate_change([False, True], [True, True]))
