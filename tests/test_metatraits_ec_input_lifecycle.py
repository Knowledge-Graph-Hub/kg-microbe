"""Actual registered optional EC reads survive every finalization and admission checkpoint (#1193)."""

import copy
import gzip
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/resources/metatraits_ec_inputs"
NAMES = ("metatraits", "metatraits_gtdb")


def require(condition, message):
    """Keep child verification active even when Python optimization removes ordinary assertions."""
    if not condition:
        raise RuntimeError(message)


def _child(root):
    """Run unchanged registered finalization/gates on tiny outputs, never full producers or adapters."""
    root = root.resolve()
    sys.path.insert(0, str(root))

    def offline(*args, **kwargs):
        """Reject accidental network in the isolated child as well as parent pytest."""
        raise RuntimeError("network forbidden in optional EC regression")

    socket.socket.connect = offline
    import kg_microbe.transform as dispatcher
    from kg_microbe.merge_utils import merge_kg
    from kg_microbe.merge_utils.source_freshness import verify_source_freshness
    from kg_microbe.transform_utils.transform import Transform
    from kg_microbe.utils import source_finalization as finalizer
    from kg_microbe.utils import transform_fingerprint as fingerprint

    require(Path(dispatcher.__file__).resolve().is_relative_to(root), "wrong package origin")
    script = root / ".claude/skills/kgm-freshness-check/kgm_freshness_check.py"
    spec = importlib.util.spec_from_file_location("ec_diagnostic", script)
    diagnostic = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = diagnostic
    spec.loader.exec_module(diagnostic)
    raw = root / "data/raw"
    ec = raw / "ec2go.txt"
    first, second = [(root / "ec-fixture" / name).read_bytes() for name in ("first.txt", "second.txt")]
    ec.write_bytes(first)
    prepared = {}

    def prepare(name, *, read=True):
        """Use real registered classes and actual optional reader without expensive constructors."""
        cls = dispatcher.DATA_SOURCES[name].transform_class
        value = cls.__new__(cls)
        Transform.__init__(value, name, raw, root / "data/transformed")
        for kind in ("nodes", "edges"):
            shutil.copyfile(root / "fixture" / (kind + ".tsv"), value.output_dir / (kind + ".tsv"))
        if name in NAMES and read:
            value.ec_to_go = value._load_ec_to_go()
            value.enzyme_name_to_go = {}
            value.metpo_pattern_to_predicate = {}
        value.finalize(fresh_run=True)
        dispatcher._record_fingerprint(value, name)
        require((value.output_dir / fingerprint.FINGERPRINT_FILE).is_file(), "completion marker absent")
        return value

    for name in ("ontologies", "gtdb", "cog", *NAMES):
        prepared[name] = prepare(name)

    def fresh(name):
        """Run public recursive freshness and verify the returned retained input set."""
        value = prepared[name]
        admission = verify_source_freshness([value.output_node_file, value.output_edge_file])
        admission.verify()
        return admission

    def verdict(call):
        """Expose actual gate rejection without monkeypatching validators or checking removable asserts."""
        try:
            call()
            return "ACCEPTED"
        except finalizer.SourceFinalizationRequired as error:
            return "REJECTED: " + str(error)

    def diag(name):
        """Check the actual diagnostic's requested registered source identity."""
        return diagnostic._fingerprint_verdict(name, root / "kg_microbe/transform_utils" / name)[0]

    import yaml

    config = root / "merge-fixture.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(root / "published")},
                "merged_graph": {
                    "name": "fixture",
                    "source": {
                        name: {
                            "input": {
                                "format": "tsv",
                                "filename": [
                                    str(prepared[name].output_node_file),
                                    str(prepared[name].output_edge_file),
                                ],
                            }
                        }
                        for name in NAMES
                    },
                    "destination": {"tsv": {"format": "tsv", "filename": "fixture"}},
                },
            }
        )
    )
    result = {"initial": {name: verdict(lambda name=name: fresh(name)) for name in (*NAMES, "cog")}}
    result["targets"] = {
        name: prepared[name]._resolve_enzyme_activity("enzyme activity: fixture (EC1.1.1.1)")["curie"] for name in NAMES
    }
    files = [p for value in prepared.values() for p in value.output_dir.iterdir() if p.is_file()]
    original = {str(p): p.read_bytes() for p in files}
    result["drift"] = {}
    for kind in ("change", "same-size-restored-mtime", "delete", "same-byte-link", "parent-link"):
        ec.write_bytes(first)
        admissions = {name: fresh(name) for name in (*NAMES, "cog")}
        stamp = ec.stat()
        if kind in ("change", "same-size-restored-mtime"):
            require(len(first) == len(second), "fixture must have equal sizes")
            ec.write_bytes(second)
            if kind == "same-size-restored-mtime":
                os.utime(ec, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        elif kind == "delete":
            ec.unlink()
        elif kind == "same-byte-link":
            other = raw / "same-byte-other.txt"
            other.write_bytes(first)
            ec.unlink()
            ec.symlink_to(other)
        else:
            moved = raw.with_name("raw-moved")
            raw.rename(moved)
            raw.symlink_to(moved, target_is_directory=True)
        result["drift"][kind] = {}
        for name in NAMES:
            value = prepared[name]
            result["drift"][kind][name] = {
                "public": verdict(lambda name=name: fresh(name)),
                "retained": verdict(admissions[name].verify),
                "recorded": verdict(
                    lambda value=value: finalizer.verify_finalized_source_files(
                        [value.output_node_file, value.output_edge_file]
                    )
                ),
                "diagnostic": diag(name),
            }
        result["drift"][kind]["merge"] = verdict(lambda: merge_kg._assert_sources_finalized(str(config)))
        if kind != "parent-link":
            # Whole raw-directory retargeting also changes COG's schema/authority
            # locators; only EC-specific changes are an unrelated-source control.
            result["drift"][kind]["cog"] = {
                "public": verdict(lambda: fresh("cog")),
                "retained": verdict(admissions["cog"].verify),
                "diagnostic": diag("cog"),
            }
        if kind == "parent-link":
            raw.unlink()
            moved.rename(raw)
        if ec.is_symlink():
            ec.unlink()
        ec.write_bytes(first)
    result["unrelated"] = verdict(lambda: fresh("cog"))
    require(original == {str(p): p.read_bytes() for p in files}, "read-only gates changed fixture outputs")
    result["outputs_unchanged"] = True

    result["late_standalone"] = {}
    for name in NAMES:
        result["late_standalone"][name] = {}
        for absent in (False, True):
            if absent:
                ec.unlink(missing_ok=True)
            else:
                ec.write_bytes(first)
            value = prepare(name)
            for stage in ("source_canonicalization.tsv", "edges.tsv"):
                for legacy in (True, False):
                    if absent:
                        ec.unlink(missing_ok=True)
                    else:
                        ec.write_bytes(first)
                    original_sha = finalizer._sha256
                    changed = []

                    def mutate_during_later_read(path, original_sha=original_sha, changed=changed, stage=stage):
                        """Inject drift after initial optional admission during audit or the later graph member."""
                        digest = original_sha(path)
                        if Path(path).name == stage and not changed:
                            ec.write_bytes(second)
                            changed.append(True)
                        return digest

                    with patch.object(finalizer, "_sha256", mutate_during_later_read):
                        verify = finalizer.verify_finalized_source_files
                        if legacy:
                            namespace = dict(finalizer.__dict__)
                            exec(  # noqa: S102 - exact immutable prior verification function
                                compile(
                                    (root / "ec-fixture/legacy_verify_finalized.txt").read_text(),
                                    "legacy_verify_finalized.txt",
                                    "exec",
                                ),
                                namespace,
                            )
                            verify = namespace["verify_finalized_source_files"]
                        result["late_standalone"][name][f"{absent}:{stage}:{legacy}"] = verdict(
                            lambda verify=verify, value=value: verify([value.output_node_file, value.output_edge_file])
                        )
                    require(changed, "late standalone callback not reached")
        ec.write_bytes(first)
        prepared[name] = prepare(name)

    result["tamper"] = {}
    for name in NAMES:
        value = prepared[name]
        path = value.output_dir / finalizer.FINALIZATION_FILE
        original_bytes = path.read_bytes()
        report = json.loads(original_bytes)
        result["tamper"][name] = {}
        for kind in (
            "missing",
            "bool-version",
            "wrong-locator",
            "source",
            "directory",
            "both",
            "directory-missing",
            "directory-unknown",
            "directory-null",
            "directory-integer",
            "producer-missing",
        ):
            altered = copy.deepcopy(report)
            if kind == "missing":
                del altered["optional_consumed_inputs"]
            elif kind == "bool-version":
                altered["optional_consumed_inputs"]["version"] = True
            elif kind == "wrong-locator":
                other = raw / "same-byte-other.txt"
                other.write_bytes(first)
                altered["optional_consumed_inputs"]["inputs"]["ec_to_go"]["locator"] = str(other)
            elif kind == "directory-missing":
                del altered["producer_code"]["directory"]
            elif kind == "producer-missing":
                del altered["producer_code"]
            elif kind.startswith("directory-"):
                altered["producer_code"]["directory"] = {
                    "directory-unknown": str(root / "not-a-registered-producer"),
                    "directory-null": None,
                    "directory-integer": 23,
                }[kind]
            else:
                altered.pop("optional_consumed_inputs")
                if kind in ("source", "both"):
                    altered["source"] = "cog"
                if kind in ("directory", "both"):
                    altered["producer_code"]["directory"] = str(root / "kg_microbe/transform_utils/cog")
            path.write_text(json.dumps(altered))
            try:
                public = verdict(lambda name=name: fresh(name))
            except TypeError as error:
                # The existing public gate rejects non-path directory values
                # through Path's TypeError; this is not successful admission.
                public = "REJECTED: TypeError: " + str(error)
            result["tamper"][name][kind] = {"public": public, "diagnostic": diag(name)}
            path.write_bytes(original_bytes)
        altered = copy.deepcopy(report)
        altered.pop("optional_consumed_inputs")
        path.write_text(json.dumps(altered))
        result["tamper"][name]["repeat_missing"] = verdict(value.finalize)
        path.write_bytes(original_bytes)

    result["absent"] = {}
    ec.unlink()
    for name in NAMES:
        prepared[name] = prepare(name)
    prepared["cog"] = prepare("cog")
    absent_cog_admission = fresh("cog")
    absent_admissions = {name: fresh(name) for name in NAMES}
    ec.write_bytes(second)
    result["unrelated_absent"] = {
        "public": verdict(lambda: fresh("cog")),
        "retained": verdict(absent_cog_admission.verify),
        "diagnostic": diag("cog"),
    }
    for name in NAMES:
        value = prepared[name]
        result["absent"][name] = {
            "map": value.ec_to_go,
            "target": value._resolve_enzyme_activity("enzyme activity: fixture (EC1.1.1.1)")["curie"],
            "public_after_appearance": verdict(lambda name=name: fresh(name)),
            "retained_after_appearance": verdict(absent_admissions[name].verify),
            "diagnostic": diag(name),
        }

    result["lifetime"] = {}
    for name in NAMES:
        ec.write_bytes(first)
        value = prepare(name)
        ec.write_bytes(second)
        result["lifetime"][name] = {"finalize": verdict(lambda value=value: value.finalize(fresh_run=True))}
        dispatcher._record_fingerprint(value, name)
        result["lifetime"][name]["marker_absent"] = not (value.output_dir / fingerprint.FINGERPRINT_FILE).exists()

    result["late"] = {}
    for name in NAMES:
        result["late"][name] = {}
        for absent in (False, True):
            if absent:
                ec.unlink(missing_ok=True)
            else:
                ec.write_bytes(first)
            value = prepare(name)
            previous = {p.name: p.read_bytes() for p in value.output_dir.iterdir() if p.is_file()}
            publish = finalizer._publish_finalization

            def late_publish(transform, prepared_bundle, publish=publish):
                """Mutate after staging but before the actual publication guard, not instead of it."""
                ec.write_bytes(second)
                return publish(transform, prepared_bundle)

            with patch.object(finalizer, "_publish_finalization", late_publish):
                decision = verdict(lambda value=value: value.finalize(fresh_run=True))
            result["late"][name][f"finalize-{absent}"] = decision
            require(
                previous == {p.name: p.read_bytes() for p in value.output_dir.iterdir() if p.is_file()},
                "failed finalizer published partial outputs",
            )
            if absent:
                ec.unlink()
            else:
                ec.write_bytes(first)
            value = prepare(name)
            atomic = fingerprint.atomic_write

            @contextmanager
            def late_marker(*args, atomic=atomic, **kwargs):
                """Inject drift during the real atomic marker write, before its final callback."""
                with atomic(*args, **kwargs) as handle:

                    class Stream:
                        """Delegate serialization while changing only the disposable EC input."""

                        def write(self, payload):
                            """Write normally before exercising the last producer-read guard."""
                            count = handle.write(payload)
                            ec.write_bytes(second)
                            return count

                    yield Stream()

            with patch.object(fingerprint, "atomic_write", late_marker):
                dispatcher._record_fingerprint(value, name)
            result["late"][name][f"marker-{absent}"] = not (value.output_dir / fingerprint.FINGERPRINT_FILE).exists()

    result["alternate"] = {}
    ec.write_bytes(second)
    alternate = root / "alternate"
    alternate.mkdir()
    (alternate / "ec2go.txt").write_bytes(first)
    for name in NAMES:
        value = prepare(name)
        value.input_base_dir = alternate
        result["alternate"][name] = value._load_ec_to_go()["1.1.1.1"]["go_id"]
    result["never_read"] = {name: verdict(lambda name=name: prepare(name, read=False)) for name in NAMES}
    from typing import Dict

    namespace = {"RAW_DATA_DIR": raw, "Dict": Dict}
    exec(  # noqa: S102 - exact immutable extracted old method, not arbitrary user code
        compile((root / "ec-fixture/legacy_loader.txt").read_text(), "legacy_loader.txt", "exec"), namespace
    )
    parent_class = dispatcher.DATA_SOURCES["metatraits"].transform_class
    with patch.object(parent_class, "_load_ec_to_go", namespace["_load_ec_to_go"]):
        result["legacy_reader"] = {name: verdict(lambda name=name: prepare(name)) for name in NAMES}
    print("EC_LIFECYCLE_RESULT=" + json.dumps(result, sort_keys=True))


@pytest.fixture(scope="module")
def lifecycle(tmp_path_factory, record_testsuite_property):
    """Run one offline real registered-source matrix, with no production raw or graph access."""
    root = tmp_path_factory.mktemp("ec-lifecycle").resolve()
    shutil.copytree(ROOT / "kg_microbe", root / "kg_microbe", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "tests/resources/metatraits_dependency_inputs/canonical", root / "mappings/canonical")
    from kg_microbe.utils.transform_fingerprint import SHARED_DATA_INPUTS

    for relative in (*SHARED_DATA_INPUTS, "mappings/ontology_self_loop_exclusions.tsv"):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    with gzip.open(root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz", "wb") as stream:
        stream.write((ROOT / "tests/resources/metatraits_manual_identity.sssom.tsv").read_bytes())
    raw = root / "data/raw"
    raw.mkdir(parents=True)
    for source, target in (
        ("biolink-model-minimal.yaml", "biolink-model.yaml"),
        ("predicate_mapping_minimal.yaml", "predicate_mapping.yaml"),
    ):
        shutil.copyfile(ROOT / "tests/resources" / source, raw / target)
    with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as archive:
        content = b"1\t|\t1\t|\tno rank\t|\n"
        member = tarfile.TarInfo("nodes.dmp")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    shutil.copytree(ROOT / "tests/resources/merge_source_freshness", root / "fixture")
    shutil.copytree(FIXTURE, root / "ec-fixture")
    diagnostic = Path(".claude/skills/kgm-freshness-check/kgm_freshness_check.py")
    (root / diagnostic).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / diagnostic, root / diagnostic)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("KG_MICROBE_")}
    environment.update(
        PYTHONPATH=str(root),
        PYTHONDONTWRITEBYTECODE="1",
        KG_MICROBE_BIOLINK_MODEL=str(raw / "biolink-model.yaml"),
        KG_MICROBE_BIOLINK_PREDICATE_MAP=str(raw / "predicate_mapping.yaml"),
    )
    command = [
        sys.executable,
        "-B",
        *(["-O"] if sys.flags.optimize else []),
        str(Path(__file__).resolve()),
        "--child",
        str(root),
    ]
    child = subprocess.run(  # noqa: S603 - exact interpreter and this immutable test script only
        command, cwd=root, env=environment, text=True, capture_output=True
    )
    assert child.returncode == 0, child.stdout + child.stderr
    result = json.loads(
        next(line.split("=", 1)[1] for line in child.stdout.splitlines() if line.startswith("EC_LIFECYCLE_RESULT="))
    )
    record_testsuite_property("ec_lifecycle", json.dumps(result, sort_keys=True))
    return result


