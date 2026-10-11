"""Finite corrections to Madin et al's downloaded environments.csv."""

import csv
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

import pandas as pd
import pytest
from lxml import etree

from kg_microbe.transform_utils import constants as C
from kg_microbe.transform_utils.constants import ENVO_ID_COLUMN, ENVO_TERMS_COLUMN, TYPE_COLUMN
from kg_microbe.transform_utils.madin_etal import madin_etal
from kg_microbe.transform_utils.madin_etal.madin_etal import (
    ENVIRONMENT_ID_CORRECTIONS_FILE,
    _apply_environment_id_corrections,
)
from kg_microbe.utils.stub_curie_collection import DEFAULT_MAPPING_PATHS, collect_stub_curies

REPO_ROOT = Path(__file__).resolve().parents[1]
RETIREMENT_FIXTURE = Path(__file__).parent / "resources" / "madin_foodon_retirement"


def _frame(rows):
    """Build a minimal environments.csv frame."""
    return pd.DataFrame(
        {
            TYPE_COLUMN: [r[0] for r in rows],
            ENVO_TERMS_COLUMN: [r[1] for r in rows],
            ENVO_ID_COLUMN: [r[2] for r in rows],
        }
    )


class EnvironmentCorrectionTest(TestCase):
    """Curated upstream rows that name the wrong or a retired term."""

    def test_the_taxonomy_root_is_replaced_by_the_plant_root(self):
        """
        `NCBITaxon:1` is the root of the tree of life, matched on the label "root".

        It produced 628 merged edges asserting the root of all life is the
        `location_of` an organism. HabitatMech dropped these by refusing taxa as
        habitats; kg-microbe applied no such filter and asserted them.
        """
        out = _apply_environment_id_corrections(_frame([("host_plant_root-associated", "root", "NCBITaxon:1")]))
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "PO:0009005")
        self.assertEqual(out.iloc[0][ENVO_TERMS_COLUMN], "root")

    def test_the_whole_respiratory_tract_is_narrowed_to_the_nasopharynx(self):
        """Nasopharyngeal measurements must not be asserted about trachea and alveoli."""
        out = _apply_environment_id_corrections(
            _frame([("host_animal_endotherm_nasopharyngeal", "respiratory tract", "UBERON:0000065")])
        )
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "UBERON:0001728")
        self.assertEqual(out.iloc[0][ENVO_TERMS_COLUMN], "nasopharynx")

    def test_unrelated_rows_are_untouched(self):
        """A correction table that rewrites more than it names is worse than none."""
        out = _apply_environment_id_corrections(_frame([("soil", "soil", "ENVO:00001998")]))
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "ENVO:00001998")

    def test_a_correction_does_not_fire_once_upstream_fixes_the_row(self):
        """
        Match on the exact wrong value, not just the row key.

        Otherwise a stale correction would overwrite a *newer* upstream value
        with an older one — turning the fix into the next bug.
        """
        out = _apply_environment_id_corrections(_frame([("host_plant_root-associated", "root", "PO:0009005")]))
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "PO:0009005")

    def test_an_unapplied_correction_is_reported(self):
        """A table that silently stops matching is a table nobody will ever clean up."""
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            _apply_environment_id_corrections(_frame([("soil", "soil", "ENVO:00001998")]))
        self.assertIn("not applied", buf.getvalue())

    def test_native_retired_foodon_component_preserves_companion(self):
        """Native FOODON replacement changes only its aligned identifier and label."""
        before = pd.read_csv(RETIREMENT_FIXTURE / "environments.csv", keep_default_na=False)
        expected = before.copy(deep=True)
        expected.loc[0, ENVO_ID_COLUMN] = "PO:0009011, UBERON:0002049"
        expected.loc[0, ENVO_TERMS_COLUMN] = "plant structure, vasculature"
        pd.testing.assert_frame_equal(_apply_environment_id_corrections(before), expected)

    def test_retirement_does_not_match_other_key_or_identifier_substring(self):
        """Neither labels nor substrings establish the identity to be corrected."""
        before = _frame(
            [
                ("another_habitat", "part of plant, vasculature", "FOODON:03420174, UBERON:0002049"),
                ("host_plant_vasculature", "part of plant", "FOODON:034201740"),
                ("host_plant_vasculature", "part of plant", "OTHER:FOODON:03420174"),
                ("host_plant_vasculature", "part of plant", "PO:0009011"),
                ("host_plant_vasculature", "part of plant", "PO:0025131"),
            ]
        )
        expected = before.copy(deep=True)
        pd.testing.assert_frame_equal(_apply_environment_id_corrections(before), expected)

    def test_retirement_preserves_token_order_and_other_labels(self):
        """A display-label change does not override exact native identifier authority."""
        before = _frame(
            [("host_plant_vasculature", "vasculature, changed display label", "UBERON:0002049, FOODON:03420174")]
        )
        out = _apply_environment_id_corrections(before)
        self.assertEqual(out.iloc[0][ENVO_ID_COLUMN], "UBERON:0002049, PO:0009011")
        self.assertEqual(out.iloc[0][ENVO_TERMS_COLUMN], "vasculature, plant structure")

    def test_retirement_is_idempotent(self):
        """A second pass cannot rewrite an already corrected row."""
        first = _apply_environment_id_corrections(pd.read_csv(RETIREMENT_FIXTURE / "environments.csv"))
        expected = first.copy(deep=True)
        pd.testing.assert_frame_equal(_apply_environment_id_corrections(first), expected)

    def test_ambiguous_component_label_alignment_aborts(self):
        """Do not silently lose or reassign companion labels in malformed input."""
        before = _frame([("host_plant_vasculature", "one ambiguous label", "FOODON:03420174, UBERON:0002049")])
        expected = before.copy(deep=True)
        with pytest.raises(ValueError, match="align"):
            _apply_environment_id_corrections(before)
        pd.testing.assert_frame_equal(before, expected)


