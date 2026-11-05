"""Exercise pristine FOODON retirements through producer, authority, and replay (#1745)."""

import copy
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest
from lxml import etree

from kg_microbe.utils import foodon_kernel_quarantine as native
from kg_microbe.utils.foodon_classification import foodon_categories, organism_classes
from kg_microbe.utils.foodon_kernel_producer import verify_kernel_audit_bindings
from kg_microbe.utils.source_category_authority import SourceCategoryAuthority
from tests.test_foodon_kernel_quarantine import POLICY, prepare, publish

FIXTURE = Path(__file__).parent / "resources/foodon_kernel/cold_conversion"
RETIRED = "CHEBI:23652"
LIVE_CHILD = "CHEBI:25140"


def document():
    """Load the immutable actual cold conversion, with its original obsolete incidence."""
    return json.loads((FIXTURE / "foodon.json").read_text())


def reviewed(graphs, owl=None):
    """Use the actual native OWL excerpt unless a negative control supplies damaged bytes."""
    return native.reviewed_hierarchy(
        graphs, POLICY, native_owl=io.BytesIO((FIXTURE / "foodon.owl").read_bytes() if owl is None else owl)
    )


def prepare_cold(tmp_path):
    """Install cold fixture inputs before the producer consumes either native source."""
    transform, scope, audit = prepare(tmp_path)
    for name in ("foodon.json", "foodon.owl"):
        shutil.copyfile(FIXTURE / name, transform.input_base_dir / name)
    return transform, scope, audit


