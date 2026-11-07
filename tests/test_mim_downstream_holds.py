"""Keep the exact P3556 downstream hold separate from upstream support (#1799)."""

import csv
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from kg_microbe.utils import chemical_mapping_utils as runtime
from scripts import mim_conservative_refresh as refresh
from tests.test_mim_broader_refresh import _claims, _load, _release
from tests.test_mim_broader_refresh import broader_inputs as broader_fixture
from tests.test_mim_conservative_refresh import FIELDS, NODE_FIELDS, _table

broader_inputs = broader_fixture
DECISION_FIXTURE = Path(__file__).parent / "resources/mim_downstream_hold_20261107/exported-decision.tsv"
DECISION_FIXTURE_SHA256 = "62fe14137bddd13f164ad14ca804fc2b915df7292bd1df09bfd58fec8ca5d09e"


def _actual_exported_decision():
    """Read the immutable full native export record before any synthetic product rebinding."""
    assert hashlib.sha256(DECISION_FIXTURE.read_bytes()).hexdigest() == DECISION_FIXTURE_SHA256
    with DECISION_FIXTURE.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == 1 and len(rows[0]) == 11
    return rows[0]


def test_tracked_hold_binds_complete_native_export_decision():
    """The actual policy must match all eleven native columns without synthetic repair (#1801)."""
    policy = refresh._downstream_hold_policy()
    decision = _actual_exported_decision()
    provenance = json.loads(DECISION_FIXTURE.with_name("provenance.json").read_text())
    assert policy["decision"] == decision
    assert decision["row_sha256"] == policy["row_sha256"]
    assert decision["owner_record_sha256"] == policy["owner_sha256"]
    for field in ("subject_id", "predicate_id", "object_id"):
        assert decision[field] == policy["row"][field]
    for field in ("source_commit", "source_archive_sha256", "manifest_sha256"):
        assert provenance[field] == policy[field]
    assert provenance["fixture_sha256"] == DECISION_FIXTURE_SHA256
    assert provenance["product_sha256"] == "2a075c9c4a699c9d22a5e8b736bc6d7c00c344f19363f28178c0b50b6b590a19"


def _archive(path, policy, body=b"Explicitly synthetic source owner for offline boundary controls.\n", copies=1):
    """Write a tiny test archive with one named regular source owner, never an actual export."""
    with tarfile.open(path, "w:gz") as archive:
        for _ in range(copies):
            entry = tarfile.TarInfo(
                "MediaIngredientMech-" + policy["source_commit"] + "/" + policy["decision"]["owner_record"]
            )
            entry.size = len(body)
            archive.addfile(entry, io.BytesIO(body))
    return hashlib.sha256(body).hexdigest()


def _pin_policy(case, monkeypatch):
    """Bind an explicitly synthetic product/owner while preserving the real claim and local evidence."""
    policy = case["policy"]
    bundle = refresh.validate_reviewed_bundle(
        case["args"]["release_directory"], expected_manifest_sha256=case["args"]["expected_manifest_sha256"]
    )
    for field in ("manifest_sha256", "source_sha256", "review_sha256"):
        policy[field] = getattr(bundle, field)
    policy["decision"] = next(item for item in bundle.disposition_rows if item["row_sha256"] == policy["row_sha256"])
    archive = case["archive"]
    policy["source_archive_sha256"] = refresh._hash(archive)
    case["policy_path"].write_text(json.dumps(policy, sort_keys=True, indent=2) + "\n")
    monkeypatch.setattr(refresh, "HOLD_POLICY", case["policy_path"])
    monkeypatch.setattr(refresh, "HOLD_POLICY_SHA256", refresh._hash(case["policy_path"]))
    case["args"].update(
        provenance_inputs={archive: policy["source_archive_sha256"]},
        upstream_provenance={
            "pin": {
                "source_commit": policy["source_commit"],
                "source_archive": {"sha256": policy["source_archive_sha256"]},
            }
        },
    )
    return bundle


