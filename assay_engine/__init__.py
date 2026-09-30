"""assay_engine: the statistics behind Assay Triage.

The agent acts on its own only where its precision is PROVEN (a one-sided
lower confidence bound clears the target), and keeps learned changes only
when they provably help. Pure stdlib + numpy + scipy.

    bounds   Wilson / Clopper-Pearson intervals and one-sided bounds
    bands    per-confidence-band precision and the auto-act threshold
    compare  paired test: can a cheaper model replace the reference?
    gate     paired test: does a learned change help? (fixes vs breaks)
    report   short human strings and markdown tables
"""
from .bands import (
    RELATIONS,
    auto_threshold,
    auto_threshold_by_relation,
    extra_needed,
    precision_bands,
    precision_bands_by_relation,
)
from .bounds import (
    clopper_pearson_interval,
    lower_bound,
    proportion_interval,
    upper_bound,
    wilson_interval,
)
from .compare import compare_models
from .gate import gate_change
from .learning import build_gate
from .permissions import build_receipt, can_act, validate_receipt
from .policy import label_template, scored_actions, select_action
from . import report

__all__ = [
    "RELATIONS",
    "auto_threshold", "auto_threshold_by_relation", "extra_needed",
    "precision_bands", "precision_bands_by_relation",
    "clopper_pearson_interval", "wilson_interval", "lower_bound", "upper_bound", "proportion_interval",
    "compare_models", "gate_change", "build_gate", "build_receipt", "can_act", "validate_receipt",
    "label_template", "scored_actions", "select_action", "report",
]
