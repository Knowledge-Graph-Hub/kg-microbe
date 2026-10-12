"""Keep native ENVO retirement evidence distinct from the derived KGX conversion member."""

import hashlib
import json
from pathlib import Path

import pytest

from kg_microbe.transform_utils.ontologies import ontologies_transform as module
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.native_ro_fixtures import prepare_empty_native_ro_contract
from tests.prego_identity_fixtures import stage_prego_identity_inputs


def _run(tmp_path, monkeypatch, mutate=None):
    """Exercise the actual preprocessing path while isolating unrelated KGX serialization."""
    raw = tmp_path / "raw"
    stage_prego_identity_inputs(raw)
    transform = module.OntologiesTransform(raw, tmp_path / "output")
    prepare_empty_native_ro_contract(transform)
    original = (raw / "envo.json").read_bytes()
    seen = []

    def kgx(**kwargs):
        """Inspect exactly the derived member which the native transform passes to KGX."""
        path = Path(kwargs["inputs"][0])
        seen.append((path, json.loads(path.read_text())))
        if mutate:
            mutate(raw, path)

    monkeypatch.setattr(module, "_run_kgx_transform", kgx)
    monkeypatch.setattr(transform, "post_process", lambda _name: None)
    transform.parse("envo", raw / "envo.json", "envo")
    return transform, raw, original, seen


def test_native_envo_bytes_and_retirement_declarations_are_preserved(tmp_path, monkeypatch):
    """Filtering affects only a derived member with its own consumed identity."""
    transform, raw, original, seen = _run(tmp_path, monkeypatch)
    assert (raw / "envo.json").read_bytes() == original
    path, processed = seen[0]
    assert path != raw / "envo.json" and path.name == "envo.json"
    assert path.is_relative_to(transform.output_dir)
    assert not any(node.get("meta", {}).get("deprecated") for graph in processed["graphs"] for node in graph["nodes"])
    assert len(json.loads(original)["graphs"][0]["nodes"]) - len(processed["graphs"][0]["nodes"]) == 10
    identities = transform.consumed_input_snapshots
    assert identities["ontology_native_envo"] == {
        "path": str((raw / "envo.json").resolve()),
        "sha256": hashlib.sha256(original).hexdigest(),
    }
    assert identities["ontology_metadata_envo"]["path"] == str(path.resolve())
    assert identities["ontology_metadata_envo"]["sha256"] != identities["ontology_native_envo"]["sha256"]
    transform.verify_consumed_inputs()


@pytest.mark.parametrize("which", ["native", "derived"])
def test_native_or_derived_drift_is_not_restamped(tmp_path, monkeypatch, which):
    """Both conversion input and native authority remain checked after their respective reads."""

    def mutate(raw, derived):
        """Inject a bounded same-size input mutation after the immutable metadata read."""
        path = raw / "envo.json" if which == "native" else derived
        path.write_bytes(path.read_bytes().replace(b"geothermally", b"xeothermally", 1))

    if which == "derived":
        with pytest.raises(SourceFinalizationRequired):
            _run(tmp_path, monkeypatch, mutate)
    else:
        transform, *_ = _run(tmp_path, monkeypatch, mutate)
        with pytest.raises(SourceFinalizationRequired):
            transform.verify_consumed_inputs()


def test_corrupt_previous_derived_cache_is_recreated_from_native(tmp_path, monkeypatch):
    """Derived-cache content and preprocessing results are not trusted on a later invocation."""
    transform, raw, original, seen = _run(tmp_path, monkeypatch)
    derived = seen[0][0]
    derived.write_text('{"corrupted": true}')
    transform.begin_consumed_inputs()
    transform.parse("envo", raw / "envo.json", "envo")
    assert (raw / "envo.json").read_bytes() == original
    assert json.loads(derived.read_text()) == seen[0][1]