class StubRegistrationTest(TestCase):
    """The corrected targets must resolve to real nodes."""

    def test_the_corrections_file_is_scanned_for_stub_curies(self):
        """
        Registration is what makes the fix safe.

        `PO:0009005` is carried by no loaded ontology, so a correction written
        outside a scanned mapping file would swap the taxonomy-root phantom for
        a PO phantom — the defect fixed for NCBITaxon in #815.
        """
        self.assertIn(ENVIRONMENT_ID_CORRECTIONS_FILE, DEFAULT_MAPPING_PATHS)

    def test_the_plant_root_target_is_collected_for_stub_emission(self):
        """End-to-end: the id reaches the set ontologies_stubs builds nodes from."""
        self.assertIn("PO:0009005", collect_stub_curies(["PO"])["PO"])

    def test_retired_foodon_replacement_is_collected_from_this_table(self):
        """The replacement is a single CURIE, not an undiscoverable composite cell."""
        self.assertIn("PO:0009011", collect_stub_curies(["PO"], [ENVIRONMENT_ID_CORRECTIONS_FILE])["PO"])


def test_foodon_retirement_is_pinned_native_identity_not_a_label_match():
    """The immutable native OWL excerpt explicitly replaces one deprecated class."""
    ns = {
        "owl": "http://www.w3.org/2002/07/owl#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "obo": "http://purl.obolibrary.org/obo/",
    }
    root = etree.parse(
        str(RETIREMENT_FIXTURE / "native-authority.owl"),
        parser=etree.XMLParser(no_network=True, resolve_entities=False),
    ).getroot()
    records = {node.attrib[f"{{{ns['rdf']}}}about"]: node for node in root.findall("owl:Class", ns)}
    old = records[ns["obo"] + "FOODON_03420174"]
    replacement = records[ns["obo"] + "PO_0009011"]
    assert old.findtext("owl:deprecated", namespaces=ns) == "true"
    assert [node.attrib[f"{{{ns['rdf']}}}resource"] for node in old.findall("obo:IAO_0100001", ns)] == [
        ns["obo"] + "PO_0009011"
    ]
    assert replacement.find("owl:deprecated", ns) is None
    assert replacement.findtext("rdfs:label", namespaces=ns) == "plant structure"
    assert replacement.find("rdfs:subClassOf", ns).attrib[f"{{{ns['rdf']}}}resource"] == ns["obo"] + "PO_0025131"
    corrections = pd.read_csv(ENVIRONMENT_ID_CORRECTIONS_FILE, sep="\t", comment="#")
    matches = corrections[corrections.wrong_object_id == "FOODON:03420174"]
    assert len(matches) == 1
    assert matches.iloc[0].environment_type == "host_plant_vasculature"
    assert matches.iloc[0].object_id == "PO:0009011"
    assert matches.iloc[0].object_label == "plant structure"


