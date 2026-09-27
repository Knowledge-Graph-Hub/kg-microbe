"""Real registered source gates retain finite NCIT authority evidence after completion (#1192)."""

import copy
import gzip
import json
import os
import shutil
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _child(root):
    """Publish fixture outputs with unchanged finalizer/marker/public APIs, never a live adapter."""
    sys.path.insert(0, str(root))

    def offline(*args, **kwargs):
        """Fail any accidental live-service lookup in this subprocess too."""
        raise RuntimeError("network forbidden in NCIT regression")

    socket.socket.connect = offline
    import oaklib

    import kg_microbe.transform as dispatcher
    from kg_microbe.merge_utils.source_freshness import verify_source_freshness
    from kg_microbe.transform_utils.ontologies_stubs import ontologies_stubs_transform as module
    from kg_microbe.utils import source_finalization as finalization

    evidence = json.loads((root / "fixture/native.json").read_bytes())

    class Adapter:
        """Expose only hash-proven fixture statements through the actual selected-input path."""

        def label(self, curie):
            """Return the native label or an unchanged ancestor control."""
            return self.entity_metadata_map(curie).get("rdfs:label", [curie])[0]

        def entity_aliases(self, curie):
            """Return the fixture's native aliases unchanged."""
            return evidence["aliases"].get(curie, [])

        def entity_metadata_map(self, curie, include_all_triples=False):
            """Expose direct native triples rather than deriving a category from a label."""
            result = {}
            for subject, predicate, obj, value in evidence["statements"]:
                if subject == curie:
                    result.setdefault(predicate, []).append(obj or value)
            return result

        def outgoing_relationships(self, curie, predicates=None):
            """Mirror named asserted parents from SemSQL's Edge view."""
            return [
                ("rdfs:subClassOf", value)
                for value in self.entity_metadata_map(curie).get("rdfs:subClassOf", [])
                if not value.startswith("_:")
            ]

    oaklib.get_adapter = lambda locator: Adapter()
    module.collect_stub_curies = lambda prefixes: {"NCIT": {"NCIT:C71939", "NCIT:C16883"}}
    raw = root / "data/raw"
    db = raw / "ncit.db"
    real = raw / "native-original.db"
    real.write_bytes((root / "fixture/native.json").read_bytes())
    db.symlink_to(real)
    transform = module.OntologiesStubsTransform(input_dir=raw, output_dir=root / "data/transformed")
    transform.run()
    transform.finalize(fresh_run=True)
    dispatcher._record_fingerprint(transform, "ontologies_stubs")
    paths = [transform.output_dir / "ncit_nodes.tsv", transform.output_dir / "ncit_edges.tsv"]
    record_path = transform.output_dir / finalization.FINALIZATION_FILE
    original_record = record_path.read_bytes()
    report = json.loads(original_record)

    def fresh():
        """Return a genuine registered public admission with its guards executed."""
        admission = verify_source_freshness(paths)
        admission.verify()
        return admission

    def verdict(call):
        """Capture fail-closed outcomes explicitly, also under optimized Python."""
        try:
            call()
            return "PASS"
        except finalization.SourceFinalizationRequired as error:
            return "REJECTED: " + str(error)

    result = {"initial": verdict(fresh), "contract": report["producer_native_inputs"]}
    result["tamper"] = {}
    for change in (
        "missing",
        "version",
        "bool-version",
        "extra-key",
        "authority-type",
        "sha",
        "resolved",
        "sidecars",
        "sidecar-type",
        "null",
    ):
        changed = copy.deepcopy(report)
        contract = changed["producer_native_inputs"]
        if change == "missing":
            changed.pop("producer_native_inputs")
        elif change == "version":
            contract["version"] = 2
        elif change == "bool-version":
            contract["version"] = True
        elif change == "extra-key":
            contract["waiver"] = True
        elif change == "authority-type":
            contract["authority"] = []
        elif change == "sha":
            contract["authority"]["sha256"] = "0" * 64
        elif change == "resolved":
            contract["authority"]["resolved_path"] = str(raw / "other.db")
        elif change == "sidecars":
            contract["authority"]["absent_sqlite_sidecars"].pop()
        elif change == "sidecar-type":
            contract["authority"]["absent_sqlite_sidecars"] = "omitted"
        else:
            contract["authority"] = None
        record_path.write_text(json.dumps(changed))
        result["tamper"][change] = {
            "public": verdict(fresh),
            "finalization": verdict(lambda: finalization.verify_finalized_source_files(paths)),
        }
        record_path.write_bytes(original_record)

    result["retarget"] = {}
    replacement = raw / "replacement.db"
    for changed_bytes in (False, True):
        admission = fresh()
        replacement.write_bytes(real.read_bytes() + (b"\n" if changed_bytes else b""))
        db.unlink()
        db.symlink_to(replacement)
        result["retarget"][str(changed_bytes)] = {
            "public": verdict(fresh),
            "late": verdict(lambda admission=admission: admission.verify(metadata_only=True)),
            "finalization": verdict(lambda: finalization.verify_finalized_source_files(paths)),
        }
        db.unlink()
        db.symlink_to(real)

    result["sidecars"] = {}
    for name in report["producer_native_inputs"]["authority"]["absent_sqlite_sidecars"]:
        admission = fresh()
        sidecar = Path(name)
        sidecar.write_bytes(b"previously absent state")
        result["sidecars"][sidecar.name] = {
            "public": verdict(fresh),
            "late": verdict(lambda admission=admission: admission.verify(metadata_only=True)),
            "finalization": verdict(lambda: finalization.verify_finalized_source_files(paths)),
        }
        sidecar.unlink()

    # Complete-source inputs are also checked by standalone finalization, not
    # merely an overridable transform method or later marker callback.
    sidecar = real.with_name(real.name + "-wal")
    before = {path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()}
    sidecar.write_bytes(b"late state")
    result["direct_finalizer"] = verdict(lambda: transform.finalize(fresh_run=True))
    result["direct_finalizer_preserved"] = before == {
        path.name: path.read_bytes() for path in transform.output_dir.iterdir() if path.is_file()
    }
    sidecar.unlink()

    # A newly constructed instance can reuse the original verified contract;
    # it must not replace it with currently observed bytes or lose its guards.
    repeated = module.OntologiesStubsTransform(input_dir=raw, output_dir=root / "data/transformed")
    result["repeat"] = verdict(repeated.finalize)
    result["repeat_contract_equal"] = repeated.producer_native_inputs == report["producer_native_inputs"]
    result["repeat_record_equal"] = record_path.read_bytes() == original_record
    sidecar.write_bytes(b"late state")
    dispatcher._record_fingerprint(repeated, "ontologies_stubs")
    result["late_marker_absent"] = not (transform.output_dir / "source_fingerprint.json").exists()
    sidecar.unlink()

    publication = module.OntologiesStubsTransform(input_dir=raw, output_dir=root / "data/transformed")
    publication.finalize()
    original_publish = finalization._publish_finalization

    def introduce_before_publish(*args, **kwargs):
        """Make the native state stale after staging, before the real publication checkpoint."""
        sidecar.write_bytes(b"changed after staging")
        return original_publish(*args, **kwargs)

    with patch.object(finalization, "_publish_finalization", introduce_before_publish):
        result["late_finalizer_publication"] = verdict(lambda: publication.finalize(fresh_run=True))
    sidecar.unlink()

    publication = module.OntologiesStubsTransform(input_dir=raw, output_dir=root / "data/transformed")
    publication.finalize()
    from kg_microbe.utils import transform_fingerprint as fingerprint

    original_atomic = fingerprint.atomic_write

    @contextmanager
    def introduce_inside_marker(*args, **kwargs):
        """Insert drift after marker serialization, leaving the real atomic writer/check active."""
        with original_atomic(*args, **kwargs) as stream:

            class Writer:
                """Delegate bytes unchanged, then introduce the previously absent native state."""

                def write(self, value):
                    """Make the final marker callback, not its initial callback, reject the input."""
                    count = stream.write(value)
                    sidecar.write_bytes(b"changed inside atomic marker")
                    return count

            yield Writer()

    with patch.object(fingerprint, "atomic_write", introduce_inside_marker):
        dispatcher._record_fingerprint(publication, "ontologies_stubs")
    result["atomic_late_marker_absent"] = not (transform.output_dir / fingerprint.FINGERPRINT_FILE).exists()
    sidecar.unlink()

    byte_control = module.OntologiesStubsTransform(input_dir=raw, output_dir=root / "data/transformed")
    byte_control.finalize()
    original_bytes, stamp = real.read_bytes(), real.stat()
    real.write_bytes(original_bytes.replace(b'"Sugar"', b'"SUGAR"'))
    os.utime(real, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    result["restored_mtime"] = {
        "same_size_mtime": real.stat().st_size == stamp.st_size and real.stat().st_mtime_ns == stamp.st_mtime_ns,
        "direct": verdict(byte_control.verify_consumed_inputs),
        "finalization": verdict(lambda: finalization.verify_finalized_source_files(paths)),
        "public": verdict(fresh),
    }
    real.write_bytes(original_bytes)

    # A null contract is a separately verified, retained proof over the
    # canonical NCIT output; missing or malformed output never establishes it.
    module.collect_stub_curies = lambda prefixes: {"NCIT": set()}
    empty = module.OntologiesStubsTransform(input_dir=raw, output_dir=root / "empty")
    empty.run()
    empty.finalize(fresh_run=True)
    dispatcher._record_fingerprint(empty, "ontologies_stubs")
    empty_paths = [empty.output_dir / "ncit_nodes.tsv", empty.output_dir / "ncit_edges.tsv"]
    empty_nodes = empty_paths[0]
    original_empty = empty_nodes.read_bytes()
    empty_record = empty.output_dir / finalization.FINALIZATION_FILE
    empty_report_bytes = empty_record.read_bytes()

    def empty_fresh():
        """Use normal public source admission for the no-projection control too."""
        admission = verify_source_freshness(empty_paths)
        admission.verify()
        return admission

    result["null_initial"] = verdict(empty_fresh)
    # Null eligibility must describe the canonical staged bytes, not merely
    # the producer's original CSV spelling. The late case also checks the
    # last publication checkpoint independently of post-staging validation.
    result["null_staging"] = {}
    for curie in ("NCIT:C71939", "NCIT:C16883"):
        for mode in ("quoted-producer", "late-staged"):
            control = module.OntologiesStubsTransform(
                input_dir=raw, output_dir=root / f"staging-{curie.split(':')[1]}-{mode}"
            )
            control.run()
            control.finalize(fresh_run=True)
            control_nodes = control.output_dir / "ncit_nodes.tsv"

            def add_reviewed_node(path, *, quoted=False, curie=curie):
                """Inject a reviewed ID without inventing authority for this null source."""
                header = path.read_text().splitlines()[0].split("\t")
                values = {
                    "id": f'"{curie}"' if quoted else curie,
                    "category": "biolink:OntologyClass",
                    "name": "Sugar" if curie.endswith("71939") else "Mucin",
                }
                with path.open("a") as stream:
                    stream.write("\t".join(values.get(key, "") for key in header) + "\n")

            if mode == "quoted-producer":
                add_reviewed_node(control_nodes, quoted=True)
            before_control = {path.name: path.read_bytes() for path in control.output_dir.iterdir() if path.is_file()}

            def introduce_staged_node(transform, prepared):
                """Alter only staged output after the first canonical native eligibility check."""
                add_reviewed_node(prepared[0] / "ncit_nodes.tsv")
                return original_publish(transform, prepared)

            if mode == "late-staged":
                with patch.object(finalization, "_publish_finalization", introduce_staged_node):
                    outcome = verdict(lambda control=control: control.finalize(fresh_run=True))
            else:
                outcome = verdict(lambda control=control: control.finalize(fresh_run=True))
            result["null_staging"][f"{curie}/{mode}"] = {
                "outcome": outcome,
                "preserved": before_control
                == {path.name: path.read_bytes() for path in control.output_dir.iterdir() if path.is_file()},
            }
    result["null_output"] = {}
    for change in ("missing", "header", "reviewed-curie", "other-bytes"):
        admission = empty_fresh()
        if change == "missing":
            empty_nodes.unlink()
        elif change == "header":
            empty_nodes.write_text("wrong\theader\n")
        elif change == "reviewed-curie":
            empty_nodes.write_bytes(paths[0].read_bytes())
        else:
            empty_nodes.write_bytes(original_empty + b"\n")
        result["null_output"][change] = {
            "public": verdict(empty_fresh),
            "late": verdict(lambda admission=admission: admission.verify(metadata_only=True)),
            "direct": verdict(lambda empty=empty: empty.finalize(fresh_run=True)),
        }
        empty_nodes.write_bytes(original_empty)
        empty_record.write_bytes(empty_report_bytes)
        empty = module.OntologiesStubsTransform(input_dir=raw, output_dir=root / "empty")
        empty.finalize()

    # No native-specific obligation is imposed on unrelated registered sources.
    from kg_microbe.transform_utils.transform import Transform

    cls = dispatcher.DATA_SOURCES["cog"].transform_class
    unrelated = cls.__new__(cls)
    Transform.__init__(unrelated, "cog", raw, root / "control")
    for kind in ("nodes", "edges"):
        shutil.copyfile(root / "fixture" / f"{kind}.tsv", unrelated.output_dir / f"{kind}.tsv")
    unrelated.finalize(fresh_run=True)
    dispatcher._record_fingerprint(unrelated, "cog")
    result["unrelated"] = verdict(
        lambda: verify_source_freshness([unrelated.output_node_file, unrelated.output_edge_file]).verify()
    )
    print("NCIT_LIFETIME_RESULT=" + json.dumps(result, sort_keys=True))


@pytest.fixture(scope="module")
def lifetime_probe(tmp_path_factory):
    """Isolate code, declared curation and tiny schemas before exercising real registered gates."""
    root = tmp_path_factory.mktemp("ncit-lifetime-copy")
    shutil.copytree(ROOT / "kg_microbe", root / "kg_microbe", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "mappings", root / "mappings", ignore=shutil.ignore_patterns("__pycache__"))
    with gzip.open(root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz", "wb") as stream:
        stream.write((ROOT / "tests/resources/metatraits_manual_identity.sssom.tsv").read_bytes())
    raw = root / "data/raw"
    raw.mkdir(parents=True)
    for fixture, name in (
        ("biolink-model-minimal.yaml", "biolink-model.yaml"),
        ("predicate_mapping_minimal.yaml", "predicate_mapping.yaml"),
    ):
        shutil.copyfile(ROOT / "tests/resources" / fixture, raw / name)
    shutil.copytree(ROOT / "tests/resources/merge_source_freshness", root / "fixture")
    shutil.copyfile(ROOT / "tests/resources/ncit_category_projection/native.json", root / "fixture/native.json")
    environment = dict(
        os.environ,
        PYTHONPATH=str(root),
        PYTHONDONTWRITEBYTECODE="1",
        KG_MICROBE_BIOLINK_MODEL=str(raw / "biolink-model.yaml"),
        KG_MICROBE_BIOLINK_PREDICATE_MAP=str(raw / "predicate_mapping.yaml"),
    )
    command = [
        sys.executable,
        *(["-O"] if sys.flags.optimize else []),
        str(Path(__file__).resolve()),
        "--child",
        str(root),
    ]
    result = subprocess.run(command, cwd=root, env=environment, text=True, capture_output=True)  # noqa: S603 - exact local fixture only
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(
        next(
            line.removeprefix("NCIT_LIFETIME_RESULT=")
            for line in result.stdout.splitlines()
            if line.startswith("NCIT_LIFETIME_RESULT=")
        )
    )


def test_real_source_completion_and_unrelated_control(lifetime_probe):
    """Actual finalization and markers establish positive controls, including explicit null authority."""
    assert lifetime_probe["initial"] == lifetime_probe["null_initial"] == lifetime_probe["unrelated"] == "PASS"
    assert lifetime_probe["repeat"] == "PASS"
    assert lifetime_probe["repeat_contract_equal"] and lifetime_probe["repeat_record_equal"]
    assert len(lifetime_probe["contract"]["authority"]["absent_sqlite_sidecars"]) == 6


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "version",
        "bool-version",
        "extra-key",
        "authority-type",
        "sha",
        "resolved",
        "sidecars",
        "sidecar-type",
        "null",
    ],
)
def test_recorded_contract_cannot_drop_or_weaken_evidence(lifetime_probe, change):
    """Both completion-record and public gates require exact typed native evidence."""
    assert all(value.startswith("REJECTED:") for value in lifetime_probe["tamper"][change].values())