@pytest.fixture
def held_case(broader_inputs, monkeypatch, tmp_path):
    """Combine actual immutable claims/native names with a clearly synthetic signed subset archive."""
    policy = refresh._downstream_hold_policy()
    assert policy["decision"] == _actual_exported_decision()
    rows = [*_claims(), dict(policy["row"])]
    pin = _release(broader_inputs["release_directory"], rows)
    args = dict(broader_inputs, expected_manifest_sha256=pin)
    fixture = json.loads(refresh.HOLD_FIXTURE.read_text())
    baseline = args["baseline"]
    metadata, _ = refresh._header(baseline)
    historical = [item["row"] for item in fixture["mapping_claims"] if item["table"] == "unified"]
    _table(baseline, FIELDS, [*refresh._rows(baseline), *historical], metadata)
    native = args["ontology_paths"][0]
    _table(native, NODE_FIELDS, [*refresh._rows(native), policy["native"]])
    policy["source_commit"] = "a" * 40
    bundle = refresh.validate_reviewed_bundle(args["release_directory"], expected_manifest_sha256=pin)
    policy["decision"] = next(item for item in bundle.disposition_rows if item["row_sha256"] == policy["row_sha256"])
    case = {
        "args": args,
        "policy": policy,
        "rows": rows,
        "archive": tmp_path / "source.tar.gz",
        "policy_path": tmp_path / "synthetic-hold-policy.json",
        "historical": historical,
    }
    policy["owner_sha256"] = _archive(case["archive"], policy)
    _pin_policy(case, monkeypatch)
    return case


def test_actual_claim_is_held_with_full_payload_and_native_controls(held_case, monkeypatch):
    """Hold one complete current claim without changing its product or four native molecular routes."""
    args, policy = held_case["args"], held_case["policy"]
    before = {path: path.read_bytes() for path in args["release_directory"].iterdir()}
    result = refresh.build_conservative_candidate(**args)
    ledger_path = result.directory / "downstream-held.json"
    ledger = json.loads(ledger_path.read_text())
    assert result.report["downstream_held_ledger"] == {
        "name": ledger_path.name,
        "sha256": refresh._hash(ledger_path),
        "rows": 1,
    }
    assert ledger["claims"][0]["row"] == policy["row"]
    assert ledger["claims"][0]["decision"] == policy["decision"]
    assert ledger["claims"][0]["owner_sha256"] == policy["owner_sha256"]
    assert ledger["claims"][0]["supported_ordinal"] == 7
    assert ledger["native_supported_count"] == 7
    assert ledger["eligible_exact_count"] == 4
    assert ledger["eligible_broader_count"] == 2
    assert ledger["downstream_held_count"] == 1
    counts = result.report["counts"]
    assert (
        counts["native_supported_rows"],
        counts["supported_exact_rows"],
        counts["eligible_exact_rows"],
        counts["eligible_supported_rows"],
        counts["downstream_held_rows"],
        counts["native_withheld_rows"],
    ) == (7, 5, 4, 6, 1, 0)
    target = policy["row"]["object_id"]
    assert target in result.report["initial_affected_entities"]
    assert result.report["supported_name_lookup_conflicts"] == []
    assert result.report["supported_xref_lookup_conflicts"] == []
    rows = [row for row in refresh._rows(result.candidate_path) if row["object_id"] == target]
    structured = set(policy["native"]["synonym"].split("|"))
    assert len(rows) == 4
    assert {row["subject_label"] for row in rows} == structured
    assert {row["object_label"] for row in rows} == {policy["authority_label"]}
    assert {row["source"] for row in rows} == {"native_ontology:chebi"}
    assert {row["object_category"] for row in rows} == {policy["native"]["category"]}
    held_history = list(refresh._rows(result.quarantine_path))
    for old in held_case["historical"]:
        assert any(all(item[key] == value for key, value in old.items()) for item in held_history)
    _load(result.candidate_path, monkeypatch)
    assert runtime.find_chebi_by_xref(policy["row"]["subject_id"]) is None
    for generic in [policy["row"]["subject_label"], policy["row"]["other"]]:
        assert runtime.find_chebi_by_name(generic) is None
    for name in structured:
        assert runtime.find_chebi_by_name(name) == target
    assert before == {path: path.read_bytes() for path in before}


