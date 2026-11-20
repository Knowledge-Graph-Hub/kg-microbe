"""Hermetic preservation and failure controls for historical closure capture."""

import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import reconcile_historical_kgm_source as closure

# Independent historical topology, including the stubs dependency from review #1887.
EXPECTED_UPSTREAM = {
    "mediadive": ("ontologies", "bacdive"),
    "metatraits": ("ontologies",),
    "metatraits_gtdb": ("ontologies", "gtdb"),
    "microbedecoder": ("lpsn", "gold", "gtdb", "ontologies"),
    "bacdive": ("ontologies",),
    "lpsn": ("ontologies", "gtdb"),
    "gold": ("ontologies", "ontologies_stubs"),
    "gtdb": ("ontologies",),
    "ontologies": (),
    "ontologies_stubs": ("ontologies",),
}


def sha(path):
    """Hash the tiny immutable fixture bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path, value):
    """Write explicitly synthetic evidence and return exact byte metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def selected(tmp_path):
    """Build tiny graph members with a stand-in external row proof, never scientific acceptance."""
    root, frozen = tmp_path / "kg", tmp_path / "historical"
    root.mkdir()
    frozen.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)  # noqa: S603,S607
    export = "data/rebuild-evidence/fixture/official-export"
    products = {}
    for name in closure.PRODUCTS:
        products[name] = put(root / export / name, ("synthetic " + name + "\n").encode())["sha256"]
    manifest = {
        "schema_version": 1,
        "semantic_status": "PASS_SUPPORTED_SUBSET",
        "source_sssom": "mappings/ingredient_mappings.sssom.tsv",
        "source_sha256": "a" * 64,
        "review_sha256": "b" * 64,
        "files": products,
    }
    export_manifest = put(root / export / "manifest.json", manifest)
    pin = {
        "schema_version": 2,
        "mode": "candidate_only",
        "origin": "immutable_commit_export",
        "source_commit": "c" * 40,
        "manifest_sha256": export_manifest["sha256"],
        "files": products,
        "source_archive": {
            "url": "https://codeload.github.com/CultureBotAI/MediaIngredientMech/tar.gz/" + "c" * 40,
            "sha256": "d" * 64,
        },
    }
    put(root / closure.PIN_PATH, pin)
    proposed = "data/rebuild-evidence/fixture/proposed-immutable-pin-r1.json"
    put(root / proposed, pin)
    supported = root / "mappings/ingredient_mappings.sssom.tsv"
    supported.write_bytes((root / export / "ingredient_mappings.sssom.tsv").read_bytes())
    put(root / closure.UNIFIED_PATH, b"synthetic independent unified bytes\n")
    put(root / "data/raw/authority.tsv", b"id\tname\nX:1\tsynthetic\n")
    upstream_markers = {}

    def upstream_marker(source):
        """Build independent fixture marker dependencies from the reviewed historical topology."""
        if source not in upstream_markers:
            h = hashlib.sha256()
            for name in sorted(EXPECTED_UPSTREAM[source]):
                h.update(name.encode() + b"\0" + json.dumps(upstream_marker(name), sort_keys=True).encode() + b"\0")
            value = {"version": 3, "synthetic_marker": source, "upstream": h.hexdigest()}
            upstream_markers[source] = value
            put(root / "data/transformed" / source / "source_fingerprint.json", value)
        return upstream_markers[source]

    for source in set(EXPECTED_UPSTREAM) - set(closure.SOURCES):
        upstream_marker(source)
    old = {}

    def freeze(name):
        path = root / name
        target = frozen / "snapshots" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        old["snapshots/" + name] = {"bytes": path.stat().st_size, "sha256": sha(path)}

    graphs = {}
    deps = ["data/raw/authority.tsv", "mappings/ingredient_mappings.sssom.tsv", closure.UNIFIED_PATH]
    for source in closure.SOURCES:
        base = "data/transformed/" + source + "/"
        members = {}
        for name, data in (
            ("nodes.tsv", b"id\tcategory\tname\nX:1\tbiolink:ChemicalEntity\tsynthetic\n"),
            ("edges.tsv", b"subject\tpredicate\tobject\nX:1\tskos:closeMatch\tY:1\n"),
        ):
            members[name] = put(root / base / name, data)
            graphs[base + name] = {
                **members[name],
                "row_count": 1,
                "columns": data.split(b"\n", 1)[0].decode().split("\t"),
            }
        audit = put(root / base / "source_reference_resolution.tsv", b"id\tdisposition\nX:1\tretained\n")
        inputs = [{"path": str(root / name), "sha256": sha(root / name)} for name in deps]
        receipt = {
            "version": 2,
            "source": source,
            "tsv_quoting": "none",
            "members": members,
            "audit_members": {"source_reference_resolution.tsv": audit},
            "producer_audit_members": {},
            "inputs": inputs,
            "consumed_inputs": {"authority": inputs[0]},
            "declared_data_inputs": deps,
            "producer_code": {"directory": str(root / "kg_microbe" / source), "fingerprint": "e" * 64},
            "finalizer_code": "f" * 64,
            "summaries": {"rows": {"nodes": 1, "edges": 1}},
        }
        put(root / base / "source_finalization.json", receipt)
        h = hashlib.sha256()
        for name in sorted(deps):
            h.update(name.encode() + b"\0" + bytes.fromhex(sha(root / name)) + b"\0")
        upstream = hashlib.sha256()
        for name in sorted(EXPECTED_UPSTREAM[source]):
            upstream.update(name.encode() + b"\0" + json.dumps(upstream_markers[name], sort_keys=True).encode() + b"\0")
        marker = {
            "version": 3,
            "code": "e" * 64,
            "shared": "f" * 64,
            "finalization_inputs": sorted(deps),
            "finalization_data": h.hexdigest(),
            "upstream": upstream.hexdigest(),
        }
        put(root / base / "source_fingerprint.json", marker)
        for name in ("nodes.tsv", "source_finalization.json", "source_fingerprint.json"):
            freeze(base + name)
    for name in (
        *[export + "/" + name for name in closure.PRODUCTS | {"manifest.json"}],
        proposed,
        "mappings/ingredient_mappings.sssom.tsv",
        closure.UNIFIED_PATH,
    ):
        freeze(name)
    subprocess.run(["git", "-C", str(root), "add", closure.PIN_PATH], check=True)  # noqa: S603,S607
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture.invalid",
            "commit",
            "-qm",
            "pin reviewed release",
        ],
        check=True,
    )
    revision = closure.head(root)
    historical = {
        "schema_version": 1,
        "upstream_root": str(root),
        "upstream_revision": revision,
        "mim_revision": "c" * 40,
        "files": old,
        "consumed_reviewed": {
            "directory": "snapshots/" + export,
            "source_commit": "c" * 40,
            "manifest_sha256": export_manifest["sha256"],
            "files": {**products, "manifest.json": export_manifest["sha256"]},
        },
    }
    historical_path = frozen / "source-manifest.json"
    historical_meta = put(historical_path, historical)
    proof_path = tmp_path / "row-evidence/proof.json"
    outputs = {}
    for name, count in (("full-row-ledger.json", 5740), ("full-row-ledger.tsv", 5740), ("full-node-ledger.json", 507)):
        data = (
            (b"source\tfixture\n" + b"synthetic\ttrue\n" * count)
            if name.endswith(".tsv")
            else [{"fixture": i} for i in range(count)]
        )
        outputs[name] = {**put(proof_path.parent / name, data), "row_count": count}
    proof = {
        "schema_version": 1,
        "status": "PASS_HISTORICAL_SOURCE_ROW_RECONCILIATION",
        "historical_manifest_sha256": historical_meta["sha256"],
        "kgm_root": str(root),
        "kgm_revision": revision,
        "selected_sources": list(closure.SOURCES),
        "graph_members": graphs,
        "counts": {
            "kg_source_ids": 507,
            "provider_cases": 549,
            "kg_occurrences": 5740,
            "shared_metatraits_gtdb_ids": 42,
        },
        "provider_counts": {
            "mediadive": {"cases": 415, "occurrences": 5332},
            "metatraits": {"cases": 82, "occurrences": 120},
            "metatraits_gtdb": {"cases": 42, "occurrences": 63},
            "microbedecoder": {"cases": 10, "occurrences": 225},
        },
        "all_native_kg_rows_accounted": True,
        "exact_combined_projection": True,
        "all_inputs_unchanged": True,
        "production_admission": False,
        "scientific_approval": False,
        "inputs_before": {str(historical_path): historical_meta},
        "inputs_after": {str(historical_path): historical_meta},
        "outputs": outputs,
    }
    proof_meta = put(proof_path, proof)
    return {
        "root": root,
        "revision": revision,
        "historical_manifest": historical_path,
        "historical_sha256": historical_meta["sha256"],
        "row_reconciliation": proof_path,
        "row_reconciliation_sha256": proof_meta["sha256"],
        "output": tmp_path / "new-closure",
    }


