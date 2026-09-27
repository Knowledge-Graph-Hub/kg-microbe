"""Exercise two evidence-guarded NCIT categories through the actual stub producer (#1180)."""

import copy
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.ontologies_stubs import ontologies_stubs_transform as module
from kg_microbe.transform_utils.ontologies_stubs.ncit_category_projection import (
    FIELDS,
    REVIEWED_CATEGORIES,
    read_dispositions,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_consumed_inputs

FIXTURE = Path(__file__).parent / "resources/ncit_category_projection/native.json"
POLICY = Path(__file__).resolve().parents[1] / "mappings/ncit_category_dispositions.tsv"


class NativeAdapter:
    """Expose immutable direct native statements through the consumed OAK interfaces."""

    def __init__(self, evidence):
        """Copy native annotations and keep separately identified synthetic metadata controls."""
        self.metadata = {}
        for subject, predicate, obj, value in evidence["statements"]:
            self.metadata.setdefault(subject, {}).setdefault(predicate, []).append(obj or value)
        self.aliases = copy.deepcopy(evidence["aliases"])

    def label(self, curie):
        """Return the native label or an unchanged conceptual ancestor control."""
        return self.metadata.get(curie, {}).get("rdfs:label", [curie])[0]

    def entity_aliases(self, curie):
        """Keep the direct native alias list unchanged."""
        return self.aliases.get(curie, [])

    def entity_metadata_map(self, curie, include_all_triples=False):
        """Mirror the full native triple query needed for P106 and named parents."""
        return self.metadata.get(curie, {})

    def outgoing_relationships(self, curie, predicates=None):
        """Expose named parents, not anonymous restrictions, as the SemSQL Edge view does."""
        return [
            ("rdfs:subClassOf", parent)
            for parent in self.metadata.get(curie, {}).get("rdfs:subClassOf", [])
            if not parent.startswith("_:")
        ]


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """Run real dispatch/open/binding/writing with only the OAK reader injected."""
    import oaklib

    raw = tmp_path / "raw"
    raw.mkdir()
    db = raw / "ncit.db"
    db.write_bytes(FIXTURE.read_bytes())
    policy = tmp_path / "dispositions.tsv"
    policy.write_bytes(POLICY.read_bytes())
    evidence = json.loads(db.read_bytes())
    adapter = NativeAdapter(evidence)
    calls = []

    def open_selected(locator):
        """Reject any silent fallback outside this test's selected native input."""
        calls.append(locator)
        assert locator == f"sqlite:{db}"
        return adapter

    monkeypatch.setattr(oaklib, "get_adapter", open_selected)
    monkeypatch.setattr(module, "NCIT_CATEGORY_DISPOSITIONS", policy)
    monkeypatch.setattr(module, "collect_stub_curies", lambda prefixes: {"NCIT": set(REVIEWED_CATEGORIES)})
    transform = module.OntologiesStubsTransform(input_dir=raw, output_dir=tmp_path / "out")
    return transform, adapter, db, policy, calls


def read_tsv(path):
    """Read only the tiny fixture graph with literal finalized-style TSV cells."""
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE))


