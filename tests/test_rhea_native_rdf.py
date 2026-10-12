"""Exercise local streaming Rhea XML selection without PyOBO or native cache reads."""

import gzip
import io
from pathlib import Path

import pytest

from kg_microbe.transform_utils.rhea_mappings.native_rdf import (
    RH,
    NativeRheaError,
    load_native_rdf,
)

FIXTURE = Path(__file__).parent / "resources/rhea/native-small.rdf"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def test_split_descriptions_union_reaction_and_side_fields():
    """Preserve all explicitly declared family links without deriving them from IDs."""
    index = load_native_rdf(FIXTURE)
    assert set(index.reactions) == {"RHEA:100", "RHEA:101", "RHEA:102", "RHEA:103"}
    master = index.reactions["RHEA:100"]
    assert master[LABEL] == ("fixture master",)
    assert master[RH + "equation"] == ("left = right",)
    assert master[RH + "status"] == (RH + "Approved",)
    assert master[RH + "ec"] == ("http://purl.uniprot.org/enzyme/1.2.3.4",)
    assert master["http://www.w3.org/2000/01/rdf-schema#seeAlso"] == ("http://purl.obolibrary.org/obo/GO_0000001",)
    assert master[RH + "citation"] == (RH + "citations/12345",)
    assert master[RH + "directionalReaction"] == (RH + "101", RH + "102")
    assert master[RH + "bidirectionalReaction"] == (RH + "103",)
    assert master[RH + "side"] == (RH + "100_L", RH + "100_R")
    assert index.reactions["RHEA:101"][TYPE] == (RH + "DirectionalReaction",)
    assert index.reactions["RHEA:102"][RH + "substrates"] == (RH + "100_R",)
    assert index.sides[RH + "100_L"] == (RH + "Participant_1", RH + "Participant_2")


def test_direct_polymer_and_each_reactive_part_keep_distinct_route_evidence():
    """A generic reactive part is evidence about that part, not whole-compound identity."""
    index = load_native_rdf(FIXTURE)
    left = index.chemical_participants(RH + "100_L")
    assert [(item.chebi_id, item.route) for item in left] == [
        ("CHEBI:15377", "direct_chebi"),
        ("CHEBI:27732", "underlying_chebi"),
    ]
    right = index.chemical_participants(RH + "100_R")
    assert [(item.chebi_id, item.route) for item in right] == [
        ("CHEBI:15377", "reactive_part_chebi"),
        ("CHEBI:15378", "reactive_part_chebi"),
        ("CHEBI:15377", "direct_chebi"),
    ]
    assert right[0].compound_iri == RH + "Generic_3"
    assert right[0].reactive_part_iri == RH + "ReactivePart_3a"
    assert right[0].participant_iri == RH + "Participant_3"
    assert right[0].side_iri == RH + "100_R"
    assert right[2].reactive_part_iri is None


def test_native_compound_and_part_metadata_preserve_distinct_source_meanings():
    """Keep literal whole-compound, part and polymer names without inventing identity."""
    index = load_native_rdf(FIXTURE)
    assert index.entity_metadata[RH + "Compound_1"] == {RH + "name": "water", LABEL: "native water label"}
    assert index.entity_metadata[RH + "Polymer_2"] == {
        RH + "name": "fixture polymer (n+1)",
        RH + "polymerizationIndex": "n+1",
    }
    assert index.entity_metadata[RH + "Generic_3"] == {RH + "name": "fixture whole compound"}
    assert index.entity_metadata[RH + "ReactivePart_3a"] == {RH + "name": "fixture water moiety"}
    assert index.entity_metadata[RH + "ReactivePart_3b"] == {RH + "name": "fixture proton moiety"}
    assert RH + "Participant_1" not in index.entity_metadata


@pytest.mark.parametrize(
    "original,replacement",
    [
        ("<rh:name>water</rh:name>", "<rh:name>other compound</rh:name>"),
        ("<rdfs:label>native water label</rdfs:label>", "<rdfs:label>other label</rdfs:label>"),
        (
            "<rh:polymerizationIndex>n+1</rh:polymerizationIndex>",
            "<rh:polymerizationIndex>n-1</rh:polymerizationIndex>",
        ),
    ],
)
def test_ambiguous_native_entity_metadata_fails(tmp_path, original, replacement):
    """Do not select an arbitrary name or polymer index from competing native values."""
    path = tmp_path / "ambiguous-entity-metadata.rdf"
    path.write_text(FIXTURE.read_text().replace(original, original + replacement))
    with pytest.raises(NativeRheaError, match="Ambiguous.*metadata"):
        load_native_rdf(path)