def test_held_candidate_second_cycle_is_byte_stable(held_case):
    """Already-clean native molecular rows survive a second pass without reintroducing the held claim."""
    first = refresh.build_conservative_candidate(**held_case["args"])
    second = refresh.build_conservative_candidate(
        **dict(held_case["args"], baseline=first.candidate_path, output_directory=first.directory.with_name("second"))
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    assert first.report["downstream_held_ledger"] == second.report["downstream_held_ledger"]


@pytest.mark.parametrize("field", ["comment", "other", "subject_label"])
def test_changed_held_payload_is_fatal_even_with_signed_product(held_case, field):
    """A new full-row variant must obtain review instead of inheriting the exact finite hold."""
    rows = held_case["rows"]
    rows[-1][field] += " changed"
    held_case["args"]["expected_manifest_sha256"] = _release(held_case["args"]["release_directory"], rows)
    with pytest.raises(ValueError, match="Known downstream-held native claim changed"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()


@pytest.mark.parametrize("kind", ["policy", "fixture", "identity_policy", "review_document"])
def test_changed_hold_authority_bytes_are_fatal(held_case, monkeypatch, tmp_path, kind):
    """Neither altered local curation nor changed original evidence can silently keep the hold active."""
    if kind == "policy":
        held_case["policy_path"].write_text(held_case["policy_path"].read_text() + " ")
    else:
        constant = {"fixture": "HOLD_FIXTURE", "identity_policy": "IDENTITY_POLICY", "review_document": "HOLD_REVIEW"}[
            kind
        ]
        original = getattr(refresh, constant)
        original_bytes = original.read_bytes()
        if kind == "identity_policy":
            root = tmp_path / "identity-policy-root"
            path = root / "mappings" / original.name
            path.parent.mkdir(parents=True)
            for name in ("ingredient_context.py", "ingredient_identity.py", "cas.py", "sssom_identity_policy.py"):
                source = original.parent.parent / "kg_microbe/utils" / name
                copied = root / "kg_microbe/utils" / name
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(source.read_bytes())
                assert copied.read_bytes() == source.read_bytes()
        else:
            path = tmp_path / (kind + ".changed")
        path.write_bytes(original_bytes + b" ")
        assert original.read_bytes() == original_bytes
        assert path.read_bytes() != original_bytes
        monkeypatch.setattr(refresh, constant, path)
    with pytest.raises(ValueError, match="Downstream hold (policy|evidence) identity changed"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()


@pytest.mark.parametrize("change", ["owner_bytes", "duplicate_owner", "owner_decision", "unbound_archive"])
def test_owner_and_actual_archive_binding_cannot_be_substituted(held_case, monkeypatch, change):
    """The hold requires the exact owner decision and one real regular archive member."""
    if change in {"owner_bytes", "duplicate_owner"}:
        kwargs = {"body": b"Changed synthetic owner"} if change == "owner_bytes" else {"copies": 2}
        _archive(held_case["archive"], held_case["policy"], **kwargs)
        _pin_policy(held_case, monkeypatch)
    elif change == "owner_decision":
        held_case["policy"]["decision"]["owner_record"] += ".changed"
        held_case["policy_path"].write_text(json.dumps(held_case["policy"]))
        monkeypatch.setattr(refresh, "HOLD_POLICY_SHA256", refresh._hash(held_case["policy_path"]))
    else:
        held_case["args"]["provenance_inputs"] = {held_case["policy_path"]: refresh._hash(held_case["policy_path"])}
    with pytest.raises(ValueError, match="owner|actual bound input"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()


def test_an_additional_unreviewed_conflict_remains_fatal(held_case, monkeypatch):
    """Recognizing the finite hold never turns other policy conflicts into skippable rows."""
    held_case["rows"].append(dict(held_case["policy"]["row"], subject_id="MIM:Different_generic_material"))
    held_case["args"]["expected_manifest_sha256"] = _release(held_case["args"]["release_directory"], held_case["rows"])
    _pin_policy(held_case, monkeypatch)
    with pytest.raises(ValueError, match="Supported MIM assertion conflicts with current identity policy"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()


def test_held_exact_claim_cannot_license_a_broader_relation(held_case):
    """The original exact row is absent from the only identity set allowed to transport broader claims."""
    args = held_case["args"]
    bundle = refresh.validate_reviewed_bundle(
        args["release_directory"], expected_manifest_sha256=args["expected_manifest_sha256"]
    )
    eligible, held = refresh._supported_partition(
        bundle, refresh._downstream_hold_policy(), args["provenance_inputs"], args["upstream_provenance"]
    )
    assert len(held) == 1
    broad = dict(held_case["policy"]["row"], predicate_id="skos:broadMatch", object_id="CHEBI:6731")
    with pytest.raises(ValueError, match="lacks an exact form identity"):
        refresh._broader_projections(
            [row for row in eligible if row["predicate_id"] == "skos:exactMatch"], [broad], FIELDS, "synthetic_source"
        )


@pytest.mark.parametrize("change", ["missing", "synonym", "category"])
def test_structured_current_native_witness_is_mandatory(held_case, change):
    """Do not substitute the rejected generic preferred label or historical descriptions."""
    native = held_case["args"]["ontology_paths"][0]
    rows = list(refresh._rows(native))
    if change == "missing":
        rows = rows[:-1]
    elif change == "synonym":
        rows[-1]["synonym"] = "unreviewed descriptive name"
    else:
        rows[-1]["category"] = "biolink:ChemicalMixture"
    _table(native, NODE_FIELDS, rows)
    with pytest.raises(ValueError, match="current structured native witness"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()


@pytest.mark.parametrize("change", ["empty_object", "schema_version", "downstream_held_count"])
def test_missing_or_altered_held_ledger_prevents_publication(held_case, monkeypatch, change):
    """Reject missing contents and bool/int substitutions before publication (#1800)."""
    original = Path.write_text

    def altered(path, content, *args, **kwargs):
        """Simulate corruption at the held-ledger output boundary only."""
        if path.name == "downstream-held.json":
            payload = {} if change == "empty_object" else json.loads(content)
            if change != "empty_object":
                payload[change] = True
            content = json.dumps(payload, sort_keys=True, indent=2) + "\n"
        return original(path, content, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", altered)
    with pytest.raises(ValueError, match="Mandatory downstream-held ledger differs"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()


def test_altered_full_row_hash_is_not_a_hold_override(held_case, monkeypatch):
    """Even a re-signed synthetic policy cannot mismatch the complete native payload identity."""
    held_case["policy"]["row_sha256"] = "0" * 64
    held_case["policy_path"].write_text(json.dumps(held_case["policy"]))
    monkeypatch.setattr(refresh, "HOLD_POLICY_SHA256", refresh._hash(held_case["policy_path"]))
    with pytest.raises(ValueError, match="Downstream hold full-row identity differs"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()


def test_changed_source_product_binding_requires_review(held_case):
    """Preserve a valid full partition while demonstrating that changed release identity is not approved."""
    rows = held_case["rows"]
    rows[0]["comment"] = "Changed unrelated source payload"
    held_case["args"]["expected_manifest_sha256"] = _release(held_case["args"]["release_directory"], rows)
    with pytest.raises(ValueError, match="Downstream-held source binding changed"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()


def test_held_ledger_drift_after_report_prevents_publication(held_case, monkeypatch):
    """The final boundary also binds the mandatory ledger after its report was written."""
    original = Path.write_text

    def changed_after_report(path, content, *args, **kwargs):
        """Change only the ledger after its initial exact-byte verification."""
        result = original(path, content, *args, **kwargs)
        if path.name == "report.json":
            ledger = path.with_name("downstream-held.json")
            original(ledger, ledger.read_text() + " ")
        return result

    monkeypatch.setattr(Path, "write_text", changed_after_report)
    with pytest.raises(ValueError, match="Mandatory downstream-held ledger changed before publication"):
        refresh.build_conservative_candidate(**held_case["args"])
    assert not held_case["args"]["output_directory"].exists()