def test_complete_closure_preserves_inputs_and_independent_members(selected):
    """New copies expand metadata while the historical receipt and source bytes stay intact."""
    roots = (selected["root"], selected["historical_manifest"].parent)
    before = {
        str(p): (sha(p), p.stat().st_ino)
        for root in roots
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }
    result = closure.collect(**selected)
    assert result["schema_version"] == 1
    assert result["consumed_reviewed"] == json.loads(selected["historical_manifest"].read_text())["consumed_reviewed"]
    assert selected["output"].joinpath("source-manifest.json").is_file()
    for source in closure.SOURCES:
        for name in ("nodes.tsv", "edges.tsv", "source_reference_resolution.tsv"):
            rel = "data/transformed/" + source + "/" + name
            copied = selected["output"] / "snapshots" / rel
            original = selected["root"] / rel
            assert copied.read_bytes() == original.read_bytes()
            assert copied.stat().st_ino != original.stat().st_ino
    assert before == {name: (sha(Path(name)), Path(name).stat().st_ino) for name in before}
    audit = json.loads((selected["output"] / "closure-audit.json").read_text())
    assert audit["status"] == "HISTORICAL_CLOSURE_ONLY_NOT_RELEASE_ADMISSION"
    assert audit["prego_habitat"] == "diagnostic_only_unselected"
    assert audit["prior_consumed_release"]["scope"] == "prior_consumed_input_only"
    assert "evidence/row-reconciliation/full-row-ledger.tsv" in result["files"]
    assert set(result["destination_verification"]) == set(result["files"])
    assert all(
        result["destination_verification"][name]["sha256"] == value["sha256"] for name, value in result["files"].items()
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing_graph",
        "missing_audit",
        "graph_drift",
        "dependency_drift",
        "frozen_drift",
        "current_snapshot_drift",
        "prior_pin_drift",
        "ledger_drift",
    ],
)
def test_failed_member_checks_leave_no_final_receipt(selected, change):
    """No incomplete or drifting copy becomes a final source receipt."""
    root = selected["root"]
    paths = {
        "missing_graph": root / "data/transformed/mediadive/edges.tsv",
        "missing_audit": root / "data/transformed/mediadive/source_reference_resolution.tsv",
        "graph_drift": root / "data/transformed/metatraits/edges.tsv",
        "dependency_drift": root / "data/raw/authority.tsv",
        "frozen_drift": selected["historical_manifest"].parent / "snapshots/data/transformed/mediadive/nodes.tsv",
        "current_snapshot_drift": root / "data/transformed/mediadive/nodes.tsv",
        "prior_pin_drift": root / closure.PIN_PATH,
        "ledger_drift": selected["row_reconciliation"].parent / "full-row-ledger.tsv",
    }
    path = paths[change]
    if change.startswith("missing"):
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"changed\n")
    with pytest.raises((ValueError, FileNotFoundError)):
        closure.collect(**selected)
    assert not (selected["output"] / "source-manifest.json").exists()


