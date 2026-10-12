"""Ambiguous GSS name joins are audited upstream, never decided by row order (#1292)."""

import csv
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest

from kg_microbe.transform_utils.lpsn.lpsn import (
    GSS_NATIVE_INPUT,
    PARENT_DISPOSITIONS_FILE,
    LPSNTransform,
)
from kg_microbe.utils.producer_audits import verify_producer_audits
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

FIXTURE = Path(__file__).parent / "resources/lpsn_parent_ambiguity.csv"


class NoCrosswalk:
    """Keep native GSS parent tests offline and independent of external taxonomy."""

    def curies_by_label(self, label):
        """Return no external NCBI candidate."""
        return []

    def curies_by_rank_name(self, rank, name):
        """Return no external GTDB candidate."""
        return []


def make_transform(tmp_path, *, records=None):
    """Use the genuine parser/emitter on immutable or explicitly mutated synthetic input."""
    raw = tmp_path / "raw"
    raw.mkdir(parents=True)
    native = raw / "lpsn_gss.csv"
    if records is None:
        shutil.copyfile(FIXTURE, native)
    else:
        with FIXTURE.open(newline="") as stream:
            header = next(csv.reader(stream))
        with native.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=header, lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
    return LPSNTransform(
        input_dir=raw, output_dir=tmp_path / "output", ncbi_impl=NoCrosswalk(), gtdb_index=NoCrosswalk()
    )


def rows(path):
    """Read a small test TSV with its actual quoting convention."""
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def fixture_records():
    """Return independent mutable copies of the clearly synthetic native examples."""
    with FIXTURE.open(newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.mark.parametrize("status", ["current name", "synonym"])
def test_ambiguous_parent_is_never_status_or_order_tiebroken(tmp_path, status):
    """Both all-current and all-synonym groups retain every candidate without a guessed parent."""
    source = fixture_records()
    for record in source:
        record["status"] = status
    sets, audits = [], []
    for direction, records in (("forward", source), ("reverse", list(reversed(source)))):
        transform = make_transform(tmp_path / direction, records=records)
        transform.run()
        sets.append({tuple(sorted(row.items())) for row in rows(transform.output_edge_file)})
        audits.append({row["subject"]: row for row in rows(transform.output_dir / PARENT_DISPOSITIONS_FILE)})
        assert len(rows(transform.output_node_file)) == 8
        assert {
            row["subject"] for row in rows(transform.output_edge_file) if row["predicate"] == "biolink:subclass_of"
        } == {"lpsn:41"}
    assert sets[0] == sets[1]
    assert set(audits[0]) == set(audits[1]) == {"lpsn:20", "lpsn:21", "lpsn:30"}
    for subject in audits[0]:
        assert audits[0][subject]["candidate_ids_json"] == audits[1][subject]["candidate_ids_json"]
        assert audits[0][subject]["legacy_projection_json"] != audits[1][subject]["legacy_projection_json"]


def test_audit_preserves_complete_literal_records_and_every_candidate(tmp_path):
    """Native text, fields, physical coordinates, identities and counterfactual edge semantics remain recoverable."""
    source = fixture_records()
    source[0]["authors"] = 'Line one\nLine two, with "quotes"'
    transform = make_transform(tmp_path, records=source)
    transform.run()
    native = transform.input_base_dir / "lpsn_gss.csv"
    original_lines = native.read_text().splitlines(keepends=True)
    audit = rows(transform.output_dir / PARENT_DISPOSITIONS_FILE)
    for entry in audit:
        assert entry["source_path"] == str(native.resolve())
        assert entry["source_sha256"] == hashlib.sha256(native.read_bytes()).hexdigest()
        assert "not an explicit native" in entry["legacy_projection_basis"]
        records = [json.loads(entry["child_record_json"]), *json.loads(entry["candidate_records_json"]).values()]
        for record in records:
            literal = record["literal_csv"]
            assert literal == "".join(
                original_lines[record["starting_physical_line"] - 1 : record["ending_physical_line"]]
            )
            assert hashlib.sha256(literal.encode()).hexdigest() == record["literal_sha256"]
            parsed = list(csv.reader(io.StringIO(literal), strict=True))
            assert len(parsed) == 1
            assert parsed[0] == [record["row"][column] for column in source[0]]
        proposals = json.loads(entry["candidate_projections_json"])
        assert {proposal["object"] for proposal in proposals} == set(json.loads(entry["candidate_ids_json"]))
        assert all(proposal["subject"] == entry["subject"] for proposal in proposals)
    verify_producer_audits(transform)
    transform.verify_consumed_inputs()
    assert b"\r\n" not in (transform.output_dir / PARENT_DISPOSITIONS_FILE).read_bytes()


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate",
        "missing-id",
        "unicode-id",
        "zero-id",
        "missing-genus",
        "subspecies-only",
        "short-row",
        "extra-column",
        "bad-quote",
        "duplicate-header",
        "missing-header",
    ],
)
def test_bad_native_candidates_abort_before_any_graph_or_audit(tmp_path, damage):
    """An invalid candidate is not silently removed to manufacture uniqueness."""
    source = fixture_records()
    if damage == "duplicate":
        source.append(dict(source[0]))
    elif damage in {"missing-id", "unicode-id", "zero-id"}:
        source[0]["record_no"] = {"missing-id": "", "unicode-id": "١٠", "zero-id": "0"}[damage]
    elif damage == "missing-genus":
        source[0]["genus_name"] = ""
    elif damage == "subspecies-only":
        source[0]["subsp_epithet"] = "invalid"
    transform = make_transform(tmp_path, records=source)
    native = transform.input_base_dir / "lpsn_gss.csv"
    text = native.read_text()
    lines = text.splitlines(keepends=True)
    if damage == "short-row":
        lines[1] = "Ambigua,\n"
    elif damage == "extra-column":
        lines[1] = lines[1].rstrip("\n") + ",unexpected\n"
    elif damage == "bad-quote":
        lines[-1] = '"unterminated\n'
    elif damage == "duplicate-header":
        lines[0] = lines[0].replace("authors", "reference")
    elif damage == "missing-header":
        lines = []
    native.write_text("".join(lines))
    with pytest.raises((ValueError, csv.Error)):
        transform.run()
    assert not transform.output_node_file.exists()
    assert not transform.output_edge_file.exists()
    assert not (transform.output_dir / PARENT_DISPOSITIONS_FILE).exists()
    with pytest.raises(SourceFinalizationRequired):
        verify_producer_audits(transform)


