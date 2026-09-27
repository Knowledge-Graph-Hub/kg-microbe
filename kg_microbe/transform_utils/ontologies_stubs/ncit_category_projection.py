"""Project two reviewed native NCIT concepts, never a whole semantic-type vocabulary."""

import csv
import re
from pathlib import Path

from kg_microbe.transform_utils.constants import CHEMICAL_CATEGORY, FOOD_CATEGORY

REVIEWED_CATEGORIES = {"NCIT:C71939": FOOD_CATEGORY, "NCIT:C16883": CHEMICAL_CATEGORY}
FIELDS = ["id", "label", "semantic_type", "named_parent", "definition", "category"]
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")


def native_contract(selected, resolved, sha256):
    """Serialize the producer's selected locator, exact bytes and complete absent-sidecar set."""
    sidecars = sorted(
        {str(path.with_name(path.name + suffix)) for path in (selected, resolved) for suffix in SQLITE_SIDECARS}
    )
    return {
        "version": 1,
        "authority": {
            "selected_path": str(selected),
            "resolved_path": str(resolved),
            "sha256": sha256,
            "absent_sqlite_sidecars": sidecars,
        },
    }


def validate_native_contract(contract, raw_dir, snapshots, ncit_nodes, *, admission=None, expected_member=None):
    """Validate the finite NCIT contract without adapters, retaining guards in public admission."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.graph_schema import REQUIRED_NODE_COLUMNS
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows

    def reject(reason):
        """Use the public finalization error type for every malformed or stale native contract."""
        raise SourceFinalizationRequired(f"NCIT native authority contract: {reason}; rerun ontologies_stubs")

    if (
        not isinstance(contract, dict)
        or set(contract) != {"version", "authority"}
        or type(contract["version"]) is not int
        or contract["version"] != 1
    ):
        reject("missing or malformed version/fields")
    if not isinstance(raw_dir, (str, Path)) or not str(raw_dir) or not isinstance(snapshots, dict):
        reject("missing or malformed raw directory/consumed snapshots")
    retained = admission if admission is not None else SourceAdmission()
    authority = contract["authority"]
    if authority is None:
        if "ncit_category_authority" in snapshots:
            reject("null authority contradicts the recorded native consumption")
        # The normal producer emits this canonical member even for no NCIT CURIEs.
        # Bind it before inspection, so changing the null-eligibility proof later fails.
        if ncit_nodes is None or Path(ncit_nodes).name != "ncit_nodes.tsv":
            reject("null authority requires the canonical NCIT output")
        identity = retained.capture(ncit_nodes)
        if expected_member is not None and identity != expected_member:
            reject("null-authority NCIT output changed")
        with Path(ncit_nodes).open(encoding="utf-8", newline="") as stream:
            header = next(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE), [])
        if len(header) != len(set(header)) or not REQUIRED_NODE_COLUMNS.issubset(header):
            reject("NCIT output is missing canonical node columns")
        for row in graph_rows(ncit_nodes):
            if "id" not in row:
                reject("NCIT output is missing its identifier column")
            if row["id"] in REVIEWED_CATEGORIES:
                reject("reviewed NCIT concept lacks native evidence")
        retained.verify(metadata_only=True)
        return retained
    if not isinstance(authority, dict) or set(authority) != {
        "selected_path",
        "resolved_path",
        "sha256",
        "absent_sqlite_sidecars",
    }:
        reject("malformed authority fields")
    if any(
        not isinstance(authority[key], str) or not authority[key]
        for key in ("selected_path", "resolved_path", "sha256")
    ):
        reject("untyped locator/hash")
    if re.fullmatch(r"[0-9a-f]{64}", authority["sha256"]) is None:
        reject("invalid authority digest")
    selected, resolved, raw = (
        Path(authority["selected_path"]),
        Path(authority["resolved_path"]),
        Path(raw_dir).resolve(),
    )
    if any(not path.is_absolute() or ".." in path.parts for path in (selected, resolved)):
        reject("authority locators must be absolute without traversal")
    if selected.name != "ncit.db" or selected.parent.resolve() != raw or not resolved.is_relative_to(raw):
        reject("authority is outside the selected raw directory")
    if resolved != resolved.resolve() or selected.resolve() != resolved:
        reject("selected native locator changed")
    expected = native_contract(selected, resolved, authority["sha256"])["authority"]
    if authority != expected:
        reject("sidecar absence set is not the complete derived set")
    if snapshots.get("ncit_category_authority") != {"path": str(resolved), "sha256": authority["sha256"]}:
        reject("authority does not match the original consumed snapshot")
    for name in expected["absent_sqlite_sidecars"]:
        path = Path(name)
        if path.exists() or path.is_symlink():
            reject(f"SQLite sidecar exists: {name}")
        retained.capture(path, optional=True)
    if retained.capture(selected)["sha256"] != authority["sha256"]:
        reject("consumed native bytes changed")
    retained.verify(metadata_only=True)
    return retained


def read_dispositions(stream):
    """Require the complete finite policy, rejecting duplicate or expanded scope."""
    reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
    if reader.fieldnames != FIELDS:
        raise ValueError("Invalid NCIT category disposition header")
    rows = {}
    for row in reader:
        if None in row or any(not value for value in row.values()):
            raise ValueError("Incomplete NCIT category disposition")
        curie = row["id"]
        if curie in rows or row["category"] != REVIEWED_CATEGORIES.get(curie):
            raise ValueError(f"Unreviewed or duplicate NCIT category disposition: {curie}")
        rows[curie] = row
    if rows.keys() != REVIEWED_CATEGORIES.keys():
        raise ValueError("Missing reviewed NCIT category disposition")
    return rows


def _values(metadata, *predicates):
    """Keep direct native annotation values typed and exact, without coercion or inference."""
    values = set()
    for predicate in predicates:
        selected = metadata.get(predicate, [])
        if not isinstance(selected, (list, tuple)) or any(not isinstance(value, str) for value in selected):
            raise ValueError(f"Malformed NCIT native evidence: {predicate}")
        values.update(selected)
    return values


def project_category(adapter, curie, disposition):
    """Authorize a finite projection only when every reviewed native fact still agrees."""
    metadata = adapter.entity_metadata_map(curie, include_all_triples=True)
    if not isinstance(metadata, dict):
        raise ValueError(f"Missing NCIT native evidence: {curie}")
    observed = {
        "label": _values(metadata, "rdfs:label", "http://www.w3.org/2000/01/rdf-schema#label"),
        "semantic_type": _values(metadata, "NCIT:P106", "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#P106"),
        "definition": _values(metadata, "IAO:0000115", "http://purl.obolibrary.org/obo/IAO_0000115"),
        "named_parent": {
            value
            for value in _values(metadata, "rdfs:subClassOf", "http://www.w3.org/2000/01/rdf-schema#subClassOf")
            if not value.startswith("_:")
        },
    }
    for field, values in observed.items():
        if values != {disposition[field]}:
            raise ValueError(f"NCIT category evidence changed for {curie}: {field}")
    return disposition["category"]
