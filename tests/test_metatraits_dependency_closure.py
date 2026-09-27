"""Registered producer freshness must bind dynamic curation and inherited code (#1188)."""

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
FIXTURE = ROOT / "tests/resources/metatraits_dependency_inputs"


def _child(root):
    """Run real registered finalization/gates in the disposable checkout, never producers."""
    sys.path.insert(0, str(root))

    def no_network(*args, **kwargs):
        """Keep the subprocess as strictly offline as normal pytest fixtures."""
        raise RuntimeError("network forbidden in dependency regression")

    socket.socket.connect = no_network
    from click.testing import CliRunner

    import kg_microbe.transform as dispatcher
    from kg_microbe.merge_utils import merge_kg
    from kg_microbe.merge_utils.source_freshness import verify_source_freshness
    from kg_microbe.run import main
    from kg_microbe.transform_utils.transform import Transform
    from kg_microbe.utils import source_finalization as finalization
    from kg_microbe.utils import transform_fingerprint as fingerprint
    from kg_microbe.utils.microbial_trait_mappings import canonical_mapping_paths, load_microbial_trait_mappings

    assert Path(fingerprint.__file__).resolve().is_relative_to(root)
    script = root / ".claude/skills/kgm-freshness-check/kgm_freshness_check.py"
    spec = importlib.util.spec_from_file_location("dependency_diagnostic", script)
    checker = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = checker
    spec.loader.exec_module(checker)

    def prepare(name):
        """Publish tiny graphs using actual classes without constructing adapters."""
        cls = dispatcher.DATA_SOURCES[name].transform_class
        transform = cls.__new__(cls)
        Transform.__init__(transform, name, root / "data/raw", root / "data/transformed")
        for kind in ("nodes", "edges"):
            shutil.copyfile(root / "fixture" / f"{kind}.tsv", transform.output_dir / f"{kind}.tsv")
        transform.finalize(fresh_run=True)
        dispatcher._record_fingerprint(transform, name)
        assert (transform.output_dir / fingerprint.FINGERPRINT_FILE).is_file()
        return transform

    prepared = {name: prepare(name) for name in ("ontologies", "gtdb", "cog", "metatraits", "metatraits_gtdb")}

    def fresh(name):
        """Use the unchanged registered public gate plus its final admitted-input guard."""
        transform = prepared[name]
        admission = verify_source_freshness([transform.output_node_file, transform.output_edge_file])
        admission.verify()
        return admission

    def verdict(name):
        """Record failures for parent assertions without replacing any gate implementation."""
        try:
            fresh(name)
            return "FRESH"
        except finalization.SourceFinalizationRequired as error:
            return str(error)

    def diagnostic(name):
        """Invoke content-fingerprint diagnostic logic without Git or network timestamp fallback."""
        return checker._fingerprint_verdict(name, root / "kg_microbe/transform_utils" / name)[0]

    result = {"initial": {name: verdict(name) for name in prepared}, "canonical": {}, "inventory": {}, "parent": {}}
    original_outputs = {
        str(path): path.read_bytes()
        for name in ("metatraits", "metatraits_gtdb")
        for path in prepared[name].output_dir.iterdir()
        if path.is_file()
    }
    canonical = root / "mappings/canonical"
    for filename in ("special_chemical_mappings.tsv", "chemical_mappings.tsv", "enzyme_name_to_go.tsv"):
        path = canonical / filename
        previous = path.read_bytes()
        initial = load_microbial_trait_mappings(canonical)
        reader = {
            "special_chemical_mappings.tsv": prepared["metatraits"]._load_special_chemical_mappings,
            "enzyme_name_to_go.tsv": prepared["metatraits"]._load_enzyme_name_to_go,
        }.get(filename)
        explicit_before = reader() if reader is not None else None
        admission = fresh("metatraits_gtdb")
        path.write_bytes(
            previous.replace(b"CHEBI:26833", b"CHEBI:999999")
            .replace(b"CHEBI:16236", b"CHEBI:999999")
            .replace(b"GO:0003824", b"GO:9999999")
        )
        assert load_microbial_trait_mappings(canonical) != initial
        if reader is not None:
            assert reader() != explicit_before
        with pytest.raises(finalization.SourceFinalizationRequired):
            admission.verify()
        with pytest.raises(finalization.SourceFinalizationRequired):
            finalization.verify_finalized_source_files([prepared["metatraits_gtdb"].output_node_file])
        result["canonical"][filename] = {name: verdict(name) for name in ("metatraits", "metatraits_gtdb")}
        result["canonical"][filename]["diagnostic"] = diagnostic("metatraits_gtdb")
        path.write_bytes(previous)
    for action in ("add", "remove", "rename", "negative"):
        source = canonical / "chemical_mappings.tsv"
        destination = canonical / "nested" / ("ignored_negative.tsv" if action == "negative" else "added.tsv")
        destination.parent.mkdir(exist_ok=True)
        admission = fresh("metatraits_gtdb")
        if action in ("add", "negative"):
            shutil.copyfile(source, destination)
        else:
            previous = source.read_bytes()
            if action == "remove":
                source.unlink()
            else:
                source.rename(destination)
        current = {name: verdict(name) for name in ("metatraits", "metatraits_gtdb")}
        if action != "negative":
            with pytest.raises(finalization.SourceFinalizationRequired):
                finalization.verify_finalized_source_files([prepared["metatraits_gtdb"].output_node_file])
        try:
            admission.verify()
            current["late_guard"] = "FRESH"
        except finalization.SourceFinalizationRequired as error:
            current["late_guard"] = str(error)
        current["loader_selection"] = [p.relative_to(canonical).as_posix() for p in canonical_mapping_paths(canonical)]
        result["inventory"][action] = current
        if action in ("add", "negative"):
            destination.unlink()
        elif action == "remove":
            source.write_bytes(previous)
        else:
            destination.rename(source)
    for filename in ("metatraits.py", "io.py"):
        path = root / "kg_microbe/transform_utils/metatraits" / filename
        previous = path.read_bytes()
        admission = fresh("metatraits_gtdb")
        path.write_bytes(previous + b"\nDEPENDENCY_REGRESSION = True\n")
        result["parent"][filename] = {name: verdict(name) for name in ("metatraits", "metatraits_gtdb", "cog")}
        result["parent"][filename]["diagnostic"] = diagnostic("metatraits_gtdb")
        with pytest.raises(finalization.SourceFinalizationRequired):
            admission.verify()
        with pytest.raises(finalization.SourceFinalizationRequired):
            finalization.verify_finalized_source_files([prepared["metatraits_gtdb"].output_node_file])
        path.write_bytes(previous)
        path.write_bytes(previous + b"\n# Formatting/comment-only control.\n")
        result["parent"][filename]["formatting"] = {name: verdict(name) for name in ("metatraits", "metatraits_gtdb")}
        path.write_bytes(previous)
    touched = canonical / "special_chemical_mappings.tsv"
    touched.touch()
    result["touch"] = {name: verdict(name) for name in ("metatraits", "metatraits_gtdb")}
    assert all(Path(path).read_bytes() == payload for path, payload in original_outputs.items())
    result["outputs_unchanged"] = True

    # New instance supplies a genuinely new producer-time snapshot, not a reset
    # of the original instance after unreviewed drift.
    target = prepare("metatraits_gtdb")
    path = canonical / "special_chemical_mappings.tsv"
    previous = path.read_bytes()
    path.write_bytes(previous + b"\n")
    before = {p.name: p.read_bytes() for p in target.output_dir.iterdir() if p.is_file()}
    with pytest.raises(finalization.SourceFinalizationRequired):
        target.finalize(fresh_run=True)
    assert before == {p.name: p.read_bytes() for p in target.output_dir.iterdir() if p.is_file()}
    dispatcher._record_fingerprint(target, "metatraits_gtdb")
    result["producer_drift_marker_absent"] = not (target.output_dir / fingerprint.FINGERPRINT_FILE).exists()
    path.write_bytes(previous)
    prepared["metatraits_gtdb"] = prepare("metatraits_gtdb")

    result["late_marker"] = {}
    for dependency in ("canonical", "parent"):
        target = prepare("metatraits_gtdb")
        original_atomic = fingerprint.atomic_write
        new_file = (
            canonical / "late-discovered.tsv"
            if dependency == "canonical"
            else root / "kg_microbe/transform_utils/metatraits/late_helper.py"
        )

        @contextmanager
        def late_write(*args, atomic=original_atomic, changed_file=new_file, changed_kind=dependency, **kwargs):
            """Inject new input membership after writing but before real atomic publication."""
            with atomic(*args, **kwargs) as handle:

                class MutatingStream:
                    """Keep the writer real while making the final dependency check necessary."""

                    def write(self, value):
                        """Mutate only the disposable checkout after serializing the marker."""
                        result = handle.write(value)
                        changed_file.write_text("CHANGED = True\n" if changed_kind == "parent" else "new input\n")
                        return result

                yield MutatingStream()

        with patch.object(fingerprint, "atomic_write", late_write):
            dispatcher._record_fingerprint(target, "metatraits_gtdb")
        result["late_marker"][dependency] = not (target.output_dir / fingerprint.FINGERPRINT_FILE).exists()
        new_file.unlink()
    prepared["metatraits_gtdb"] = prepare("metatraits_gtdb")

    import yaml

    published = root / "published/fixture.tar.gz"
    published.parent.mkdir()
    published.write_bytes(b"previous complete archive")
    config = root / "merge-test.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {"output_directory": str(published.parent)},
                "merged_graph": {
                    "name": "fixture",
                    "source": {
                        "arbitrary": {
                            "input": {
                                "format": "tsv",
                                "filename": [
                                    str(prepared["metatraits_gtdb"].output_node_file),
                                    str(prepared["metatraits_gtdb"].output_edge_file),
                                ],
                            }
                        }
                    },
                    "destination": {"tsv": {"format": "tsv", "filename": "fixture"}},
                },
            }
        )
    )
    path.write_bytes(previous + b"\n")
    with patch.object(merge_kg, "merge", side_effect=AssertionError("KGX must not execute")):
        with pytest.raises(finalization.SourceFinalizationRequired):
            merge_kg.load_and_merge(str(config))
        cli = CliRunner().invoke(main, ["merge", "-y", str(config)])
    result["cli_exception"] = type(cli.exception).__name__
    result["archive_unchanged"] = published.read_bytes() == b"previous complete archive"
    path.write_bytes(previous)
    print("DEPENDENCY_RESULT=" + json.dumps(result, sort_keys=True))


