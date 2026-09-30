"""Can a cheaper model B replace a reference model A?

Both models are run on the SAME items, so the comparison is PAIRED: each item
contributes one (correct_a, correct_b, cost_a, cost_b) tuple, and the bootstrap
resamples whole items (both models' outcomes together). Pairing removes the
item-difficulty noise both models share, which makes the test far sharper than
comparing two independent accuracies.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .bounds import lower_bound, upper_bound

__all__ = ["compare_models"]

_CHUNK = 256  # bootstrap resamples drawn per batch (bounds memory use)


def _need_factor(point: float, bound: float, goal: float) -> float | None:
    """(current half-width / needed half-width)^2 for moving `bound` past `goal`.

    `point` is the estimate, `bound` the one-sided bound on the side facing
    `goal`. Returns 1.0 when the bound is already past the goal, None when the
    point sits exactly on the goal (no amount of data would settle it).
    """
    needed = abs(point - goal)
    current = abs(point - bound)
    if (bound - goal) * (point - goal) > 0:  # bound already on the same side as point
        return 1.0
    if needed == 0:
        return None
    return (current / needed) ** 2


def compare_models(pairs: Sequence[dict], margin: float = 0.02, alpha: float = 0.05,
                   n_boot: int = 2000, seed: int = 0, min_n: int = 30) -> dict:
    """Paired-bootstrap test of "B is no worse than A (within margin) and cheaper".

    ``pairs``: list of {item, correct_a, correct_b, cost_a, cost_b}, one per
    item, both models judged on that same item. Costs may be None; pairs with a
    missing cost are left out of the cost comparison only.

    PAIRED BOOTSTRAP: each of ``n_boot`` resamples draws n items with
    replacement, keeping each item's A and B outcomes together, and recomputes

      quality = acc_B - acc_A                      (fraction; *_pp fields x100)
      cost    = sum(cost_B) / sum(cost_A) - 1      (relative change, <0 = cheaper)

    One-sided (1 - alpha) bounds are the alpha and 1 - alpha percentiles. The
    quality interval is widened by a conservative exact matched-pair safeguard:
    simultaneous binomial bounds on B-only-right and A-only-right rates. This
    prevents a small sample with no observed disagreements from producing a
    zero-width quality interval.

    Verdict:
      "CERTIFY"      quality lower bound > -margin  AND  cost upper bound < 0
      "REJECT"       quality upper bound < -margin  OR   cost lower bound > 0
      "INSUFFICIENT" otherwise, or when n < min_n (the percentile bootstrap is
                     unreliable on tiny samples, e.g. it reports zero width if
                     the few items seen happen to agree). ``need_n`` then
                     estimates the extra items needed, roughly
                     n * (current half-width / needed half-width)^2.

    Returns a dict with the verdict, point estimates, bounds, and need_n.
    """
    n = len(pairs)
    a = np.array([bool(p["correct_a"]) for p in pairs], dtype=float)
    b = np.array([bool(p["correct_b"]) for p in pairs], dtype=float)
    has_cost = np.array([p.get("cost_a") is not None and p.get("cost_b") is not None for p in pairs], dtype=bool)
    ca = np.array([float(p["cost_a"]) if h else 0.0 for p, h in zip(pairs, has_cost)])
    cb = np.array([float(p["cost_b"]) if h else 0.0 for p, h in zip(pairs, has_cost)])
    cost_known = bool(has_cost.any()) and ca.sum() > 0

    out = {
        "verdict": "INSUFFICIENT", "n": n, "margin": margin, "alpha": alpha,
        "method": "paired bootstrap", "n_boot": n_boot,
        "quality_safeguard": "exact matched-pair bounds (Bonferroni)",
        "acc_a": None, "acc_b": None,
        "b_only_right": int(((b == 1) & (a == 0)).sum()),  # B fixes what A got wrong
        "a_only_right": int(((a == 1) & (b == 0)).sum()),  # B breaks what A got right
        "quality_pp": None, "quality_lo_pp": None, "quality_hi_pp": None,
        "cost_a": float(ca.sum()) if cost_known else None,
        "cost_b": float(cb.sum()) if cost_known else None,
        "cost_rel": None, "cost_lo": None, "cost_hi": None,
        "need_n": None, "reason": "",
    }
    if n == 0:
        out["need_n"] = min_n
        out["reason"] = "no paired items"
        return out

    out["acc_a"], out["acc_b"] = float(a.mean()), float(b.mean())
    d = b - a
    q_hat = float(d.mean())
    c_hat = float(cb.sum() / ca.sum() - 1.0) if cost_known else None

    # ---- paired bootstrap over items -----------------------------------
    rng = np.random.default_rng(seed)
    q_boot, c_boot = [], []
    done = 0
    while done < n_boot:
        m = min(_CHUNK, n_boot - done)
        idx = rng.integers(0, n, size=(m, n))  # same rows for A and B -> paired
        q_boot.append(d[idx].mean(axis=1))
        if cost_known:
            with np.errstate(divide="ignore", invalid="ignore"):
                c_boot.append(cb[idx].sum(axis=1) / ca[idx].sum(axis=1) - 1.0)
        done += m
    q_boot = np.concatenate(q_boot)
    q_boot_lo, q_boot_hi = (float(x) for x in np.quantile(q_boot, [alpha, 1.0 - alpha]))
    fixes = out["b_only_right"]
    breaks = out["a_only_right"]
    # q = P(B fixes A) - P(B breaks A). Bound both terms simultaneously,
    # spending alpha/2 on each side, then keep the wider of this exact interval
    # and the bootstrap interval. With zero disagreements this still expresses
    # uncertainty about disagreements that have not appeared in the sample.
    q_exact_lo = lower_bound(fixes, n, alpha / 2) - upper_bound(breaks, n, alpha / 2)
    q_exact_hi = upper_bound(fixes, n, alpha / 2) - lower_bound(breaks, n, alpha / 2)
    q_lo, q_hi = min(q_boot_lo, q_exact_lo), max(q_boot_hi, q_exact_hi)
    out.update(quality_pp=100 * q_hat, quality_lo_pp=100 * q_lo, quality_hi_pp=100 * q_hi)
    if cost_known:
        c_boot = np.concatenate(c_boot)
        c_boot = c_boot[np.isfinite(c_boot)]
        c_lo, c_hi = (float(x) for x in np.quantile(c_boot, [alpha, 1.0 - alpha]))
        out.update(cost_rel=c_hat, cost_lo=c_lo, cost_hi=c_hi)

    # ---- verdict --------------------------------------------------------
    quality_ok = q_lo > -margin
    quality_bad = q_hi < -margin
    cost_ok = cost_known and c_hi < 0
    cost_bad = cost_known and c_lo > 0

    if n < min_n:
        out["reason"] = f"only {n} items; need at least {min_n} before deciding"
    elif quality_bad or cost_bad:
        out["verdict"] = "REJECT"
        out["reason"] = "worse than the reference beyond the margin" if quality_bad else "more expensive"
        return out
    elif quality_ok and cost_ok:
        out["verdict"] = "CERTIFY"
        out["reason"] = "no worse than the reference (within margin) and cheaper"
        return out
    else:
        out["reason"] = "intervals too wide to decide"

    # ---- how much more data? -------------------------------------------
    # Aim for whichever verdict the point estimates point to.
    if q_hat > -margin and (c_hat is not None and c_hat < 0):
        fq = _need_factor(q_hat, q_lo, -margin)
        fc = _need_factor(c_hat, c_hi, 0.0)
        factor = None if fq is None or fc is None else max(fq, fc)  # need both
    else:
        cands = []
        if q_hat < -margin:
            cands.append(_need_factor(q_hat, q_hi, -margin))
        if c_hat is not None and c_hat > 0:
            cands.append(_need_factor(c_hat, c_lo, 0.0))
        cands = [f for f in cands if f is not None]
        factor = min(cands) if cands else None  # either one suffices
    if factor is not None:
        extra = max(0, math.ceil(n * factor) - n)
        out["need_n"] = max(extra, min_n - n, 1)
    elif n < min_n:
        out["need_n"] = min_n - n
    return out