@pytest.mark.parametrize("member", ["../outside", "/absolute", "snapshots/../outside", "snapshots\\escape"])
def test_unsafe_historical_member_is_refused(selected, member):
    """A newly pinned manifest cannot escape its input or output member root."""
    historical = json.loads(selected["historical_manifest"].read_text())
    historical["files"][member] = {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}
    selected["historical_sha256"] = put(selected["historical_manifest"], historical)["sha256"]
    with pytest.raises(ValueError, match="unsafe relative"):
        closure.collect(**selected)
    assert not (selected["output"] / "source-manifest.json").exists()


@pytest.mark.parametrize(
    "change", ["missing_graph", "wrong_count", "scope", "approval", "input_guard", "wrong_graph_hash"]
)
def test_rehashed_proof_cannot_change_selected_accounting(selected, change):
    """An explicit external proof pin still requires exact scope, byte joins and authority limits."""
    proof = json.loads(selected["row_reconciliation"].read_text())
    if change == "missing_graph":
        proof["graph_members"].pop(next(iter(proof["graph_members"])))
    elif change == "wrong_count":
        proof["counts"]["kg_occurrences"] -= 1
    elif change == "scope":
        proof["selected_sources"].append("prego_habitat")
    elif change == "approval":
        proof["production_admission"] = True
    elif change == "input_guard":
        proof["inputs_after"] = {}
    else:
        proof["graph_members"][next(iter(proof["graph_members"]))]["sha256"] = "0" * 64
    selected["row_reconciliation_sha256"] = put(selected["row_reconciliation"], proof)["sha256"]
    with pytest.raises(ValueError, match="row proof"):
        closure.collect(**selected)
    assert not (selected["output"] / "source-manifest.json").exists()


