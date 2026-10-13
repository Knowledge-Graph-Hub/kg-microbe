"""
Real zero-cohort native-RO contracts for inert dependency-chain fixtures.

ENVO is also a native RO supplier (#1400): a selected ENVO input must carry its
exact reviewed RO cohort, and RO itself must be prepared. ``stage_native_ro_envo``
adds the separately verified native RO excerpt (the two reviewed assertions and
their endpoint declarations) to an existing genuine ENVO excerpt and binds both
files through an explicit fixture-only policy pin, as
``tests/test_native_ro_retention.fixture_policy`` does. The reviewed cohort
itself is unchanged; this is not a production escape hatch.
"""

import copy
import hashlib
import json
import shutil
from pathlib import Path

from kg_microbe.utils import native_ro_retention as native
from kg_microbe.utils.native_ro_retention import AUDIT_FILE, NativeROPredicateRetention
from tests.foodon_kernel_fixtures import prepare_empty_foodon_kernel_contract
from tests.ontology_parent_fixtures import prepare_empty_parent_contract


def prepare_empty_native_ro_contract(transform):
    """Exercise the real policy reader and mandatory empty audit for a fixture with no RO assertions."""
    prepare_empty_foodon_kernel_contract(transform)
    prepare_empty_parent_contract(transform)
    from tests.upa_route_fixtures import prepare_empty_upa_route_contract

    prepare_empty_upa_route_contract(transform)
    with (transform.output_dir / AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        authority = NativeROPredicateRetention(transform, stream)
        authority.verify_complete()
    transform.record_producer_audit(AUDIT_FILE)
    return (
        "ontology_native_relation_policy",
        "ontology_foodon_kernel_policy",
        "ontology_parent_disposition_policy",
        "upa_route_policy",
    )


NATIVE_RO_FIXTURE = Path(__file__).parent / "resources/native_ro_retention"
POLICY_NAME = "native_ro_fixture_policy.json"


def stage_native_ro_envo(raw: Path) -> Path:
    """Add the reviewed native RO ENVO cohort to ``raw/envo.json`` and pin it with ``raw/ro.json``."""
    origin = json.loads((NATIVE_RO_FIXTURE / "origin.json").read_text())
    for filename in ("ro.json", "envo.json"):
        content = (NATIVE_RO_FIXTURE / filename).read_bytes()
        assert hashlib.sha256(content).hexdigest() == origin["native_files"][filename]["fixture_sha256"]
    shutil.copyfile(NATIVE_RO_FIXTURE / "ro.json", raw / "ro.json")
    supplier = json.loads((NATIVE_RO_FIXTURE / "envo.json").read_text())["graphs"][0]
    document = json.loads((raw / "envo.json").read_text())
    graph = document["graphs"][0]
    assert graph["id"] == supplier["id"]
    present = {node["id"]: node for node in graph["nodes"]}
    for node in supplier["nodes"]:
        if node["id"] in present:
            assert present[node["id"]] == node, f"Conflicting native ENVO declaration: {node['id']}"
        else:
            graph["nodes"].append(node)
    edges = {(edge["sub"], edge["pred"], edge["obj"]) for edge in graph["edges"]}
    graph["edges"].extend(edge for edge in supplier["edges"] if (edge["sub"], edge["pred"], edge["obj"]) not in edges)
    # The combined excerpt is still from the reviewed ENVO release.
    graph.setdefault("meta", {})["version"] = supplier["meta"]["version"]
    (raw / "envo.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")

    policy = copy.deepcopy(json.loads(native.POLICY_FILE.read_text()))
    for filename in ("ro.json", "envo.json"):
        authority = policy["authorities"][filename]
        [staged] = json.loads((raw / filename).read_text())["graphs"]
        assert staged["meta"]["version"] == authority["release"]
        assert native.selected_content_sha256(filename[:-5], staged) == authority["selected_sha256"]
        authority["source"] = {"file": filename, "sha256": hashlib.sha256((raw / filename).read_bytes()).hexdigest()}
    path = raw.parent / POLICY_NAME
    path.write_text(json.dumps(policy))
    return path


def bind_native_ro_fixture_policy(raw: Path, monkeypatch=None) -> None:
    """
    Point the native RO authority at the fixture policy staged beside ``raw``.

    Subprocess scripts bind for their whole lifetime; in-process tests pass
    ``monkeypatch`` so the binding ends with the test.
    """
    path = Path(raw).parent / POLICY_NAME
    digest = native._digest(native._json(json.loads(path.read_text())).encode())
    if monkeypatch is None:
        native.POLICY_FILE = path
        native.REVIEWED_POLICY_SHA256 = digest
    else:
        monkeypatch.setattr(native, "POLICY_FILE", path)
        monkeypatch.setattr(native, "REVIEWED_POLICY_SHA256", digest)
