"""Honest NCIT selected-statement SQLite excerpts for finite category tests."""

import copy
import json
import shutil
import sqlite3
from pathlib import Path

import yaml

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import ncit_eight_categories as finite

FIXTURE = Path(__file__).parent / "resources/ncit_eight_categories"
CURRENT_MODEL_FIXTURE = Path(__file__).parent / "resources/biolink_4_4_6"
POLICY = json.loads(finite.POLICY_FILE.read_text())
NATIVE = json.loads((FIXTURE / "native.json").read_text())
SOURCE_ROWS = json.loads((FIXTURE / "source_declarations.json").read_text())


def seed_native_authority(tmp_path, monkeypatch, *, model_path=None):
    """Create literal selected SQLite statements and explicitly repin only the private fixture model."""
    # Policy version 2 binds the selected statements, not ncit.db's bytes (#1420), so the
    # excerpt database needs no repin. The reviewed release is provenance only.
    assert POLICY["native_reviewed_release"] == NATIVE["origin"]["authority_release"]
    assert POLICY["native_statements"] == NATIVE["statements"]
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    with sqlite3.connect(raw / "ncit.db") as connection:
        connection.execute("CREATE TABLE statements(subject,predicate,object,value,datatype,language)")
        connection.executemany(
            "INSERT INTO statements VALUES(?,?,?,?,?,?)",
            [
                (identifier, *(row[column] for column in ("predicate", "object", "value", "datatype", "language")))
                for identifier, rows in NATIVE["statements"].items()
                for row in rows
            ],
        )
        # A SemSQL build stamps its release on the ontology node, as the reviewed ncit.db does.
        connection.execute(
            "INSERT INTO statements VALUES(?,?,?,?,?,?)",
            ("obo:ncit.owl", "owl:versionInfo", None, NATIVE["origin"]["authority_release"], None, None),
        )
    selected_model = model_path or CURRENT_MODEL_FIXTURE / "ncit_eight_categories-classes.json"
    shutil.copyfile(selected_model, raw / "biolink-model.yaml")
    model = yaml.safe_load((raw / "biolink-model.yaml").read_text())
    policy = copy.deepcopy(POLICY)
    if model["version"] == "4.4.2":
        # Historical ingredient acceptance keeps its real 4.4.2 model. Restore
        # the original reviewed model binding from immutable historical bytes,
        # and prove the entire old policy before binding private fixture bytes.
        historical = json.loads((FIXTURE / "biolink.json").read_text())
        origin = json.loads((CURRENT_MODEL_FIXTURE / "origin.json").read_text())
        native_origin = json.loads(
            (FIXTURE.parent / "ingredient_bundle/native/acceptance-native-origin.json").read_text()
        )
        assert {key: model["classes"][key] for key in historical["classes"]} == historical["classes"]
        policy.pop("model_review")
        policy.update(
            model_classes=historical["classes"],
            model_version=historical["version"],
            model_sha256=native_origin["members"]["biolink-model.yaml"]["sha256"],
        )
        assert (
            finite.digest(finite.canonical(policy).encode())
            == origin["historical_policy_canonical_sha256"]["ncit_eight_categories"]
        )
    else:
        assert model["version"] == policy["model_version"] == "4.4.6"
        assert {key: model["classes"][key] for key in policy["model_classes"]} == policy["model_classes"]
    policy["model_sha256"] = finite.digest((raw / "biolink-model.yaml").read_bytes())
    policy_file = tmp_path / "ncit_eight_categories.json"
    policy_file.write_text(json.dumps(policy))
    monkeypatch.setattr(finite, "POLICY_FILE", policy_file)
    monkeypatch.setattr(finite, "POLICY_SHA256", finite.digest(finite.canonical(policy).encode()))
    return raw, policy_file, policy


def prepare(tmp_path, monkeypatch):
    """Create an actual snapshot-consuming transform over the immutable native fixture."""
    raw, policy_file, policy = seed_native_authority(tmp_path, monkeypatch)
    transform = Transform("fixture", raw, tmp_path / "transformed")
    transform.TSV_QUOTING = 3

    def opener(path):
        """Exercise the actual consumed immutable snapshot implementation."""
        return transform.consume_input("category_authority_" + path.stem, path)

    authority = finite.FiniteNcitCategoryAuthority(raw, opener=opener)
    return raw, policy_file, policy, transform, authority