def test_existing_output_is_preserved(selected):
    """Rerunning capture never overwrites an existing evidence directory."""
    selected["output"].mkdir()
    marker = selected["output"] / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="output must not exist"):
        closure.collect(**selected)
    assert marker.read_text() == "keep"


def test_late_input_drift_refuses_publication(selected, monkeypatch):
    """Inputs are checked again after the independent copies and proof have been prepared."""
    original = closure.Capture.verify

    def drift(capture):
        (selected["root"] / "data/raw/authority.tsv").write_text("late drift\n")
        original(capture)

    monkeypatch.setattr(closure.Capture, "verify", drift)
    with pytest.raises(ValueError, match="input changed before publication"):
        closure.collect(**selected)
    assert not (selected["output"] / "source-manifest.json").exists()


def test_symlink_dependency_is_refused(selected, tmp_path):
    """Matching target bytes do not authorize reading through an aliased dependency locator."""
    original = selected["root"] / "data/raw/authority.tsv"
    target = tmp_path / "aliased-authority.tsv"
    original.rename(target)
    original.symlink_to(target)
    with pytest.raises(ValueError, match="aliased path|symlink"):
        closure.collect(**selected)
    assert not (selected["output"] / "source-manifest.json").exists()


def repin_proof(selected, proof):
    """Select intentionally changed synthetic row evidence by its new exact bytes."""
    selected["row_reconciliation_sha256"] = put(selected["row_reconciliation"], proof)["sha256"]


