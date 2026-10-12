"""Independent finite controls for native Rhea identity and finalizer transport."""

import csv
import io

from kg_microbe.utils.source_finalization import _stage_representation
from tests.test_rhea_native_inputs import FIXTURE
from tests.test_rhea_native_transform import _producer, _replace_native, _rows


def test_full_native_entity_names_and_polymer_index_are_not_character_iterators(tmp_path, monkeypatch):
    """Singleton metadata strings must survive as whole strings, not their first character."""
    producer, _, _ = _producer(tmp_path, monkeypatch)
    producer.run(show_status=False)
    nodes = {row["id"]: row for row in _rows(producer.output_node_file)}
    assert nodes["rheav:Polymer_2"]["name"] == "fixture polymer (n+1)"
    assert nodes["rheav:Polymer_2"]["rhea_polymerization_index"] == "n+1"
    assert nodes["rheav:Generic_3"]["name"] == "fixture whole compound"
    assert nodes["rheav:ReactivePart_3a"]["name"] == "fixture water moiety"


def test_literal_quotes_survive_real_producer_and_finalizer_dialect(tmp_path, monkeypatch):
    """The declared producer TSV dialect must match its literal canonical output."""
    producer, policy_path, policy = _producer(tmp_path, monkeypatch)
    xml = FIXTURE.read_bytes().replace(b"fixture master", b"&quot;quoted master&quot;")
    _replace_native(producer, policy_path, policy, xml)
    producer.run(show_status=False)
    staged = tmp_path / "staged_nodes.tsv"
    _stage_representation(
        producer.output_node_file,
        staged,
        True,
        getattr(producer, "TSV_QUOTING", csv.QUOTE_MINIMAL),
        tmp_path / "unused-foodon.json",
        csv.DictWriter(io.StringIO(), fieldnames=()),
        set(),
        set(),
    )
    nodes = {row["id"]: row for row in _rows(staged)}
    assert nodes["RHEA:100"]["name"] == '"quoted master"'


def test_same_terminal_chemical_different_native_participants_stay_distinct(tmp_path, monkeypatch):
    """A second same-side participant cannot disappear in full-row edge deduplication."""
    producer, policy_path, policy = _producer(tmp_path, monkeypatch)
    extra = (
        b'<rdf:Description rdf:about="http://rdf.rhea-db.org/100_L">'
        b'<rh:contains rdf:resource="http://rdf.rhea-db.org/Participant_5"/></rdf:Description>'
        b'<rdf:Description rdf:about="http://rdf.rhea-db.org/Participant_5">'
        b'<rh:compound rdf:resource="http://rdf.rhea-db.org/Compound_1"/></rdf:Description>'
    )
    _replace_native(producer, policy_path, policy, FIXTURE.read_bytes().replace(b"</rdf:RDF>", extra + b"</rdf:RDF>"))
    producer.run(show_status=False)
    selected = [
        row
        for row in _rows(producer.output_edge_file)
        if row["subject"] == "RHEA:101" and row["predicate"] == "biolink:has_input" and row["object"] == "CHEBI:15377"
    ]
    assert len(selected) == 2
    assert {row["rhea_participant"] for row in selected} == {"rheav:Participant_1", "rheav:Participant_5"}
    assert {row["rhea_side"] for row in selected} == {"rheav:100_L"}
    assert {row["rhea_participant_route"] for row in selected} == {"direct_chebi"}
