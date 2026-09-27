"""
Exercise real optional-input admission through direct export and atomic archive publication.

The disposable registered producers consume tiny immutable fixtures; this does not
run their scientific transforms. Validators, freshness gates, serializer, packaging
and retained admission remain real. No production raw data or graph is read.
"""

import ast
import gzip
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONSUMERS = ("metatraits", "metatraits_gtdb")
CASES = ("stable-present", "stable-absent", "late-present-change", "late-appearance")


def require(condition, message):
    """Keep acceptance checks active under optimized Python."""
    if not condition:
        raise RuntimeError(message)


def digest(path):
    """Hash only selected fixture/code files, never production raw or graph outputs."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _child(root):
    """Use actual registered producer finalization, public admission and KGX on tiny copied fixtures."""
    root = root.resolve()
    sys.path.insert(0, str(root))

    def offline(*args, **kwargs):
        """Reject all accidental network resolution and connections."""
        raise RuntimeError("Network forbidden in EC/export integration regression")

    socket.socket.connect = offline
    socket.getaddrinfo = offline
    from multiprocessing.pool import ThreadPool

    import yaml

    import kg_microbe.transform as dispatcher
    from kg_microbe.merge_utils import kgx_source, merge_kg
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.transform_utils.transform import Transform
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    # isort: split
    # Import KGX only after the package installs its actual local-schema defaults.
    from kgx.cli import cli_utils

    require(Path(dispatcher.__file__).resolve().is_relative_to(root), "Wrong isolated package origin")
    require(kgx_source.version("kgx") == "2.7.0", "This regression requires inspected KGX 2.7.0")
    raw = root / "data/raw"
    ec = raw / "ec2go.txt"
    first, second = [(root / "ec-fixture" / name).read_bytes() for name in ("first.txt", "second.txt")]
    require(first != second, "EC mutation fixtures must differ")

    def prepare(name):
        """Avoid adapters/run methods but retain actual registered optional-reader and completion contracts."""
        cls = dispatcher.DATA_SOURCES[name].transform_class
        value = cls.__new__(cls)
        Transform.__init__(value, name, raw, root / "data/transformed")
        for kind in ("nodes", "edges"):
            shutil.copyfile(root / "fixture" / (kind + ".tsv"), value.output_dir / (kind + ".tsv"))
        if name in CONSUMERS:
            value.ec_to_go = value._load_ec_to_go()
        value.finalize(fresh_run=True)
        dispatcher._record_fingerprint(value, name)
        require((value.output_dir / "source_fingerprint.json").is_file(), "Actual producer marker missing")
        return value

    prepare("ontologies")
    prepare("gtdb")

    def exercise(consumer, case):
        """Run one real pipeline with an optional-state observation or late mutation."""
        absent = case in {"stable-absent", "late-appearance"}
        if absent:
            ec.unlink(missing_ok=True)
        else:
            ec.write_bytes(first)
        value = prepare(consumer)
        case_dir = root / "cases" / consumer / case
        published = case_dir / "published" / "fixture.tar.gz"
        published.parent.mkdir(parents=True)
        previous = b"PREVIOUS ACCEPTED ARCHIVE SENTINEL\n"
        published.write_bytes(previous)
        config = case_dir / "merge.yaml"
        config.write_text(
            yaml.safe_dump(
                {
                    "configuration": {"output_directory": str(published.parent)},
                    "merged_graph": {
                        "name": "ec-export-fixture",
                        "source": {
                            "selected": {
                                "input": {
                                    "format": "tsv",
                                    "filename": [str(value.output_node_file), str(value.output_edge_file)],
                                }
                            }
                        },
                        "destination": {"release": {"format": "tsv", "filename": "fixture", "compression": "tar.gz"}},
                    },
                }
            )
        )
        admitted, direct, packaged = [], [], []
        original_admit = merge_kg._assert_sources_finalized
        original_direct = kgx_source.ProvenancePreservingTransformer._export_completed_graph
        original_package = merge_kg._rewrite_tarball

        def observe_admission(*args, **kwargs):
            """Inspect the real returned admission, without altering acceptance or verification."""
            guard = original_admit(*args, **kwargs)
            require(isinstance(guard, SourceAdmission), "No actual retained source admission")
            require(guard.bindings.get(ec.absolute()) == ec.resolve(), "EC locator missing from admission")
            if absent:
                require(ec.resolve() in guard.absent, "Optional absence not retained")
            else:
                require(
                    guard.identities[ec.resolve()]["sha256"] == hashlib.sha256(first).hexdigest(),
                    "Wrong producer-time EC bytes admitted",
                )
            admitted.append(guard)
            return guard

        def observe_direct(self, *args, **kwargs):
            """Count real direct serialization; never replace its reader, sink, or processor."""
            direct.append(True)
            return original_direct(self, *args, **kwargs)

        def package_then_change(*args, **kwargs):
            """Change disposable EC only after the genuine private archive has been packaged."""
            result = original_package(*args, **kwargs)
            require(Path(args[0]).is_file(), "Real private packaging did not finish")
            packaged.append(True)
            if case == "late-present-change":
                ec.write_bytes(second)
            elif case == "late-appearance":
                ec.write_bytes(first)
            return result

        error = None
        with (
            patch.object(cli_utils, "Pool", ThreadPool),
            patch.object(merge_kg, "_assert_sources_finalized", observe_admission),
            patch.object(kgx_source.ProvenancePreservingTransformer, "_export_completed_graph", observe_direct),
            patch.object(merge_kg, "_rewrite_tarball", package_then_change),
            kgx_source.local_prefix_context(),
        ):
            try:
                merge_kg.load_and_merge(str(config))
            except SourceFinalizationRequired as caught:
                error = str(caught)
        require(len(admitted) == len(direct) == len(packaged) == 1, "Expected full actual pipeline was not reached")
        require(kgx_source._DIRECT_EXPORT.get() is None, "Export scope leaked after public call")
        if case.startswith("late-"):
            require(error is not None and str(ec) in error, "Wrong/missing late EC rejection")
            require(published.read_bytes() == previous, "Failed final guard overwrote prior archive")
            require(list(published.parent.iterdir()) == [published], "Failed merge published extra artifacts")
            try:
                admitted[0].verify()
            except SourceFinalizationRequired:
                pass
            else:
                raise RuntimeError("The genuine retained admission did not detect injected EC drift")
        else:
            require(error is None, "Stable admitted optional state failed: " + str(error))
            require(published.read_bytes() != previous, "Stable pipeline did not publish its archive")
            with tarfile.open(published, "r:gz") as archive:
                payload = {member.name: archive.extractfile(member).read() for member in archive.getmembers()}
            manifest = json.loads(payload.pop("manifest.json"))
            for name, entry in manifest["members"].items():
                require(hashlib.sha256(payload[name]).hexdigest() == entry["sha256"], "Archive byte hash mismatch")
            require(len(payload["fixture_nodes.tsv"].splitlines()) == 3, "Unexpected fixture node count")
            require(len(payload["fixture_edges.tsv"].splitlines()) == 2, "Unexpected fixture assertion count")
            admitted[0].verify()
        require(not list(case_dir.glob(".published.merge-*")), "Private staging was not cleaned")
        return {
            "direct_calls": len(direct),
            "real_admissions": len(admitted),
            "packaging_calls": len(packaged),
            "rejected": error is not None,
            "error": error,
            "prior_archive_preserved": published.read_bytes() == previous,
        }

    outcomes = {consumer + ":" + case: exercise(consumer, case) for consumer in CONSUMERS for case in CASES}
    print("EC_EXPORT_INTEGRATION_RESULT=" + json.dumps(outcomes, sort_keys=True))


@pytest.fixture(scope="module")
def integration_results(tmp_path_factory, record_testsuite_property):
    """Copy bounded code/resources and exercise all eight public pipelines once."""
    code = ROOT
    root = tmp_path_factory.mktemp("ec-direct-export").resolve()
    tree = ast.parse((code / "kg_microbe/utils/transform_fingerprint.py").read_text())
    declaration = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SHARED_DATA_INPUTS" for target in node.targets)
    )
    shared = ast.literal_eval(declaration)
    require(
        isinstance(shared, tuple) and all(isinstance(name, str) for name in shared),
        "Unsupported fixture input declaration",
    )
    package_files = [
        path for path in (code / "kg_microbe").rglob("*.py") if path.is_file() and "__pycache__" not in path.parts
    ]
    resources = (
        *shared,
        "mappings/ontology_self_loop_exclusions.tsv",
        "kg_microbe/transform_utils/custom_curies.yaml",
        "kg_microbe/utils/category_consolidation_rules.yaml",
    )
    fixture_dirs = (
        ("metatraits_dependency_inputs/canonical", "mappings/canonical"),
        ("merge_source_freshness", "fixture"),
        ("metatraits_ec_inputs", "ec-fixture"),
    )
    fixture_files = (
        "biolink-model-minimal.yaml",
        "predicate_mapping_minimal.yaml",
        "metatraits_manual_identity.sssom.tsv",
    )
    copied = [*package_files, *(code / name for name in resources), Path(__file__).resolve()]
    copied.extend(
        path
        for relative, _ in fixture_dirs
        for path in (code / "tests/resources" / relative).rglob("*")
        if path.is_file()
    )
    copied.extend(code / "tests/resources" / name for name in fixture_files)
    before = {str(path): digest(path) for path in set(copied)}
    child = None
    try:
        for path in {*package_files, *(code / name for name in resources)}:
            target = root / path.relative_to(code)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            require(digest(target) == before[str(path)], "Code/resource changed during copy")
        for source, target in fixture_dirs:
            shutil.copytree(code / "tests/resources" / source, root / target)
        raw = root / "data/raw"
        raw.mkdir(parents=True)
        for source, target in (
            ("biolink-model-minimal.yaml", "biolink-model.yaml"),
            ("predicate_mapping_minimal.yaml", "predicate_mapping.yaml"),
        ):
            shutil.copyfile(code / "tests/resources" / source, raw / target)
        with gzip.open(root / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz", "wb") as stream:
            stream.write((code / "tests/resources/metatraits_manual_identity.sssom.tsv").read_bytes())
        with tarfile.open(raw / "taxdump.tar.gz", "w:gz") as archive:
            content = b"1\t|\t1\t|\tno rank\t|\n"
            member = tarfile.TarInfo("nodes.dmp")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        require({name: digest(Path(name)) for name in before} == before, "Fixture setup input drift")
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("KG_MICROBE_")
            and key not in {"PYTHONHOME", "PYTHONOPTIMIZE", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"}
        }
        env.update(
            PYTHONPATH=str(root),
            PYTHONDONTWRITEBYTECODE="1",
            KG_MICROBE_BIOLINK_MODEL=str(raw / "biolink-model.yaml"),
            KG_MICROBE_BIOLINK_PREDICATE_MAP=str(raw / "predicate_mapping.yaml"),
        )
        child = subprocess.run(  # noqa: S603 -- this test file and the current interpreter only
            [
                sys.executable,
                "-B",
                *(["-O"] if sys.flags.optimize else []),
                str(Path(__file__).resolve()),
                "--child",
                str(root),
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )
    finally:
        require({name: digest(Path(name)) for name in before} == before, "Code/fixture input drift")
    require(
        child is not None and child.returncode == 0,
        (child.stdout + child.stderr) if child else "Child did not run",
    )
    rows = [
        line.partition("=")[2] for line in child.stdout.splitlines() if line.startswith("EC_EXPORT_INTEGRATION_RESULT=")
    ]
    require(len(rows) == 1, "Missing/ambiguous child outcome")
    result = json.loads(rows[0])
    require(
        set(result) == {consumer + ":" + case for consumer in CONSUMERS for case in CASES},
        "Not all eight actual pipelines reported",
    )
    record_testsuite_property("ec_export_integration", json.dumps(result, sort_keys=True))
    return result


@pytest.mark.parametrize("consumer", CONSUMERS)
@pytest.mark.parametrize("case", CASES)
def test_registered_ec_admission_survives_real_direct_export(integration_results, consumer, case):
    """Reach real export and packaging before accepting or rejecting each optional state."""
    result = integration_results[consumer + ":" + case]
    require(
        result["direct_calls"] == result["packaging_calls"] == result["real_admissions"] == 1,
        "Pipeline count mismatch",
    )
    require(
        result["rejected"] == result["prior_archive_preserved"] == case.startswith("late-"),
        "Wrong publication disposition",
    )


if __name__ == "__main__":
    require(len(sys.argv) == 3 and sys.argv[1] == "--child", "Use pytest or the isolated child entry")
    _child(Path(sys.argv[2]))
