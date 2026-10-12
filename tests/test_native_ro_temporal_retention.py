"""The approved temporal extension is finite, directional and does not revise the first184."""

from collections import Counter

import pandas as pd
import pytest

from kg_microbe.utils import native_ro_retention as native
from tests.test_native_ro_retention import POLICY, audit_rows, frame, prepare

TEMPORAL = {
    "RO:0002488": 22,
    "RO:0002489": 10,
    "RO:0002492": 54,
    "RO:0002493": 8,
    "RO:0002496": 2,
    "RO:0002497": 2,
    "RO:0002285": 10,
}


def test_extension_preserves_original184_and_exact108_directional_records():
    """Prevent newly approved scope from silently expanding or rewriting old records."""
    original_suppliers = [row for row in POLICY["records"] if row["ontology"] in {"pato", "uberon"}]
    original = [row for row in original_suppliers if row["relation"] in {"RO:0002216", "RO:0002503"}]
    assert len(original) == 184
    assert native._digest(native._json(original).encode()) == (
        "c492804662084db957c0ccdb145378e343e7ef52b3b7658e0ba48fb81d540e45"
    )
    temporal = [row for row in original_suppliers if row["relation"] in TEMPORAL]
    assert Counter(row["relation"] for row in temporal) == TEMPORAL
    assert Counter(row["ontology"] for row in temporal) == {"pato": 37, "uberon": 71}
    assert len({(row["subject"], row["relation"], row["object"]) for row in temporal}) == 71


@pytest.mark.parametrize("relation", TEMPORAL)
def test_reversing_one_temporal_assertion_refuses_before_audit(tmp_path, monkeypatch, relation):
    """Even ambiguous upstream prose does not authorize silently reversing its asserted edge."""
    _, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    rows = frame("pato")
    index = rows.index[rows["relation"] == relation][0]
    subject, obj = rows.loc[index, ["subject", "object"]]
    assert subject != obj
    rows.loc[index, ["subject", "object"]] = [obj, subject]
    with pytest.raises(ValueError, match="cohort"):
        authority.project("pato", rows, rows, "pato_edges.tsv")
    assert not audit_rows(audit)


@pytest.mark.parametrize("relation", ["BFO:0000062", "RO:0000056"])
def test_unapproved_temporal_and_participant_relations_remain_untouched(tmp_path, monkeypatch, relation):
    """Do not turn finite retention into a blanket native-predicate policy."""
    _, authority, audit = prepare(tmp_path, monkeypatch, sources=("pato",))
    rows = frame("pato")
    rows.loc[rows.index[-1], "relation"] = relation
    previous = rows.copy()
    result = authority.project("pato", rows, rows, "pato_edges.tsv")
    pd.testing.assert_series_equal(result.iloc[-1], previous.iloc[-1])
    assert len(audit_rows(audit)) == 74
    assert all(row["strict_biolink_disposition"] == native.STRICT_DISPOSITION for row in audit_rows(audit))