@pytest.mark.parametrize("changed_bytes", ["False", "True"])
def test_selected_locator_survives_receipts_and_admission(lifetime_probe, changed_bytes):
    """Retargeting to identical bytes is still a locator change, not a permitted replacement."""
    assert all(value.startswith("REJECTED:") for value in lifetime_probe["retarget"][changed_bytes].values())


def test_complete_sidecar_absence_set_survives_completion(lifetime_probe):
    """All selected and resolved -wal/-shm/-journal siblings remain checked after admission."""
    assert len(lifetime_probe["sidecars"]) == 6
    assert all(
        value.startswith("REJECTED:") for checks in lifetime_probe["sidecars"].values() for value in checks.values()
    )


def test_direct_finalizer_and_marker_keep_prepublication_guards(lifetime_probe):
    """A direct finalizer cannot bypass the producer hook or replace prior valid artifacts."""
    assert lifetime_probe["direct_finalizer"].startswith("REJECTED:")
    assert lifetime_probe["direct_finalizer_preserved"]
    assert lifetime_probe["late_marker_absent"]
    assert lifetime_probe["late_finalizer_publication"].startswith("REJECTED:")
    assert lifetime_probe["atomic_late_marker_absent"]


def test_restored_mtime_does_not_substitute_for_byte_verification(lifetime_probe):
    """Equal size and restored mtime cannot make changed authority bytes current."""
    result = lifetime_probe["restored_mtime"]
    assert result["same_size_mtime"]
    assert all(result[key].startswith("REJECTED:") for key in ("direct", "finalization", "public"))