@pytest.fixture(scope="module")
def dependency_probe(tmp_path_factory):
    """Run a single isolated real-public-gate matrix, shared by small result assertions."""
    root = tmp_path_factory.mktemp("metatraits-dependency-copy")
    shutil.copytree(ROOT / "kg_microbe", root / "kg_microbe", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(FIXTURE / "canonical", root / "mappings/canonical")
    from kg_microbe.utils.transform_fingerprint import SHARED_DATA_INPUTS

    for relative in (
        *SHARED_DATA_INPUTS,
        "mappings/foodon_model_dispositions.tsv",
        "mappings/ontology_self_loop_exclusions.tsv",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    with gzip.open(root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz", "wb") as stream:
        stream.write((ROOT / "tests/resources/metatraits_manual_identity.sssom.tsv").read_bytes())
    raw = root / "data/raw"
    raw.mkdir(parents=True)
    for fixture, filename in (
        ("biolink-model-minimal.yaml", "biolink-model.yaml"),
        ("predicate_mapping_minimal.yaml", "predicate_mapping.yaml"),
    ):
        shutil.copyfile(ROOT / "tests/resources" / fixture, raw / filename)
    with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as archive:
        content = b"1\t|\t1\t|\tno rank\t|\n"
        member = tarfile.TarInfo("nodes.dmp")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    shutil.copytree(ROOT / "tests/resources/merge_source_freshness", root / "fixture")
    diagnostic = Path(".claude/skills/kgm-freshness-check/kgm_freshness_check.py")
    (root / diagnostic).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / diagnostic, root / diagnostic)
    environment = dict(
        os.environ,
        PYTHONPATH=str(root),
        PYTHONDONTWRITEBYTECODE="1",
        KG_MICROBE_BIOLINK_MODEL=str(raw / "biolink-model.yaml"),
        KG_MICROBE_BIOLINK_PREDICATE_MAP=str(raw / "predicate_mapping.yaml"),
    )
    child = subprocess.run(  # noqa: S603 - exact interpreter and this immutable fixture script only
        [sys.executable, str(Path(__file__).resolve()), "--child", str(root)],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    return json.loads(
        next(
            line.removeprefix("DEPENDENCY_RESULT=")
            for line in child.stdout.splitlines()
            if line.startswith("DEPENDENCY_RESULT=")
        )
    )


def test_registered_sources_initially_pass_and_preserve_outputs(dependency_probe):
    """Initial green evidence is produced by real finalization and success-marker publication."""
    assert set(dependency_probe["initial"].values()) == {"FRESH"}
    assert dependency_probe["outputs_unchanged"]


@pytest.mark.parametrize(
    "filename", ["special_chemical_mappings.tsv", "chemical_mappings.tsv", "enzyme_name_to_go.tsv"]
)
def test_actual_canonical_changes_reject_both_sources(dependency_probe, filename):
    """All three reader routes must invalidate actual public and diagnostic freshness."""
    result = dependency_probe["canonical"][filename]
    assert all(result[name] != "FRESH" for name in ("metatraits", "metatraits_gtdb"))
    assert result["diagnostic"].startswith("STALE")


@pytest.mark.parametrize("action", ["add", "remove", "rename"])
def test_dynamic_inventory_changes_and_late_guards(dependency_probe, action):
    """Discovery after import and after admission must see membership changes, not old globs."""
    result = dependency_probe["inventory"][action]
    assert all(result[key] != "FRESH" for key in ("metatraits", "metatraits_gtdb", "late_guard"))


def test_negative_file_exclusion_and_unchanged_bytes(dependency_probe):
    """The declaration shares the reader's exclusion; touches do not change content freshness."""
    result = dependency_probe["inventory"]["negative"]
    assert all(result[key] == "FRESH" for key in ("metatraits", "metatraits_gtdb", "late_guard"))
    assert not any("negative" in name for name in result["loader_selection"])
    assert set(dependency_probe["touch"].values()) == {"FRESH"}


@pytest.mark.parametrize("filename", ["metatraits.py", "io.py"])
def test_inherited_behavior_targets_only_relevant_producers(dependency_probe, filename):
    """Parent behavior changes invalidate GTDB, while comments and unrelated producers stay fresh."""
    result = dependency_probe["parent"][filename]
    assert result["metatraits"] != "FRESH" and result["metatraits_gtdb"] != "FRESH"
    assert result["cog"] == "FRESH"
    assert result["diagnostic"] == "STALE_VS_CODE"
    assert set(result["formatting"].values()) == {"FRESH"}


def test_producer_drift_cannot_be_restamped_or_reach_kgx(dependency_probe):
    """A current hash must never certify an earlier producer snapshot after input drift."""
    assert dependency_probe["producer_drift_marker_absent"]
    assert dependency_probe["cli_exception"] == "SourceFinalizationRequired"
    assert dependency_probe["archive_unchanged"]
    assert all(dependency_probe["late_marker"].values())


def test_inherited_code_inventory_and_checkout_prefix(tmp_path):
    """Code keys stay checkout-independent and additions/removals change inherited identity."""
    from kg_microbe.utils.transform_fingerprint import code_fingerprint

    dependencies = ("kg_microbe/transform_utils/metatraits",)
    own = "kg_microbe/transform_utils/metatraits_gtdb"
    digests = []
    for name in ("first", "second"):
        root = tmp_path / name
        for package in (*dependencies, own):
            directory = root / package
            directory.mkdir(parents=True)
            (directory / "__init__.py").write_text("VALUE = 1\n")
        digests.append(code_fingerprint(root / own, root, dependencies))
    assert digests[0] == digests[1]
    root = tmp_path / "second"
    extra = root / dependencies[0] / "extra.py"
    extra.write_text("EXTRA = True\n")
    assert code_fingerprint(root / own, root, dependencies) != digests[1]
    extra.unlink()
    assert code_fingerprint(root / own, root, dependencies) == digests[1]


def test_legacy_migration_cannot_bless_unbound_dependencies(tmp_path):
    """Even matching v2 evidence cannot certify newly discovered or inherited dependencies."""
    from kg_microbe.utils import transform_fingerprint as fingerprint

    package = tmp_path / "producer"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 1\n")
    output = tmp_path / "transformed/source"
    output.mkdir(parents=True)
    marker = output / fingerprint.FINGERPRINT_FILE
    marker.write_text(
        json.dumps(
            {
                "version": 2,
                "code": fingerprint._v2_code_fingerprint(package),
                "data": fingerprint._v2_hash_files(()),
                "upstream": fingerprint._v2_upstream_fingerprint(output.parent, ()),
            }
        )
    )
    before = marker.read_bytes()
    outcome = fingerprint.migrate_markers(
        output.parent,
        tmp_path,
        [
            {
                "name": "source",
                "output_dir": "source",
                "code_dir": package,
                "data_inputs": (),
                "transform_inputs": (),
                "requires_dependency_rebuild": True,
            }
        ],
    )
    assert outcome == {"source": "left: discovered/inherited dependencies require a producer rerun"}
    assert marker.read_bytes() == before


if __name__ == "__main__":
    assert sys.argv[1] == "--child"
    _child(Path(sys.argv[2]))
