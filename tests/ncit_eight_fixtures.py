"""Honest NCIT selected-statement SQLite excerpts for finite category tests."""

import copy
import json
import shutil
import sqlite3
from pathlib import Path

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import ncit_eight_categories as finite

FIXTURE = Path(__file__).parent / "resources/ncit_eight_categories"
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
    shutil.copyfile(model_path or FIXTURE / "biolink.json", raw / "biolink-model.yaml")
    policy = copy.deepcopy(POLICY)
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
