"""Actual public finalization, source-marker and admission coverage for the finite parent cohort."""

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe.utils import ontology_parent_quarantine as native
from kg_microbe.utils.source_finalization import graph_rows, verify_finalized_source_files
from tests.native_ro_fixtures import bind_native_ro_fixture_policy, stage_native_ro_envo

FIXTURE = Path(__file__).parent / "resources/ontology_parent_dispositions"


@pytest.fixture(scope="module", params=("both", "foodon", "envo"))
def finalized_seed(tmp_path_factory, request):
    """Exercise the real dispatcher, normalizer, finalizer and marker without synthetic success records."""
    scope = request.param
    root = tmp_path_factory.mktemp("parent-public-" + scope)
    raw = root / "raw"
    raw.mkdir()
    for name in ("foodon.json", "envo.json", "po.owl"):
        shutil.copyfile(FIXTURE / "lifecycle" / name, raw / name)
    shutil.copyfile(FIXTURE / "foodon.owl", raw / "foodon.owl")
    stage_native_ro_envo(raw)
    script = r"""
import csv, hashlib, importlib, json, socket, sys
from pathlib import Path
def offline(*args, **kwargs):
    raise AssertionError("Parent lifecycle test may not contact a live service")
socket.getaddrinfo = offline
socket.socket.connect = offline
from kg_microbe.transform_utils.ontologies import ontologies_transform as module
dispatcher = importlib.import_module("kg_microbe.transform")
from kg_microbe.utils import transform_fingerprint as fingerprints
from kg_microbe.merge_utils import source_freshness
from kg_microbe.merge_utils.merge_kg import _assert_sources_finalized
from kg_microbe.utils.source_finalization import verify_finalized_source_files
from kg_microbe.utils import ontology_parent_quarantine as native
raw, output, scope = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
from tests.native_ro_fixtures import bind_native_ro_fixture_policy
bind_native_ro_fixture_policy(raw)
schemas = tuple(Path(value) for value in sys.argv[4:6])
fingerprints.SCHEMA_FILES = source_freshness.SCHEMA_FILES = schemas
module.ONTOLOGIES_MAP = {"foodon": "foodon.json", "envo": "envo.json"}
instances = []
original_init = module.OntologiesTransform.__init__
def capture_instance(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    instances.append(self)
module.OntologiesTransform.__init__ = capture_instance
dispatcher._run_one("ontologies" if scope == "both" else scope, raw, output, False)
original = instances[-1]
prefix = "" if scope == "both" else scope + "_"
report_path = original.output_dir / (prefix + "source_finalization.json")
assert report_path.is_file()
report = json.loads(report_path.read_text())
names = sorted(report["members"])
selected = ("foodon", "envo") if scope == "both" else (scope,)
expected_names = sorted(f"{source}_{kind}.tsv" for source in selected for kind in ("nodes", "edges"))
assert names == expected_names
assert report["producer_native_inputs"]["ontology_parent_dispositions"]["members"] == names
paths = [original.output_dir / name for name in names]
before = {name: (original.output_dir / name).read_bytes() for name in names}
original.verify_consumed_inputs()
assert original.finalize(file_prefix=prefix) == report
original.verify_consumed_inputs()
fresh = module.OntologiesTransform(raw, output)
assert fresh.finalize(file_prefix=prefix) == report
fresh.verify_consumed_inputs()
assert {name: (original.output_dir / name).read_bytes() for name in names} == before
verify_finalized_source_files(paths)
audit = native._read_tsv(
    (original.output_dir / native.AUDIT_FILE).read_bytes(),
    fields=native.AUDIT_FIELDS, quoting=csv.QUOTE_MINIMAL,
)
assert len(audit) == {"both": 14, "foodon": 13, "envo": 1}[scope]
marker = original.output_dir / "source_fingerprint.json"
if scope == "both":
    assert marker.is_file(), "Real _run_one must publish a current fingerprint"
    dispatcher._record_fingerprint(original, "ontologies")
    assert marker.is_file(), "Same-object marker must survive the legitimate publication rename"
    dispatcher._record_fingerprint(fresh, "ontologies")
    assert marker.is_file(), "Fresh-object repeat must retain complete dynamic native guards"
    config = original.output_dir / "admission-fixture.yaml"
    config_document = {
        "configuration": {},
        "merged_graph": {"source": {"reviewed_fixture": {
            "input": {"format": "tsv", "filename": [str(path) for path in paths]},
        }}},
    }
    config.write_text(json.dumps(config_document))
    admission = _assert_sources_finalized(config)
    admission.verify(metadata_only=True)
else:
    assert not marker.exists(), "One selected ontology must not certify whole-source freshness"
print(report_path)
"""
    model = FIXTURE.parent / "ingredient_bundle/native"
    result = subprocess.run(  # noqa: S603 - fixed offline fixture script
        [
            sys.executable,
            "-c",
            script,
            str(raw),
            str(root / "transformed"),
            scope,
            str(model / "biolink-model.yaml"),
            str(model / "predicate_mapping.yaml"),
        ],
        cwd=Path(__file__).parents[1],
        env={
            **os.environ,
            "KG_MICROBE_BIOLINK_MODEL": str(model / "biolink-model.yaml"),
            "KG_MICROBE_BIOLINK_PREDICATE_MAP": str(model / "predicate_mapping.yaml"),
        },
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = "" if scope == "both" else scope + "_"
    return root / "transformed/ontologies", prefix, scope


@pytest.fixture
def public_candidate(finalized_seed, tmp_path, monkeypatch):
    """Keep primary authority receipts immutable while changing only a disposable published candidate."""
    source, prefix, scope = finalized_seed
    bind_native_ro_fixture_policy(source.parents[1] / "raw", monkeypatch)
    directory = tmp_path / "published"
    shutil.copytree(source, directory)
    report_path = directory / (prefix + "source_finalization.json")
    return directory, report_path, json.loads(report_path.read_text()), scope


def _identity(path):
    """Compute an explicit outer receipt for a deliberate tampering probe."""
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _restamp(report_path, report, name):
    """Change outer artifact receipts, never the independently selected native policy."""
    identity = _identity(report_path.parent / name)
    for field in ("members", "audit_members", "producer_audit_members"):
        if name in report.get(field, {}):
            report[field][name] = identity
    report_path.write_text(json.dumps(report, sort_keys=True))


def _write(path, rows, fields, quoting):
    """Retain all unaffected row fields and the actual final TSV dialect."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            delimiter="\t",
            quoting=quoting,
            quotechar=None if quoting == csv.QUOTE_NONE else '"',
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _admit(directory, report):
    """Use the real public finalized-source admission, not just the source-specific helper."""
    return verify_finalized_source_files([directory / name for name in report["members"]])


def test_nonempty_full_lifecycle_and_selected_supplier_reports(public_candidate):
    """The subprocess already exercised actual run/finalize/repeats/markers; re-admit the immutable bytes."""
    directory, _, report, scope = public_candidate
    assert scope in {"both", "foodon", "envo"}
    _admit(directory, report)


@pytest.mark.parametrize("damage", ["drop_one", "omit_supplier", "erase_original", "changed_uuid"])
def test_coherently_restamped_nonempty_audit_is_not_authority(public_candidate, damage):
    """Partial native cohorts and changed converter traces fail even with matching outer receipts."""
    directory, report_path, report, scope = public_candidate
    path = directory / native.AUDIT_FILE
    rows = native._read_tsv(path.read_bytes(), fields=native.AUDIT_FIELDS, quoting=csv.QUOTE_MINIMAL)
    if damage == "drop_one":
        rows.pop()
    elif damage == "omit_supplier":
        if scope == "both":
            rows = [row for row in rows if row["ontology"] == "envo"]
        else:
            # Same scope and nonzero row count; one prior claim is silently substituted.
            rows[0]["ontology"] = "envo" if scope == "foodon" else "foodon"
    elif damage == "erase_original":
        rows[0]["normalization_input_row_json"] = "{}"
    else:
        original = json.loads(rows[0]["normalization_input_row_json"])
        original["id"] = "urn:uuid:00000000-0000-4000-8000-000000000001"
        rows[0]["normalization_input_row_json"] = native.canonical(original)
    _write(path, rows, native.AUDIT_FIELDS, csv.QUOTE_MINIMAL)
    _restamp(report_path, report, path.name)
    with pytest.raises(ValueError, match="parent.*audit|audit.*native"):
        _admit(directory, report)


@pytest.mark.parametrize("damage", ["removed", "same_count_changed_relation", "invented_publication", "reinsert"])
def test_coherently_restamped_retained_graph_scope(public_candidate, damage):
    """Rejoin finalized full claims, not just pre-finalization S/P/O or row counts."""
    directory, report_path, report, scope = public_candidate
    supplier = "envo" if scope == "envo" else "foodon"
    path = directory / f"{supplier}_edges.tsv"
    rows = list(graph_rows(path))
    ids = set(json.loads(native.POLICY_FILE.read_text())["sources"][supplier]["incident_ids"])
    index = next(i for i, row in enumerate(rows) if row["subject"] in ids)
    if damage == "removed":
        rows.pop(index)
    elif damage == "same_count_changed_relation":
        rows[index]["relation"] = "biolink:related_to"
    elif damage == "invented_publication":
        rows[index]["publications"] = "PMID:99999999"
    else:
        spec = json.loads(native.POLICY_FILE.read_text())["sources"][supplier]
        selected = native._reject_key(spec["quarantines"][0])
        original = next(row for row in spec["source_incidence"] if native._key(row) == selected)
        rows.append({column: original.get(column, "") for column in rows[0]})
    _write(path, rows, tuple(rows[0]), csv.QUOTE_NONE)
    _restamp(report_path, report, path.name)
    with pytest.raises(ValueError, match="parent retained graph"):
        _admit(directory, report)


@pytest.mark.parametrize("damage", ["clear_members", "omit_supplier_roles"])
def test_nonempty_public_report_cannot_be_restamped_as_empty_scope(public_candidate, damage):
    """Actual selected graph members independently determine the expected native cohort."""
    directory, report_path, report, scope = public_candidate
    if damage == "clear_members":
        report["producer_native_inputs"]["ontology_parent_dispositions"]["members"] = []
    else:
        supplier = "envo" if scope == "envo" else "foodon"
        for role in tuple(report["consumed_inputs"]):
            if role.startswith(f"ontology_parent_{supplier}_"):
                report["consumed_inputs"].pop(role)
    report_path.write_text(json.dumps(report, sort_keys=True))
    expected = (
        "Native ontology recorded input contract missing or changed$"
        if damage == "clear_members"
        else "native.*contract|parent.*role|parent.*scope"
    )
    with pytest.raises(ValueError, match=expected):
        _admit(directory, report)


def test_public_native_admission_retains_output_binding(public_candidate):
    """A selected graph mutation after successful complete admission cannot escape the late check."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

    directory, report_path, report, scope = public_candidate
    _admit(directory, report)
    guard = SourceAdmission()
    OntologiesTransform.verify_recorded_native_inputs(report, report_path, admission=guard)
    supplier = "envo" if scope == "envo" else "foodon"
    path = directory / f"{supplier}_edges.tsv"
    with path.open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="admitted file changed"):
        guard.verify(metadata_only=True)
