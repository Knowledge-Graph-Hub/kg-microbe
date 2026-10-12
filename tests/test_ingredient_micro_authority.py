"""Ingredient acceptance uses native MICRO declarations, not inferred aliases."""

import json
from contextlib import contextmanager
from pathlib import Path

from lxml import etree

from kg_microbe.utils.ontology_category_authority import OntologyCategoryAuthority
from tests.ingredient_acceptance_runner import sha256

NATIVE = Path(__file__).parent / "resources/ingredient_bundle/native"


def test_acceptance_micro_excerpt_is_hash_bound_and_retains_original_iris():
    """Historical stub CURIEs cannot silently rewrite native declaration identity."""
    origin = json.loads((NATIVE / "acceptance-native-origin.json").read_text())
    fixture = NATIVE / "micro-authority.owl"
    assert sha256(fixture) == origin["members"][fixture.name]["sha256"]
    assert fixture.stat().st_size == origin["members"][fixture.name]["bytes"]
    source = origin["sources"]["data/raw/micro.owl"]
    assert source["sha256"] == "ef21dbfab755143a9c390ad274d4e1405f344f6a8dbfbd749de09af0b4b54910"
    document = etree.parse(str(fixture))
    declarations = {
        node.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about")
        for node in document.getroot().findall("{http://www.w3.org/2002/07/owl#}Class")
    }
    assert declarations == set(source["complete_named_ancestor_declaration_iris"])
    assert set(source["selected_seed_iris"]) <= declarations
    assert not {identifier.replace("/MicrO.owl/", "/") for identifier in source["selected_seed_iris"]} & declarations


def test_acceptance_micro_excerpt_has_genuine_material_ancestry_without_filler_inference(tmp_path):
    """A genuine ancestor class resolves; a restriction filler is not a declaration."""

    @contextmanager
    def opener(path):
        """Supply the immutable native excerpt under its runtime authority name."""
        assert path.name == "micro.owl"
        with (NATIVE / "micro-authority.owl").open() as stream:
            yield stream

    authority = OntologyCategoryAuthority(tmp_path, opener=opener)
    assert authority.category_for("MICRO:0000167") == "biolink:ChemicalMixture"
    assert authority.evidence_for("MICRO:0000067").disposition == "undeclared"
    for identifier in ("MICRO:0002250", "MICRO:0002392", "MICRO:0002393"):
        assert authority.category_for(identifier) is None
        assert authority.evidence_for(identifier).disposition == "undeclared"