def test_real_initial_admission_and_nonconsumer(lifecycle):
    """The positive baseline and unrelated producer remain genuinely fresh, with unchanged outputs."""
    assert set(lifecycle["initial"].values()) == {"ACCEPTED"}
    assert set(lifecycle["targets"].values()) == {"GO:0004022"}
    assert lifecycle["unrelated"] == "ACCEPTED"
    assert lifecycle["unrelated_absent"] == {"public": "ACCEPTED", "retained": "ACCEPTED", "diagnostic": "FRESH"}
    assert lifecycle["outputs_unchanged"]
    for cases in lifecycle["late_standalone"].values():
        for key, value in cases.items():
            assert value == "ACCEPTED" if key.endswith(":True") else value.startswith("REJECTED:")


@pytest.mark.parametrize("kind", ["change", "same-size-restored-mtime", "delete", "same-byte-link", "parent-link"])
def test_real_gates_reject_ec_drift(lifecycle, kind):
    """Public, recorded, retained, diagnostic and merge-preflight gates all reject each drift class."""
    row = lifecycle["drift"][kind]
    if kind != "parent-link":
        assert row["cog"] == {"public": "ACCEPTED", "retained": "ACCEPTED", "diagnostic": "FRESH"}
    assert row["merge"].startswith("REJECTED:")
    for name in NAMES:
        assert all(row[name][key].startswith("REJECTED:") for key in ("public", "recorded", "retained"))
        assert row[name]["diagnostic"].startswith("STALE")


