"""Unified mappings can resolve local chemistry IDs that still need nodes (#1073)."""

import csv
import io

import pytest

from kg_microbe.transform_utils.microbedecoder.microbedecoder import MicrobeDecoderTransform


class _ChemicalLookup:
    """Hermetic mapping lookup with explicit per-entity labels and categories."""

    def __init__(self, curie, name=None, category=None):
        """Store one mapped entity."""
        self.curie, self.name, self.category = curie, name, category

    def find_chebi_by_name(self, label, fuzzy_stereochemistry=True):
        """Return the same mapping for either spelling of the source label."""
        return self.curie

    def get_canonical_name(self, curie):
        """Return only the supplied canonical name."""
        assert curie == self.curie
        return self.name

    def get_category(self, curie):
        """Return only the supplied category."""
        assert curie == self.curie
        return self.category


@pytest.mark.parametrize("curie", ["kgmicrobe.compound:sugars", "kgmicrobe.ingredient:1_butanol_co2"])
def test_local_mapping_emits_named_node_once_without_changing_identity(tmp_path, curie):
    """A successful local lookup must not leave a merge-created anonymous NamedThing."""
    transform = MicrobeDecoderTransform(
        input_dir=tmp_path,
        output_dir=tmp_path,
        chemical_loader=_ChemicalLookup(curie, "Supplied mixture name", "biolink:ChemicalMixture"),
    )
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")
    writer.writerow(transform.node_header)
    for label in ("raw spelling", "alternate raw spelling"):
        assert transform._resolve_chemical_curie(label, writer, "bergey:substrates") == curie
    rows = list(csv.DictReader(io.StringIO(output.getvalue()), delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["id"] == curie
    assert rows[0]["name"] == "Supplied mixture name"
    assert rows[0]["category"] == "biolink:ChemicalMixture"
    assert rows[0]["provided_by"] == "infores:microbedecoder"
    assert not rows[0].get("same_as")
    assert not rows[0].get("xref")
    assert transform._stats["unmatched_labels"] == 0


def test_local_mapping_without_enrichment_retains_raw_name_and_generic_category(tmp_path):
    """An absent mapped label is not permission to infer a ChEBI identity."""
    curie = "kgmicrobe.compound:aminovalerate"
    transform = MicrobeDecoderTransform(input_dir=tmp_path, output_dir=tmp_path, chemical_loader=_ChemicalLookup(curie))
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")
    writer.writerow(transform.node_header)
    assert transform._resolve_chemical_curie("Aminovalerate", writer, "bergey:substrates") == curie
    row = next(csv.DictReader(io.StringIO(output.getvalue()), delimiter="\t"))
    assert row["id"] == curie
    assert row["name"] == "Aminovalerate"
    assert row["category"] == "biolink:ChemicalEntity"


@pytest.mark.parametrize("curie", ["CHEBI:15377", "FOODON:03315426", "ENVO:00001998"])
def test_external_ontology_resolution_is_not_stubbed(tmp_path, curie):
    """Existing authoritative ontology targets remain the other transform's responsibility."""
    transform = MicrobeDecoderTransform(input_dir=tmp_path, output_dir=tmp_path, chemical_loader=_ChemicalLookup(curie))
    output = io.StringIO()
    assert transform._resolve_chemical_curie("raw label", csv.writer(output), "bergey:substrates") == curie
    assert output.getvalue() == ""
    assert not transform._seen_nodes