def test_optional_entity_metadata_and_split_descriptions_do_not_change_routes(tmp_path):
    """Missing names remain absent, and split identical metadata remains set-equivalent."""
    path = tmp_path / "optional-metadata.rdf"
    duplicate = (
        '<rdf:Description rdf:about="http://rdf.rhea-db.org/Polymer_2">'
        "<rh:polymerizationIndex>n+1</rh:polymerizationIndex></rdf:Description>"
    )
    path.write_text(
        FIXTURE.read_text()
        .replace("<rh:name>fixture whole compound</rh:name>", "")
        .replace("</rdf:RDF>", duplicate + "</rdf:RDF>")
    )
    index, original = load_native_rdf(path), load_native_rdf(FIXTURE)
    assert index.entity_metadata.get(RH + "Generic_3", {}) == {}
    assert index.entity_metadata[RH + "Polymer_2"] == original.entity_metadata[RH + "Polymer_2"]
    assert index.chemical_participants(RH + "100_R") == original.chemical_participants(RH + "100_R")


@pytest.mark.parametrize("compressed", [False, True])
def test_caller_owned_binary_stream_remains_open(compressed):
    """Consume local snapshot buffers without closing the owner's read-bound handle."""
    payload = FIXTURE.read_bytes()
    stream = io.BytesIO(gzip.compress(payload) if compressed else payload)
    index = load_native_rdf(stream, compressed=compressed)
    assert len(index.reactions) == 4
    assert not stream.closed
    assert stream.read() == b""


def test_compressed_local_path_is_inferred(tmp_path):
    """A local .rdf.gz path uses the same streaming parser as its literal XML bytes."""
    path = tmp_path / "native.rdf.gz"
    path.write_bytes(gzip.compress(FIXTURE.read_bytes()))
    assert load_native_rdf(path) == load_native_rdf(FIXTURE)


def test_stream_compression_is_explicit():
    """Reject an unspecified caller-stream dialect instead of guessing from bytes."""
    with pytest.raises(ValueError, match="compressed"):
        load_native_rdf(io.BytesIO(FIXTURE.read_bytes()))


@pytest.mark.parametrize(
    "old,new,side,match",
    [
        ("Participant_1", "Missing_1", "unknown", "side"),
        ('<rh:compound rdf:resource="http://rdf.rhea-db.org/Compound_1"/>', "", "100_L", "compound"),
        (
            '<rh:compound rdf:resource="http://rdf.rhea-db.org/Compound_1"/>',
            '<rh:compound rdf:resource="http://rdf.rhea-db.org/Compound_1"/>'
            '<rh:compound rdf:resource="http://rdf.rhea-db.org/Compound_other"/>',
            "100_L",
            "Ambiguous",
        ),
        ('<rh:chebi rdf:resource="http://purl.obolibrary.org/obo/CHEBI_15377"/>', "", "100_L", "chemical"),
        (
            '<rh:chebi rdf:resource="http://purl.obolibrary.org/obo/CHEBI_15378"/>',
            "",
            "100_R",
            "reactive",
        ),
        ("CHEBI_27732", "NOT_CHEBI_27732", "100_L", "ChEBI"),
    ],
)
def test_missing_or_ambiguous_chemical_paths_fail_explicitly(tmp_path, old, new, side, match):
    """No incomplete side-to-chemical chain may be silently dropped from a selected side."""
    path = tmp_path / "changed.rdf"
    path.write_text(FIXTURE.read_text().replace(old, new))
    index = load_native_rdf(path)
    with pytest.raises(NativeRheaError, match=match):
        index.chemical_participants(RH + side)


def test_selected_resource_property_cannot_be_a_literal(tmp_path):
    """Reject malformed selected RDF properties instead of changing their meaning."""
    path = tmp_path / "literal.rdf"
    path.write_text(
        FIXTURE.read_text().replace(
            '<rh:status rdf:resource="http://rdf.rhea-db.org/Approved"/>', "<rh:status>Approved</rh:status>"
        )
    )
    with pytest.raises(NativeRheaError, match="resource"):
        load_native_rdf(path)


