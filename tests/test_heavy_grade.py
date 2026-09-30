"""Grading against the maintainers' record: every rule, including the conservative ones."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("heavy_grade", Path(__file__).resolve().parents[1] / "scripts" / "heavy_grade.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)


def t(key, parent=None, resolution=None):
    return {"key": key, "parent": parent, "resolution": resolution, "summary": key}


TICKETS = {k: v for k, v in [
    ("SPARK-1", t("SPARK-1")), ("SPARK-2", t("SPARK-2", resolution="Duplicate")), ("SPARK-3", t("SPARK-3", resolution="Fixed")),
    ("SPARK-4", t("SPARK-4", parent="SPARK-1")), ("SPARK-5", t("SPARK-5", parent="SPARK-1")), ("SPARK-6", t("SPARK-6", resolution="Duplicate")),
    ("KAFKA-1", t("KAFKA-1")), ("SPARK-7", t("SPARK-7", resolution="Resolved")), ("SPARK-8", t("SPARK-8"))]}
TRUTH = [{"src": "SPARK-2", "dst": "SPARK-1", "relation": "duplicate"}, {"src": "SPARK-6", "dst": "SPARK-8", "relation": "duplicate"},
         {"src": "SPARK-3", "dst": "SPARK-1", "relation": "related"}]
T = G.Truth(TICKETS, TRUTH)


def test_duplicate_rules():
    assert T.grade("SPARK-2", "SPARK-1", "duplicate")[0] == "confirmed"          # maintainers linked them
    assert T.grade("SPARK-6", "KAFKA-1", "duplicate")[0] == "contradicted"       # another project
    assert T.grade("SPARK-4", "SPARK-1", "duplicate")[0] == "contradicted"       # it's the parent
    assert T.grade("SPARK-3", "SPARK-1", "duplicate")[0] == "contradicted"       # linked as related instead
    assert T.grade("SPARK-6", "SPARK-1", "duplicate")[0] == "contradicted"       # duplicate of SPARK-8 instead
    assert T.grade("SPARK-4", "SPARK-5", "duplicate")[0] == "contradicted"       # siblings
    assert T.grade("SPARK-3", "SPARK-6", "duplicate")[0] == "contradicted"       # fixed on its own
    assert T.grade("SPARK-7", "SPARK-6", "duplicate")[0] == "unlinked"           # "Resolved" is too vague to decide
    assert T.grade("SPARK-1", "SPARK-8", "duplicate")[0] == "unlinked"           # no record (being an original proves nothing)


def test_part_of_and_related_rules():
    assert T.grade("SPARK-4", "SPARK-1", "part_of")[0] == "confirmed"
    assert T.grade("SPARK-4", "SPARK-6", "part_of")[0] == "contradicted"         # its parent is another ticket
    assert T.grade("SPARK-1", "SPARK-8", "part_of")[0] == "unlinked"
    assert T.grade("SPARK-4", "SPARK-5", "related")[0] == "confirmed"            # same parent
    assert T.grade("SPARK-1", "SPARK-8", "related")[0] == "unlinked"


def test_one_action_per_ticket_is_the_most_confident_link():
    js = [{"candidate": "A", "relation": "related", "confidence": 0.7}, {"candidate": "B", "relation": "none", "confidence": 0.99},
          {"candidate": "C", "relation": "duplicate", "confidence": 0.9}]
    assert G.action(js)["candidate"] == "C"
    assert G.action([{"candidate": "A", "relation": "none", "confidence": 1.0}]) is None


def test_precision_counts_unlinked_as_wrong_when_strict():
    p = G.prec([{"grade": "confirmed"}, {"grade": "contradicted"}, {"grade": "unlinked"}, {"grade": "confirmed"}])
    assert (p["strict"], p["decided"], p["optimistic"]) == (0.5, 2 / 3, 0.75)