def test_actual_cold_fixture_and_live_projection_preserve_finite_decisions():
    """Separate source-backed deprecation preparation from the unchanged 22-class correction."""
    origin = json.loads((FIXTURE / "origin.json").read_text())
    for name, identity in origin["fixtures"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == identity["sha256"]
    graphs = document()["graphs"]
    original = copy.deepcopy(graphs)
    with pytest.raises(ValueError, match="lacks a live CLASS declaration"):
        organism_classes(graphs)
    view, evidence = reviewed(graphs)
    declared = {native.compact(n["id"]) for g in view for n in g["nodes"]}
    assert RETIRED not in declared
    assert LIVE_CHILD in declared
    # One actual retired node/four incident edges, independently of the one
    # explicitly quarantined kernel parent. All original witnesses stay intact.
    assert sum(len(g["nodes"]) for g in graphs) - sum(len(g["nodes"]) for g in view) == 1
    assert sum(len(g["edges"]) for g in graphs) - sum(len(g["edges"]) for g in view) == 5
    categories = foodon_categories(view)
    assert all(categories[i] == "biolink:Food" for i in POLICY["cohort"])
    assert categories[native.REJECTED_PARENT] == "biolink:OrganismTaxon"
    assert evidence.cohort == frozenset(POLICY["cohort"])
    assert native.digest(evidence.json_records) == native.JSON_EVIDENCE_SHA256
    assert native.digest(evidence.owl_records) == native.OWL_EVIDENCE_SHA256
    assert graphs == original


def test_cold_producer_private_preparation_keeps_pristine_consumed_inputs(tmp_path):
    """Run the real producer boundary before the real private sanitation/deprecation methods."""
    transform, scope, _ = prepare_cold(tmp_path)
    path = transform.input_base_dir / "foodon.json"
    raw = path.read_bytes()
    private = scope.prepare_source(path)
    assert private.read_bytes() == raw
    assert transform.consumed_input_snapshots[native.JSON_ROLE]["sha256"] == hashlib.sha256(raw).hexdigest()
    transform._sanitize_obograph_synonyms(private)
    transform._drop_deprecated_terms(private)
    live = json.loads(private.read_text())["graphs"]
    assert RETIRED not in {native.compact(n["id"]) for g in live for n in g["nodes"]}
    organism_classes(live)
    assert path.read_bytes() == raw
    transform.verify_consumed_inputs()


def test_cold_authority_and_audit_replay_use_same_pristine_evidence(tmp_path):
    """Exercise actual source snapshots, projected audit rows, and independent replay validation."""
    transform, scope, audit = prepare_cold(tmp_path)
    raw_before = {name: (transform.input_base_dir / name).read_bytes() for name in ("foodon.json", "foodon.owl")}
    publish(transform, scope, audit)

    def opener(path):
        """Bind every selected authority to the actual consumed-input lifecycle."""
        authority_path = Path(path)
        suffix = "_owl" if authority_path.suffix == ".owl" else ""
        return transform.consume_input(f"category_authority_{authority_path.stem}{suffix}", path)

    authority = SourceCategoryAuthority(transform.input_base_dir, opener=opener)
    for identifier in POLICY["cohort"]:
        row = {"id": identifier, "category": "biolink:OrganismTaxon"}
        authority.normalize(row)
        assert row["category"] == "biolink:Food"
    control = {"id": native.REJECTED_PARENT, "category": ""}
    authority.normalize(control)
    assert control["category"] == "biolink:OrganismTaxon"
    verify_kernel_audit_bindings(transform.output_dir, transform.consumed_input_snapshots, members=scope.member_names())
    transform.verify_consumed_inputs()
    assert all((transform.input_base_dir / name).read_bytes() == payload for name, payload in raw_before.items())


@pytest.mark.parametrize("damage", ["missing", "property", "individual", "conflicting_live_retired"])
def test_retired_incidence_cannot_hide_invalid_original_endpoint(damage):
    """Validate the live peer and compacted duplicate declarations before retirement filtering."""
    graphs = document()["graphs"]
    graph = graphs[0]
    child = next(n for n in graph["nodes"] if native.compact(n["id"]) == LIVE_CHILD)
    if damage == "missing":
        graph["nodes"].remove(child)
    elif damage == "conflicting_live_retired":
        duplicate = copy.deepcopy(child)
        duplicate["id"] = LIVE_CHILD
        duplicate.setdefault("meta", {})["deprecated"] = True
        graph["nodes"].append(duplicate)
    else:
        child["type"] = damage.upper()
    with pytest.raises(ValueError, match="(Conflicting FOODON declarations|lacks a CLASS declaration)"):
        reviewed(graphs)


@pytest.mark.parametrize(
    "damage", ["missing_source_flag", "source_false", "wrong_source_type", "fabricated_retirement"]
)
def test_retirement_requires_matching_native_owl_declaration(damage):
    """A conversion-only flag cannot remove a live class or conceal unsupported ancestry."""
    graphs = document()["graphs"]
    tree = etree.parse(str(FIXTURE / "foodon.owl"))
    retired = next(
        e for e in tree.iter(native._OWL + "Class") if native.compact(e.get(native._RDF + "about", "")) == RETIRED
    )
    flag = retired.find(native._OWL + "deprecated")
    if damage == "missing_source_flag":
        retired.remove(flag)
    elif damage == "source_false":
        flag.text = "false"
    elif damage == "wrong_source_type":
        retired.tag = native._OWL + "ObjectProperty"
    else:
        child = next(n for n in graphs[0]["nodes"] if native.compact(n["id"]) == LIVE_CHILD)
        child.setdefault("meta", {})["deprecated"] = True
    with pytest.raises(ValueError, match="(retirement|native OWL declaration)"):
        reviewed(graphs, etree.tostring(tree))


def test_retired_incidence_must_exist_in_native_owl():
    """Do not discard an invented edge merely because its endpoints are valid declarations."""
    graphs = document()["graphs"]
    graphs[0]["edges"].append({"sub": RETIRED, "pred": "is_a", "obj": LIVE_CHILD})
    with pytest.raises(ValueError, match="retired incidence lacks native OWL named-parent evidence"):
        reviewed(graphs)


def test_native_owl_comments_do_not_change_retirement_authority():
    """Full RDF/XML includes source comments omitted by the selected fixture extraction."""
    tree = etree.parse(str(FIXTURE / "foodon.owl"))
    tree.getroot().insert(0, etree.Comment("http://purl.obolibrary.org/obo/CHEBI_23652"))
    view, evidence = reviewed(document()["graphs"], etree.tostring(tree))
    assert evidence.cohort == frozenset(POLICY["cohort"])
    assert RETIRED not in {native.compact(n["id"]) for g in view for n in g["nodes"]}