def test_native_four_observations_keep_edges_and_provenance(tmp_path, monkeypatch):
    """Run actual producer emission twice; only the four retired subjects change."""
    monkeypatch.setattr(madin_etal, "load_metpo_mappings", lambda *_args: {})
    monkeypatch.setattr(madin_etal, "ChemicalMappingLoader", lambda: None)
    monkeypatch.setattr(madin_etal, "get_exclusion_token_list", lambda *_args: [])
    monkeypatch.setattr(madin_etal, "get_chebi_adapter", lambda: SimpleNamespace(relationships=lambda **_kwargs: []))
    monkeypatch.setattr(madin_etal, "cache_is_complete", lambda *_args: True)
    for prefix in ("chebi", "go"):
        pd.DataFrame(
            columns=[C.OBJECT_ID_COLUMN, C.OBJECT_LABEL_COLUMN, C.SUBJECT_LABEL_COLUMN, C.TRAITS_DATASET_LABEL_COLUMN]
        ).to_csv(tmp_path / f"{prefix}_ner.tsv", sep="\t", index=False)

    def run_producer(output_name):
        """Use unchanged raw excerpts and isolated output, without remote enrichment."""
        producer = madin_etal.MadinEtAlTransform(RETIREMENT_FIXTURE, tmp_path / output_name, nlp=False)
        producer.nlp_output_dir = tmp_path
        producer.nlp_stopwords_dir = tmp_path
        producer.run(show_status=False)
        with producer.output_edge_file.open() as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    with monkeypatch.context() as before_patch:
        # An empty, explicit cohort models the old producer policy; production
        # must still consume and fingerprint its selected correction table.
        empty_corrections = tmp_path / "no_corrections.tsv"
        empty_corrections.write_text(
            "environment_type\twrong_object_id\twrong_object_label\tobject_id\tobject_label\tnotes\n"
        )
        before_patch.setattr(madin_etal, "ENVIRONMENT_ID_CORRECTIONS_FILE", empty_corrections)
        before = run_producer("before")
    after = run_producer("after")
    retired = [row for row in before if row[C.SUBJECT_COLUMN] == "FOODON:03420174"]
    corrected = [row for row in after if row[C.SUBJECT_COLUMN] == "PO:0009011"]
    assert len(retired) == len(corrected) == 4
    assert {row[C.OBJECT_COLUMN] for row in corrected} == {
        "NCBITaxon:399742",
        "NCBITaxon:324057",
        "NCBITaxon:519050",
        "NCBITaxon:456493",
    }
    for row in corrected:
        assert row[C.PREDICATE_COLUMN] == C.NCBI_TO_ISOLATION_SOURCE_EDGE
        assert row[C.RELATION_COLUMN] == C.LOCATION_OF
        assert row[C.PRIMARY_KNOWLEDGE_SOURCE_COLUMN] == "infores:madin_etal"
        assert row[C.KNOWLEDGE_LEVEL_COLUMN] == C.OBSERVATION
        assert row[C.AGENT_TYPE_COLUMN] == C.MANUAL_AGENT
    expected = [
        {**row, C.SUBJECT_COLUMN: "PO:0009011"} if row[C.SUBJECT_COLUMN] == "FOODON:03420174" else row for row in before
    ]
    assert Counter(tuple(sorted(row.items())) for row in after) == Counter(
        tuple(sorted(row.items())) for row in expected
    )
    assert len([row for row in after if row[C.SUBJECT_COLUMN] == "UBERON:0002049"]) == 4