@pytest.mark.parametrize("name", NAMES)
def test_real_record_identity_optional_absence_and_callbacks(lifecycle, name):
    """Tampering, optional appearance and producer/finalizer/marker lifetime drift cannot certify a run."""
    for kind, row in lifecycle["tamper"][name].items():
        if kind == "repeat_missing":
            assert row.startswith("REJECTED:")
        else:
            assert row["public"].startswith("REJECTED:")
            assert row["diagnostic"].startswith("STALE")
    absent = lifecycle["absent"][name]
    assert absent["map"] == {} and absent["target"] == "EC:1.1.1.1"
    assert absent["public_after_appearance"].startswith("REJECTED:")
    assert absent["retained_after_appearance"].startswith("REJECTED:")
    assert absent["diagnostic"].startswith("STALE")
    assert lifecycle["lifetime"][name]["finalize"].startswith("REJECTED:")
    assert lifecycle["lifetime"][name]["marker_absent"]
    assert lifecycle["alternate"][name] == "GO:0003824"
    assert lifecycle["never_read"][name].startswith("REJECTED:")
    assert lifecycle["legacy_reader"][name].startswith("REJECTED:")
    for absent in (False, True):
        assert lifecycle["late"][name][f"finalize-{absent}"].startswith("REJECTED:")
        assert lifecycle["late"][name][f"marker-{absent}"]


if __name__ == "__main__":
    require(sys.argv[1] == "--child", "expected child invocation")
    _child(Path(sys.argv[2]))