@pytest.mark.parametrize(
    "name",
    [
        "source-manifest.json",
        "closure-audit.json",
        "evidence/row-reconciliation.json",
        "evidence/parent-source-manifest.json",
        "evidence/row-reconciliation/other.tsv",
    ],
)
def test_reserved_historical_names_refuse_before_any_copy(selected, name):
    """An input cannot prepopulate final receipt or generated evidence locations."""
    historical = json.loads(selected["historical_manifest"].read_text())
    historical["files"][name] = {"bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}
    selected["historical_sha256"] = put(selected["historical_manifest"], historical)["sha256"]
    with pytest.raises(ValueError, match="reserved historical member"):
        closure.collect(**selected)
    assert list(selected["output"].iterdir()) == []


@pytest.mark.parametrize("target", ["gold", "ontologies_stubs"])
def test_transitive_marker_must_verify_its_own_dependencies(selected, target):
    """Re-pinning selected markers cannot hide a coherently forwarded stale transitive marker."""
    root = selected["root"]
    path = root / "data/transformed" / target / "source_fingerprint.json"
    bad = json.loads(path.read_text())
    bad["upstream"] = "0" * 64
    put(path, bad)
    ancestors = ("gold", "microbedecoder") if target == "ontologies_stubs" else ("microbedecoder",)
    for source in ancestors:
        path = root / "data/transformed" / source / "source_fingerprint.json"
        value = json.loads(path.read_text())
        h = hashlib.sha256()
        for name in sorted(EXPECTED_UPSTREAM[source]):
            dependency = json.loads((root / "data/transformed" / name / "source_fingerprint.json").read_text())
            h.update(name.encode() + b"\0" + json.dumps(dependency, sort_keys=True).encode() + b"\0")
        value["upstream"] = h.hexdigest()
        put(path, value)
    historical = json.loads(selected["historical_manifest"].read_text())
    name = "snapshots/data/transformed/microbedecoder/source_fingerprint.json"
    metadata = put(selected["historical_manifest"].parent / name, (root / name.removeprefix("snapshots/")).read_bytes())
    historical["files"][name] = metadata
    hmeta = put(selected["historical_manifest"], historical)
    selected["historical_sha256"] = hmeta["sha256"]
    proof = json.loads(selected["row_reconciliation"].read_text())
    proof["historical_manifest_sha256"] = hmeta["sha256"]
    proof["inputs_before"] = proof["inputs_after"] = {str(selected["historical_manifest"]): hmeta}
    repin_proof(selected, proof)
    with pytest.raises(ValueError, match="recursive upstream fingerprint changed: " + target):
        closure.collect(**selected)
    assert not (selected["output"] / "source-manifest.json").exists()


@pytest.mark.parametrize("change", ["omit", "extra"])
def test_row_proof_requires_all_three_exact_ledgers(selected, change):
    """A nonempty output map cannot replace the reviewed ledger closure."""
    proof = json.loads(selected["row_reconciliation"].read_text())
    if change == "omit":
        proof["outputs"].pop("full-node-ledger.json")
    else:
        proof["outputs"]["other.json"] = proof["outputs"]["full-node-ledger.json"]
    repin_proof(selected, proof)
    with pytest.raises(ValueError, match="supporting ledger closure"):
        closure.collect(**selected)
    assert not (selected["output"] / "source-manifest.json").exists()


@pytest.mark.parametrize("name", ["full-row-ledger.json", "full-row-ledger.tsv", "full-node-ledger.json"])
def test_actual_ledger_rows_must_match_claimed_count(selected, name):
    """A newly selected ledger digest does not conceal a missing parsed record."""
    path = selected["row_reconciliation"].parent / name
    if name.endswith(".json"):
        rows = json.loads(path.read_text())
        rows.pop()
        actual = put(path, rows)
    else:
        actual = put(path, path.read_bytes().rsplit(b"\n", 2)[0] + b"\n")
    proof = json.loads(selected["row_reconciliation"].read_text())
    proof["outputs"][name].update(actual)
    repin_proof(selected, proof)
    with pytest.raises(ValueError, match="parsed row ledger count differs"):
        closure.collect(**selected)
    assert not (selected["output"] / "source-manifest.json").exists()


def test_ledger_counter_preserves_quoted_multiline_rows(tmp_path):
    """A literal newline in one TSV cell remains one record."""
    import csv

    value = io.StringIO(newline="")
    writer = csv.writer(value, delimiter="\t")
    writer.writerow(["id", "literal"])
    writer.writerow(["x", "first\nsecond\tthird"])
    writer.writerow(["y", 'a "quote"'])
    path = tmp_path / "full-row-ledger.tsv"
    path.write_text(value.getvalue())
    assert closure.ledger_rows(path, 2) == 2


@pytest.mark.parametrize("short_write", [False, True])
def test_independent_destination_readback_detects_copy_corruption(selected, monkeypatch, short_write):
    """Corruption present before identity capture still fails the independent destination digest."""
    original_open = Path.open
    target = selected["output"] / "snapshots/data/transformed/mediadive/edges.tsv"
    source = selected["root"] / "data/transformed/mediadive/edges.tsv"
    before = sha(source)

    class CorruptWriter:
        """Simulate a faulty destination writer while input reads remain exact."""

        def __init__(self, stream):
            """Keep the actual exclusive output handle."""
            self.stream = stream

        def write(self, data):
            """Damage bytes before the collector records destination identity."""
            return self.stream.write(data[1:] if short_write else b"!" + data[1:])

        def close(self):
            """Flush and close the underlying output."""
            self.stream.close()

    def corrupt_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return CorruptWriter(stream) if path == target and args and args[0] == "xb" else stream

    monkeypatch.setattr(Path, "open", corrupt_open)
    with pytest.raises(ValueError, match="destination bytes or hash differ"):
        closure.collect(**selected)
    assert sha(source) == before
    assert not (selected["output"] / "source-manifest.json").exists()


@pytest.mark.parametrize("refuse", [False, True])
def test_large_ledger_fields_restore_csv_limit_on_success_and_refusal(tmp_path, refuse):
    """Complete raw/combined context may exceed the default CSV limit without leaking a new limit."""
    import csv

    text = io.StringIO(newline="")
    writer = csv.writer(text, delimiter="\t")
    writer.writerow(["id", "full_row_json"])
    writer.writerow(["row106", json.dumps({"raw": "x" * 140000, "combined": "y" * 140000})])
    path = tmp_path / "full-row-ledger.tsv"
    path.write_text(text.getvalue())
    original = csv.field_size_limit(64)
    try:
        if refuse:
            with pytest.raises(ValueError, match="too many row ledger entries"):
                closure.ledger_rows(path, 0)
        else:
            assert closure.ledger_rows(path, 1) == 1
        assert csv.field_size_limit() == 64
    finally:
        csv.field_size_limit(original)