@pytest.mark.parametrize("change", ["missing", "header", "reviewed-curie", "other-bytes"])
def test_null_contract_requires_unchanged_canonical_output(lifetime_probe, change):
    """A null proof is retained input evidence, not a caller-controlled permission to skip NCIT."""
    checks = lifetime_probe["null_output"][change]
    assert checks["public"].startswith("REJECTED:")
    assert checks["late"].startswith("REJECTED:")
    # A fresh finalization may normalize a harmless extra empty line, but may
    # never bless missing IDs/headers or a reviewed concept without authority.
    if change != "other-bytes":
        assert checks["direct"].startswith("REJECTED:")


@pytest.mark.parametrize("curie", ["NCIT:C71939", "NCIT:C16883"])
@pytest.mark.parametrize("mode", ["quoted-producer", "late-staged"])
def test_null_proof_checks_canonical_staging_before_publication(lifetime_probe, curie, mode):
    """CSV canonicalization or late staging cannot introduce a reviewed ID under null authority."""
    check = lifetime_probe["null_staging"][f"{curie}/{mode}"]
    assert check["outcome"].startswith("REJECTED:")
    assert "reviewed NCIT concept lacks native evidence" in check["outcome"]
    assert check["preserved"]


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--child":
        raise SystemExit("Expected --child <isolated-root>")
    _child(Path(sys.argv[2]))