def test_actual_ncit_walk_changes_only_two_categories(prepared):
    """Preserve complete node metadata and hierarchy instead of replacing chemical identity."""
    transform, adapter, db, policy, calls = prepared
    # Explicitly synthetic extra metadata proves category projection does not erase xrefs.
    adapter.metadata["NCIT:C71939"]["oio:hasDbXref"] = ["example:kept"]
    transform.run()
    rows = {row["id"]: row for row in read_tsv(transform.output_dir / "ncit_nodes.tsv")}
    assert set(rows) == {"NCIT:C71939", "NCIT:C16883", "NCIT:C62695", "NCIT:C16642"}
    for curie, category in REVIEWED_CATEGORIES.items():
        assert rows[curie] == dict(
            zip(
                transform.node_header,
                [
                    curie,
                    category,
                    adapter.label(curie),
                    "",
                    "example:kept" if curie.endswith("71939") else "",
                    "ontologies_stubs",
                    "Mucus Glycoprotein" if curie.endswith("16883") else "",
                    "",
                    "",
                ],
                strict=True,
            )
        )
    assert rows["NCIT:C62695"]["category"] == rows["NCIT:C16642"]["category"] == "biolink:OntologyClass"
    edges = read_tsv(transform.output_dir / "ncit_edges.tsv")
    assert edges == [
        dict(
            zip(
                transform.edge_header,
                [
                    child,
                    "biolink:subclass_of",
                    parent,
                    "rdfs:subClassOf",
                    "infores:ncit",
                    "knowledge_assertion",
                    "automated_agent",
                ],
                strict=True,
            )
        )
        for child, parent in [("NCIT:C16883", "NCIT:C16642"), ("NCIT:C71939", "NCIT:C62695")]
    ]
    assert calls == [f"sqlite:{db}"]
    snapshots = transform.consumed_input_snapshots
    assert snapshots["ncit_category_authority"] == {
        "path": str(db),
        "sha256": hashlib.sha256(db.read_bytes()).hexdigest(),
    }
    assert snapshots["ncit_category_dispositions"]["sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    verify_consumed_inputs(transform)


def test_label_only_path_and_unreviewed_concept_stay_scoped(prepared):
    """A same-semantic-type conceptual control cannot expand the finite category policy."""
    transform, adapter, db, _, _ = prepared
    adapter.metadata["NCIT:C20181"] = {"rdfs:label": ["Concept"], "NCIT:P106": ["Food"]}
    target = transform.output_dir / "ncit_nodes.tsv"
    transform._write_stub_nodes_from_semsql("NCIT", [*REVIEWED_CATEGORIES, "NCIT:C20181"], db, "infores:ncit", target)
    rows = {row["id"]: row for row in read_tsv(target)}
    assert {curie: rows[curie]["category"] for curie in REVIEWED_CATEGORIES} == REVIEWED_CATEGORIES
    assert rows["NCIT:C20181"]["category"] == "biolink:OntologyClass"


@pytest.mark.parametrize("curie", REVIEWED_CATEGORIES)
@pytest.mark.parametrize("predicate", ["rdfs:label", "NCIT:P106", "IAO:0000115", "rdfs:subClassOf"])
@pytest.mark.parametrize("mutation", ["missing", "contradiction", "malformed"])
def test_native_evidence_must_remain_exact_before_publication(prepared, curie, predicate, mutation):
    """Missing, contradictory or untyped native facts abort without replacing prior artifacts."""
    transform, adapter, _, _, _ = prepared
    if mutation == "missing":
        adapter.metadata[curie].pop(predicate)
    elif mutation == "contradiction":
        adapter.metadata[curie][predicate].append("NCIT:C999999")
    else:
        adapter.metadata[curie][predicate] = "not-a-list"
    old = {}
    for name in ("ncit_nodes.tsv", "ncit_edges.tsv"):
        path = transform.output_dir / name
        path.write_bytes(b"prior artifact\n")
        old[path] = path.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        transform.run()
    assert all(path.read_bytes() == payload for path, payload in old.items())
    with pytest.raises(SourceFinalizationRequired):
        verify_consumed_inputs(transform)


@pytest.mark.parametrize("method", ["label", "entity_aliases", "entity_metadata_map", "outgoing_relationships"])
def test_relevant_infrastructure_failure_is_not_absorbed(prepared, monkeypatch, method):
    """A failed native read cannot produce a seemingly reviewed category or a success marker."""
    transform, adapter, _, _, _ = prepared

    def fail(*args, **kwargs):
        """Model an unavailable native authority rather than an obsolete unrelated identifier."""
        raise RuntimeError("native reader failed")

    monkeypatch.setattr(adapter, method, fail)
    with pytest.raises(RuntimeError, match="native reader failed"):
        transform.run()
    assert not (transform.output_dir / "ncit_nodes.tsv").exists()
    with pytest.raises(SourceFinalizationRequired):
        verify_consumed_inputs(transform)


def test_gzip_only_selected_native_input_still_works(prepared):
    """Keep existing local gzip decompression and bind the exact decompressed consumed bytes."""
    transform, _, db, _, _ = prepared
    content = db.read_bytes()
    db.with_suffix(".db.gz").write_bytes(gzip.compress(content))
    db.unlink()
    transform.run()
    assert db.read_bytes() == content
    assert (
        transform.consumed_input_snapshots["ncit_category_authority"]["sha256"] == hashlib.sha256(content).hexdigest()
    )


@pytest.mark.parametrize("which", ["db", "policy", "wal", "symlink"])
def test_late_selected_input_drift_is_detected(prepared, tmp_path, which):
    """Byte changes, sidecar appearance and lexical retargeting all fail producer guards."""
    transform, _, db, policy, _ = prepared
    if which == "symlink":
        real = db.with_name("native-real.db")
        db.rename(real)
        db.symlink_to(real)
    transform.run()
    if which == "db":
        db.write_bytes(db.read_bytes() + b"\n")
    elif which == "policy":
        policy.write_bytes(policy.read_bytes() + b"\n")
    elif which == "wal":
        db.with_name("ncit.db-wal").write_bytes(b"new uncheckpointed state")
    else:
        replacement = db.with_name("native-new.db")
        replacement.write_bytes(db.read_bytes())
        db.unlink()
        db.symlink_to(replacement)
    with pytest.raises(SourceFinalizationRequired):
        transform.verify_consumed_inputs()


@pytest.mark.parametrize("which", ["outside", "symlink", "dangling", "gzip-symlink", "wal", "missing"])
def test_selected_native_authority_cannot_fall_back(prepared, tmp_path, which):
    """Only the selected input directory's stable database is eligible for native projection."""
    transform, _, db, _, calls = prepared
    if which in {"outside", "symlink", "dangling", "gzip-symlink"}:
        outside = tmp_path / "outside.db"
        content = db.read_bytes()
        if which != "dangling":
            outside.write_bytes(gzip.compress(content) if which == "gzip-symlink" else content)
        if which == "outside":
            with pytest.raises(ValueError, match="selected input directory"):
                transform._open_adapter("NCIT", outside)
            return
        db.unlink()
        if which == "gzip-symlink":
            db.with_suffix(".db.gz").symlink_to(outside)
        else:
            db.symlink_to(outside)
        if which == "dangling":
            db.with_suffix(".db.gz").write_bytes(gzip.compress(content))
    elif which == "wal":
        db.with_name("ncit.db-wal").write_bytes(b"existing uncheckpointed state")
    else:
        db.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        transform.run()
    assert calls == []
    if which == "dangling":
        assert not outside.exists()
    with pytest.raises(SourceFinalizationRequired):
        verify_consumed_inputs(transform)


def test_new_run_rebinds_authority_but_within_run_drift_stays_rejected(prepared):
    """A legitimate fresh run records native consumption again rather than retaining a stale guard."""
    transform, _, db, _, _ = prepared
    transform.run()
    db.write_bytes(db.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired):
        transform.run()
    transform.begin_consumed_inputs()
    transform.run()
    assert (
        transform.consumed_input_snapshots["ncit_category_authority"]["sha256"]
        == hashlib.sha256(db.read_bytes()).hexdigest()
    )


def test_adapter_creation_failure_cannot_leave_a_successful_consumed_state(prepared, monkeypatch):
    """Binding bytes does not make a failed native reader a successful producer execution."""
    import oaklib

    transform, _, _, _, _ = prepared

    def fail(locator):
        """Model an invalid or inaccessible SemSQL database."""
        raise RuntimeError("cannot open native database")

    monkeypatch.setattr(oaklib, "get_adapter", fail)
    with pytest.raises(RuntimeError, match="cannot open native database"):
        transform.run()
    with pytest.raises(SourceFinalizationRequired):
        verify_consumed_inputs(transform)


def test_existing_marker_contract_retains_native_bytes_and_refuses_late_drift(prepared, tmp_path, local_source_schema):
    """Use the real marker writer with the same consumed-input callback as production dispatch."""
    from kg_microbe.utils import transform_fingerprint as fingerprint

    transform, _, db, policy, _ = prepared
    transform.run()
    arguments = {
        "output_dir": transform.output_dir,
        "code_dir": Path(module.__file__).parent,
        "repo_root": Path(module.__file__).resolve().parents[3],
        "data_inputs": (),
        "input_dir": db.parent,
        "finalization_inputs": (str(db), str(policy)),
        "verify_inputs": transform.verify_consumed_inputs,
    }
    marker = fingerprint.write_fingerprint(**arguments)
    assert fingerprint.finalization_inputs_current(marker, arguments["repo_root"])
    assert set(marker["finalization_inputs"]) == {str(db), str(policy)}
    path = transform.output_dir / fingerprint.FINGERPRINT_FILE
    previous = path.read_bytes()
    db.write_bytes(db.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired):
        fingerprint.write_fingerprint(**arguments)
    assert path.read_bytes() == previous
    assert not fingerprint.finalization_inputs_current(marker, arguments["repo_root"])


@pytest.mark.parametrize("mutation", ["header", "missing", "duplicate", "additional", "category"])
def test_policy_cannot_expand_or_weaken_finite_scope(mutation):
    """Reject malformed, expanded or stronger category dispositions."""
    rows = list(csv.DictReader(io.StringIO(POLICY.read_text()), delimiter="\t"))
    header = FIELDS.copy()
    if mutation == "header":
        header.reverse()
    elif mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "additional":
        rows.append({**rows[0], "id": "NCIT:C20181"})
    else:
        rows[0]["category"] = "biolink:Protein"
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    stream.seek(0)
    with pytest.raises(ValueError):
        read_dispositions(stream)


def test_fixture_supports_broad_typing_not_source_endpoint_adjudication():
    """Preserve native/schema provenance and explicitly leave generic Sugar context open."""
    evidence = json.loads(FIXTURE.read_bytes())
    assert evidence["schema_parents"]["food"] == "chemical mixture"
    assert evidence["schema_parents"]["chemical mixture"] == "chemical entity"
    assert len(evidence["statements"]) == 10
    assert [(row["value"], row["object"]) for row in evidence["source_observations"]] == [
        ("sugar", "NCIT:C71939"),
        ("sugar", "NCIT:C71939"),
        ("mucin", "NCIT:C16883"),
    ]
    assert len({row["publications"] for row in evidence["source_observations"]}) == 3
    assert all(row["explanation"] == "NA" for row in evidence["source_observations"])
    assert "mappings/ncit_category_dispositions.tsv" in module.OntologiesStubsTransform.DATA_INPUTS
