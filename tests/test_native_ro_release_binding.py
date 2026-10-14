"""Native RO authorities bind their release file and reviewed content, not converted bytes (#1420)."""

import copy
import hashlib
import json

import pytest

from kg_microbe.utils import native_ro_retention as native
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.test_native_ro_retention import fixture_policy, frame, prepare

# Production converts RO, PATO and UBERON from an OWL release beside the JSON it
# reads, so the policy binds that OWL file. Only its bytes are checked, so a
# stand-in file exercises the same path as the 21 MB pinned release.
OWL = b'<?xml version="1.0"?>\n<!-- stand-in for the pinned pato.owl release -->\n'
SOURCE_ROLE = "ontology_native_relation_pato_source"


def owl_policy(release=OWL):
    """Bind PATO the production way: to the OWL release file its JSON was converted from."""
    policy = fixture_policy()
    policy["authorities"]["pato.json"]["source"] = {"file": "pato.owl", "sha256": hashlib.sha256(release).hexdigest()}
    return policy


def staged(tmp_path, monkeypatch, *, owl=OWL, policy=None):
    """Stage the fixture authorities, with ``owl`` (or nothing) as the PATO release file."""
    raw = tmp_path / "raw"
    raw.mkdir()
    if owl is not None:
        (raw / "pato.owl").write_bytes(owl)
    return prepare(tmp_path, monkeypatch, sources=(), policy=owl_policy() if policy is None else policy)


def test_a_converted_authority_is_bound_to_its_owl_release(tmp_path, monkeypatch):
    """The OWL release is read as its own consumed input, so its bytes are on record."""
    transform, authority, _ = staged(tmp_path, monkeypatch)
    authority.prepare_source("pato", transform.input_base_dir / "pato.json")
    bound = transform.consumed_input_snapshots[SOURCE_ROLE]
    assert bound["sha256"] == hashlib.sha256(OWL).hexdigest()
    assert bound["path"].endswith("pato.owl")


@pytest.mark.parametrize("owl", [OWL + b"<!-- another release -->\n", None], ids=["changed", "missing"])
def test_a_different_or_missing_owl_release_is_refused(tmp_path, monkeypatch, owl):
    """A JSON whose reviewed content matches cannot stand in for an unreviewed release."""
    transform, authority, _ = staged(tmp_path, monkeypatch, owl=owl)
    with pytest.raises((ValueError, FileNotFoundError)):
        authority.prepare_source("pato", transform.input_base_dir / "pato.json")


def test_a_json_from_another_release_is_refused(tmp_path, monkeypatch):
    """The JSON must declare the reviewed release, even when its selected content is identical."""
    policy = owl_policy()
    policy["authorities"]["pato.json"]["release"] = "http://purl.obolibrary.org/obo/pato/releases/2099-01-01/pato.owl"
    transform, authority, _ = staged(tmp_path, monkeypatch, policy=policy)
    with pytest.raises(ValueError, match="release"):
        authority.prepare_source("pato", transform.input_base_dir / "pato.json")


@pytest.mark.parametrize("name", ["pato", "ro"])
def test_changed_reviewed_content_is_refused(tmp_path, monkeypatch, name):
    """The reviewed assertions and property declarations are bound by their own digest."""
    policy = owl_policy()
    policy["authorities"][name + ".json"]["selected_sha256"] = "a" * 64
    transform, authority, _ = staged(tmp_path, monkeypatch, policy=policy)
    with pytest.raises(ValueError, match="reviewed release content"):
        authority.prepare_source("pato", transform.input_base_dir / "pato.json")


def test_a_changed_reviewed_assertion_in_the_native_json_is_refused(tmp_path, monkeypatch):
    """With no byte pin left, the selected-content digest alone catches a changed reviewed assertion (#1517)."""
    transform, authority, _ = staged(tmp_path, monkeypatch)
    path = transform.input_base_dir / "pato.json"
    document = json.loads(path.read_text())
    edge = next(
        edge for edge in document["graphs"][0]["edges"] if native.compact_identifier(edge["pred"]) in native._RELATIONS
    )
    edge.setdefault("meta", {})["comments"] = ["same triple, changed axiom annotation"]
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="differ from the reviewed release content: pato"):
        authority.prepare_source("pato", path)


@pytest.mark.parametrize("damage", ["dropped", "rebound", "changed"])
def test_admission_requires_the_owl_release_binding(tmp_path, monkeypatch, damage):
    """Finalization and merge admission re-check the release file, not only the converted JSON."""
    transform, authority, audit = staged(tmp_path, monkeypatch)
    authority.prepare_source("pato", transform.input_base_dir / "pato.json")
    rows = frame("pato")
    authority.project("pato", rows, rows, "pato_edges.tsv").to_csv(
        transform.output_dir / "pato_edges.tsv", sep="\t", index=False
    )
    (transform.output_dir / native.AUDIT_FILE).write_text(audit.getvalue())
    snapshots = copy.deepcopy(transform.consumed_input_snapshots)
    native.verify_audit_input_bindings(transform.output_dir, snapshots)
    if damage == "dropped":
        snapshots.pop(SOURCE_ROLE)
    elif damage == "rebound":
        snapshots[SOURCE_ROLE] = snapshots["ontology_native_relation_pato"]
    else:
        (transform.input_base_dir / "pato.owl").write_bytes(OWL + b"<!-- changed after the read -->\n")
    with pytest.raises(SourceFinalizationRequired, match="release"):
        native.verify_audit_input_bindings(transform.output_dir, snapshots)


@pytest.mark.parametrize("linked", ["owl_release", "json_release"])
def test_a_symlinked_release_file_is_admitted_as_it_was_read(tmp_path, monkeypatch, linked):
    """
    A release file reached through a symlink is bound the same way at read time and at finalization (#1645).

    Snapshots record resolved paths, so the target's name is not the policy's file
    name; which file is the release is decided by the policy's names on both sides.
    """
    policy = owl_policy() if linked == "owl_release" else fixture_policy()
    transform, authority, audit = staged(tmp_path, monkeypatch, policy=policy)
    raw = transform.input_base_dir
    name = "pato.owl" if linked == "owl_release" else "pato.json"
    target = raw / ("pato-2026-01-01" + name[4:])
    (raw / name).rename(target)
    (raw / name).symlink_to(target.name)
    authority.prepare_source("pato", raw / "pato.json")
    rows = frame("pato")
    authority.project("pato", rows, rows, "pato_edges.tsv").to_csv(
        transform.output_dir / "pato_edges.tsv", sep="\t", index=False
    )
    (transform.output_dir / native.AUDIT_FILE).write_text(audit.getvalue())
    native.verify_audit_input_bindings(transform.output_dir, copy.deepcopy(transform.consumed_input_snapshots))