@pytest.mark.parametrize("empty", [False, True])
def test_nonambiguous_and_empty_cohorts_still_bind_input_and_audit(tmp_path, empty):
    """Missing parent, genus without GSS parent and valid header-only input do not create false ambiguity."""
    source = [] if empty else fixture_records()[5:]
    transform = make_transform(tmp_path, records=source)
    transform.run()
    assert rows(transform.output_dir / PARENT_DISPOSITIONS_FILE) == []
    assert len(rows(transform.output_node_file)) == len(source)
    assert set(transform.consumed_input_snapshots) == {GSS_NATIVE_INPUT}
    verify_producer_audits(transform)
    transform.verify_consumed_inputs()


@pytest.mark.parametrize("damage", ["remove", "change", "unrecorded"])
def test_empty_audit_cannot_be_omitted_or_restamped(tmp_path, damage):
    """Registered producer contracts apply even when no ambiguity was observed."""
    transform = make_transform(tmp_path, records=[])
    transform.run()
    path = transform.output_dir / PARENT_DISPOSITIONS_FILE
    if damage == "remove":
        path.unlink()
    elif damage == "change":
        path.write_bytes(path.read_bytes() + b"changed\n")
    else:
        transform._producer_audit_snapshots.clear()
    with pytest.raises(SourceFinalizationRequired):
        verify_producer_audits(transform)
    with pytest.raises(SourceFinalizationRequired):
        transform.finalize(fresh_run=True)


def test_actual_override_is_bound_and_late_native_mutation_refused(tmp_path):
    """A data_file override, not the unused default pathname, supplies the immutable epoch."""
    transform = make_transform(tmp_path)
    override = tmp_path / "selected.csv"
    shutil.copyfile(FIXTURE, override)
    transform.run(data_file=override)
    assert transform.consumed_input_snapshots[GSS_NATIVE_INPUT]["path"] == str(override.resolve())
    override.write_bytes(override.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired, match="changed or missing"):
        transform.verify_consumed_inputs()
    with pytest.raises(SourceFinalizationRequired):
        transform.finalize(fresh_run=True)


def test_native_mutation_during_emission_leaves_no_new_outputs(tmp_path, monkeypatch):
    """Consumed CSV drift is caught before any new file is committed."""
    transform = make_transform(tmp_path)
    original = transform._make_node_row

    def mutate(record_no, row):
        """Change the original native input during row emission."""
        native = transform.input_base_dir / "lpsn_gss.csv"
        native.write_bytes(native.read_bytes() + b"\n")
        return original(record_no, row)

    monkeypatch.setattr(transform, "_make_node_row", mutate)
    with pytest.raises(SourceFinalizationRequired):
        transform.run()
    assert not transform.output_node_file.exists()
    assert not transform.output_edge_file.exists()
    assert not (transform.output_dir / PARENT_DISPOSITIONS_FILE).exists()


def test_audit_registration_failure_is_not_fresh_completion(tmp_path, monkeypatch):
    """Per-file emission is not a completed generation without its mandatory audit binding."""
    transform = make_transform(tmp_path)

    def refuse(name):
        """Inject audit registration failure before successful finalization."""
        raise RuntimeError("injected registration failure")

    monkeypatch.setattr(transform, "record_producer_audit", refuse)
    with pytest.raises(RuntimeError, match="registration"):
        transform.run()
    with pytest.raises(SourceFinalizationRequired):
        transform.finalize(fresh_run=True)