@pytest.mark.parametrize(
    "attribute", ['nodeID="other"', 'datatype="http://www.w3.org/2001/XMLSchema#string"', 'parseType="Resource"']
)
def test_selected_resource_cannot_have_competing_rdf_shape(tmp_path, attribute):
    """Reject a resource assertion with contradictory blank-node or literal encoding."""
    path = tmp_path / "conflicting-resource.rdf"
    path.write_text(
        FIXTURE.read_text().replace(
            '<rh:status rdf:resource="http://rdf.rhea-db.org/Approved"/>',
            f'<rh:status rdf:{attribute} rdf:resource="http://rdf.rhea-db.org/Approved"/>',
        )
    )
    with pytest.raises(NativeRheaError, match="resource"):
        load_native_rdf(path)


def test_literal_datatype_and_language_attributes_remain_supported(tmp_path):
    """Resource-shape rejection must not reject legitimate literal annotations."""
    path = tmp_path / "literal-attributes.rdf"
    path.write_text(
        FIXTURE.read_text()
        .replace("<rdfs:label>fixture master</rdfs:label>", '<rdfs:label xml:lang="en">fixture master</rdfs:label>')
        .replace(
            "<rh:equation>left = right</rh:equation>",
            '<rh:equation rdf:datatype="http://www.w3.org/2001/XMLSchema#string">left = right</rh:equation>',
        )
    )
    master = load_native_rdf(path).reactions["RHEA:100"]
    assert master[LABEL] == ("fixture master",)
    assert master[RH + "equation"] == ("left = right",)


def test_conflicting_split_reaction_metadata_remains_visible(tmp_path):
    """Union distinct metadata values so the family validator can reject contradictions."""
    path = tmp_path / "conflict.rdf"
    path.write_text(FIXTURE.read_text().replace("fixture master", "first label", 1))
    assert load_native_rdf(path).reactions["RHEA:100"][LABEL] == ("first label", "fixture master")


def test_dangling_participant_fails_without_returning_partial_side(tmp_path):
    """A missing second participant cannot silently leave only the first valid compound."""
    path = tmp_path / "missing-participant.rdf"
    path.write_text(
        FIXTURE.read_text().replace(
            '<rh:contains rdf:resource="http://rdf.rhea-db.org/Participant_2"/>',
            '<rh:contains rdf:resource="http://rdf.rhea-db.org/Missing_2"/>',
        )
    )
    with pytest.raises(NativeRheaError, match="participant compound"):
        load_native_rdf(path).chemical_participants(RH + "100_L")


@pytest.mark.parametrize("additional", ["chebi", "underlyingChebi"])
def test_ambiguous_terminal_chemical_target_fails(tmp_path, additional):
    """Reject conflicting terminal values and conflicting whole-compound route shapes."""
    path = tmp_path / "ambiguous-compound.rdf"
    path.write_text(
        FIXTURE.read_text().replace(
            '<rh:chebi rdf:resource="http://purl.obolibrary.org/obo/CHEBI_15377"/>',
            '<rh:chebi rdf:resource="http://purl.obolibrary.org/obo/CHEBI_15377"/>'
            f'<rh:{additional} rdf:resource="http://purl.obolibrary.org/obo/CHEBI_15378"/>',
            1,
        )
    )
    with pytest.raises(NativeRheaError, match="Ambiguous"):
        load_native_rdf(path).chemical_participants(RH + "100_L")


def test_caller_stream_remains_open_after_parse_failure():
    """A malformed snapshot must not close a handle owned by consumed-input admission."""
    stream = io.BytesIO(gzip.compress(b"<rdf:RDF>broken"))
    with pytest.raises(ValueError):
        load_native_rdf(stream, compressed=True)
    assert not stream.closed


def test_incremental_reads_and_many_split_descriptions():
    """Read bounded XML chunks while unioning repeated descriptions across the entire stream."""

    class BoundedReader(io.BytesIO):
        """Reject an unbounded whole-file read by the native XML parser."""

        def read(self, size=-1):
            """Permit only positive bounded reads that preserve parser streaming behavior."""
            assert 0 < size <= 65536
            return super().read(size)

    duplicate = (
        '<rdf:Description rdf:about="http://rdf.rhea-db.org/100">'
        "<rdfs:label>fixture master</rdfs:label></rdf:Description>"
    )
    payload = FIXTURE.read_text().replace("</rdf:RDF>", duplicate * 2000 + "</rdf:RDF>").encode()
    stream = BoundedReader(payload)
    assert load_native_rdf(stream, compressed=False) == load_native_rdf(FIXTURE)
