"""Exercise pinned release validation with small, offline immutable examples."""

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest
import yaml

from scripts import mim_reviewed_release as release

FIELDS = (
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "confidence",
    "other",
)
SUPPORTED = (
    "MIM:Water",
    "Water",
    "skos:exactMatch",
    "CHEBI:15377",
    "water",
    "semapv:ManualMappingCuration",
    "0.9",
    "H₂O",
)
WITHHELD = (
    "MIM:Sample",
    "Sample",
    "skos:broadMatch",
    "CHEBI:15377",
    "water",
    "semapv:ManualMappingCuration",
    "0.5",
    "",
)
PREFIXES = {
    "MIM": "https://example.org/mim/",
    "CHEBI": "http://purl.obolibrary.org/obo/CHEBI_",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "semapv": "https://w3id.org/semapv/vocab/",
}


def _tsv(fields, rows):
    """Serialize immutable example rows in the publisher's TSV dialect."""
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def _metadata(group):
    """Provide a complete local-only SSSOM metadata example."""
    return {
        "curie_map": dict(PREFIXES),
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "mapping_set_id": f"https://example.org/mappings/{group}",
        "mapping_set_version": "2026-09-21",
        "predicate_semantics": "skos",
    }


def _sssom(metadata, rows):
    """Serialize the fixture metadata followed by its mapping table."""
    header = "".join(f"# {line}\n" for line in yaml.safe_dump(metadata).splitlines())
    return header + _tsv(FIELDS, rows)


def _hash_row(row):
    """Use the upstream publisher's documented canonical JSON serialization."""
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _decision(row, position, disposition):
    """Attach minimal explicit review provenance to an immutable assertion."""
    return {
        "source_position": str(position),
        "row_sha256": _hash_row(row),
        "subject_id": row["subject_id"],
        "predicate_id": row["predicate_id"],
        "object_id": row["object_id"],
        "owner_record": f"data/ingredients/mapped/record-{position}.yaml",
        "owner_record_sha256": "a" * 64,
        "disposition": disposition,
        "review_reason": "Fixture explicit mapping decision.",
        "review_evidence": "reports/fixture.json",
        "evidence_key": str(position),
    }


@pytest.fixture
def bundle(tmp_path):
    """Construct two-row release products exclusively under pytest's tmp_path."""
    supported = dict(zip(FIELDS, SUPPORTED, strict=True))
    withheld = dict(zip(FIELDS, WITHHELD, strict=True))
    (tmp_path / release.SUPPORTED_FILE).write_text(_sssom(_metadata("supported"), [supported]))
    (tmp_path / release.WITHHELD_FILE).write_text(_sssom(_metadata("withhold"), [withheld]))
    dispositions = [_decision(supported, 1, "SUPPORTED"), _decision(withheld, 2, "WITHHOLD")]
    (tmp_path / release.DISPOSITIONS_FILE).write_text(_tsv(release.DISPOSITION_FIELDS, dispositions))
    manifest = {
        "schema_version": 1,
        "scope": "MIM-only reviewed SSSOM; no KGX dependency",
        "semantic_status": "PASS_SUPPORTED_SUBSET",
        "source_sssom": "mappings/ingredient_mappings.sssom.tsv",
        "source_sha256": "b" * 64,
        "review_sha256": "c" * 64,
        "counts": {"source": 2, "supported": 1, "withhold": 1},
        "mapping_set_ids": {group: _metadata(group)["mapping_set_id"] for group in ("supported", "withhold")},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path, _repin(tmp_path)


def _repin(directory, mutation=None):
    """Reissue a synthetic fixture so tests reach checks beyond byte integrity."""
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"] = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in release.PRODUCT_FILES
    }
    if mutation:
        mutation(manifest)
    path.write_text(json.dumps(manifest))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decisions(directory, mutate):
    """Alter an explicit decision without changing the mapping payload."""
    path = directory / release.DISPOSITIONS_FILE
    rows = list(csv.DictReader(io.StringIO(path.read_text()), delimiter="\t"))
    mutate(rows)
    path.write_text(_tsv(release.DISPOSITION_FIELDS, rows))
    return _repin(directory)


def test_valid_bundle_preserves_rows_metadata_and_provenance(bundle):
    """Keep the supported and withheld partitions separate and do not write."""
    directory, pin = bundle
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    result = release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)
    assert result.directory == directory.resolve()
    assert result.manifest_sha256 == pin
    assert result.source_sha256 == "b" * 64
    assert result.review_sha256 == "c" * 64
    assert result.supported_rows[0]["other"] == "H₂O"
    assert result.withheld_rows[0]["predicate_id"] == "skos:broadMatch"
    assert result.supported_metadata["mapping_set_id"] != result.withheld_metadata["mapping_set_id"]
    assert [row["disposition"] for row in result.disposition_rows] == ["SUPPORTED", "WITHHOLD"]
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}


def test_row_hash_uses_sorted_compact_unicode_json():
    """Match upstream bytes, including empty strings and unescaped Unicode."""
    assert release.row_sha256({"z": "α", "a": ""}) == hashlib.sha256(b'{"a":"","z":"\xce\xb1"}').hexdigest()


@pytest.mark.parametrize("filename", ["manifest.json", *sorted(release.PRODUCT_FILES)])
def test_modified_or_missing_artifact_fails(bundle, filename):
    """A pinned bundle rejects even whitespace-only changes and incomplete copies."""
    directory, pin = bundle
    path = directory / filename
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)
    path.unlink()
    with pytest.raises(ValueError, match="Missing or unsafe"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda m: m.update(schema_version=True), "schema_version"),
        (lambda m: m.update(schema_version=2), "schema_version"),
        (lambda m: m.update(scope="KGX complete release"), "MIM-only"),
        (lambda m: m.update(semantic_status="PASS"), "PASS_SUPPORTED_SUBSET"),
        (lambda m: m["files"].update({"../outside.tsv": "a" * 64}), "fixed product filenames"),
        (lambda m: m["files"].update({release.SUPPORTED_FILE: "bad"}), "Invalid SHA-256"),
        (lambda m: m.update(source_sha256="invalid"), "Invalid SHA-256"),
        (lambda m: m.update(review_sha256=None), "Invalid SHA-256"),
        (lambda m: m.update(source_sssom="../outside.tsv"), "relative path"),
        (lambda m: m["counts"].update(source=3), "release counts"),
        (lambda m: m["counts"].update(source=True), "release counts"),
        (lambda m: m["counts"].update(supported=2, source=3), "row count"),
        (lambda m: m["mapping_set_ids"].update(withhold=m["mapping_set_ids"]["supported"]), "distinct"),
        (lambda m: m["mapping_set_ids"].update(supported="https://example.org/other"), "mapping_set_id"),
    ],
)
def test_manifest_contract_is_validated_even_with_matching_hashes(bundle, mutation, match):
    """Byte-integrity checks alone do not establish a valid release contract."""
    directory, _ = bundle
    pin = _repin(directory, mutation)
    with pytest.raises(ValueError, match=match):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("source_position", "2", "duplicate source_position"),
        ("source_position", "3", "gap-free"),
        ("source_position", "0", "source_position"),
        ("source_position", "1.0", "source_position"),
        ("disposition", "UNKNOWN", "Invalid mapping disposition"),
        ("disposition", "WITHHOLD", "partition disagrees"),
        ("row_sha256", "d" * 64, "partition disagrees"),
        ("object_id", "CHEBI:1", "partition disagrees"),
        ("owner_record_sha256", "bad", "Invalid SHA-256"),
        ("review_reason", "", "Missing disposition"),
        ("review_evidence", "/outside.json", "relative path"),
    ],
)
def test_partition_requires_exact_decisions_and_source_coverage(bundle, field, value, match):
    """Bind every disposition to its complete original row and unique position."""
    directory, _ = bundle
    pin = _decisions(directory, lambda rows: rows[0].update({field: value}))
    with pytest.raises(ValueError, match=match):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


@pytest.mark.parametrize(
    "old,new,match",
    [
        ("skos:exactMatch", "skos:closeMatch", "skos:exactMatch"),
        ("MIM:Water", "CHEBI:Water", "Non-MIM"),
        ("H₂O", "unreviewed alias", "row hashes"),
        ("# predicate_semantics: skos", "# predicate_semantics: legacy", "predicate_semantics"),
        ("\t0.9\t", "\tNaN\t", "finite"),
    ],
)
def test_supported_payload_cannot_change_under_old_decisions(bundle, old, new, match):
    """A rehashed file cannot silently change predicate, scope, or reviewed aliases."""
    directory, _ = bundle
    path = directory / release.SUPPORTED_FILE
    path.write_text(path.read_text().replace(old, new))
    pin = _repin(directory)
    with pytest.raises(ValueError, match=match):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


def test_schema_validation_rejects_bad_confidence(bundle):
    """Actually exercise installed SSSOM validation, rather than mocking it."""
    directory, _ = bundle
    path = directory / release.SUPPORTED_FILE
    path.write_text(path.read_text().replace("\t0.9\t", "\t2.0\t"))
    pin = _repin(directory)
    with pytest.raises(Exception, match="(?i)confidence|maximum|validation"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


def test_duplicate_metadata_keys_are_rejected(bundle):
    """Duplicate JSON/YAML keys cannot silently override pinned metadata."""
    directory, _ = bundle
    path = directory / "manifest.json"
    path.write_text(path.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Duplicate key"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


@pytest.mark.parametrize("defect", ["duplicate_yaml", "duplicate_columns", "extra_cell", "missing_cell"])
def test_malformed_sssom_is_rejected(bundle, defect):
    """Reject ambiguous metadata and table shapes before interpreting assertions."""
    directory, _ = bundle
    path = directory / release.SUPPORTED_FILE
    content = path.read_text()
    if defect == "duplicate_yaml":
        content = "# predicate_semantics: skos\n" + content
    elif defect == "duplicate_columns":
        content = content.replace("subject_label\t", "subject_id\t")
    elif defect == "extra_cell":
        content = content.rstrip("\n") + "\textra\n"
    else:
        content = content.replace("\tH₂O", "")
    path.write_text(content)
    pin = _repin(directory)
    with pytest.raises(ValueError, match="Duplicate key|columns|row width"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


def test_undeclared_curie_prefix_is_rejected(bundle):
    """The actual SSSOM prefix validator must reject missing CURIE declarations."""
    directory, _ = bundle
    path = directory / release.SUPPORTED_FILE
    path.write_text(path.read_text().replace("CHEBI:15377", "Undeclared:15377"))
    pin = _repin(directory)
    with pytest.raises(Exception, match="(?i)prefix|validation"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


def test_symlinked_product_is_rejected(bundle, tmp_path):
    """A safe fixed filename must also refer to a regular bundle file."""
    directory, pin = bundle
    path = directory / release.SUPPORTED_FILE
    target = tmp_path / "outside.tsv"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="unsafe release file"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


def _replace_reviewed_rows(directory, supported, withheld, *, metadata=None):
    """Bind a complete synthetic review to new rows so deeper semantic guards are reached."""
    fields = list(supported[0])
    decisions = []
    for group, filename, rows, disposition in (
        ("supported", release.SUPPORTED_FILE, supported, "SUPPORTED"),
        ("withhold", release.WITHHELD_FILE, withheld, "WITHHOLD"),
    ):
        header = _metadata(group)
        header["curie_map"].update(
            {
                "kgmicrobe.compound": "https://w3id.org/kg-microbe/compound/",
                "cas": "https://example.org/cas/",
                "obo": "http://purl.obolibrary.org/obo/",
                "kgm": "https://w3id.org/kg-microbe/",
                "registry": "https://w3id.org/kg-microbe/registry/",
            }
        )
        header["extension_definitions"] = [
            {"slot_name": name, "property": "https://example.org/" + name, "type_hint": "xsd:string"}
            for name in ("source", "validation_method")
            if name in fields
        ]
        if metadata:
            header.update(metadata[group])
            header = {key: value for key, value in header.items() if value is not None}
        text = "".join(f"# {line}\n" for line in yaml.safe_dump(header).splitlines())
        (directory / filename).write_text(text + _tsv(fields, rows))
        for row in rows:
            decisions.append(_decision(row, len(decisions) + 1, disposition))
    (directory / release.DISPOSITIONS_FILE).write_text(_tsv(release.DISPOSITION_FIELDS, decisions))
    return _repin(
        directory,
        lambda manifest: manifest.update(
            counts={"source": len(decisions), "supported": len(supported), "withhold": len(withheld)}
        ),
    )


def _dated_rows():
    """Use the current release's two distinct subset dates in a tiny synthetic partition."""
    supported = dict(zip(FIELDS, SUPPORTED, strict=True), mapping_date="2026-11-01")
    withheld = dict(zip(FIELDS, WITHHELD, strict=True), mapping_date="2026-11-03")
    metadata = {
        "supported": {"mapping_date": "2026-11-01", "mapping_set_version": "2026-11-01"},
        "withhold": {"mapping_date": "2026-11-03", "mapping_set_version": "2026-11-03"},
    }
    return [supported], [withheld], metadata


def test_subset_dates_preserve_distinct_reviewed_versions(bundle):
    """A common manifest and complete partition bind products whose true subset dates differ."""
    directory, _ = bundle
    supported, withheld, metadata = _dated_rows()
    pin = _replace_reviewed_rows(directory, supported, withheld, metadata=metadata)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    result = release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)
    assert result.supported_metadata["mapping_set_version"] == "2026-11-01"
    assert result.withheld_metadata["mapping_set_version"] == "2026-11-03"
    assert result.supported_rows == tuple(supported)
    assert result.withheld_rows == tuple(withheld)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


def test_old_equal_date_release_stays_valid(bundle):
    """The historical native recipe's equal dates remain valid without rewriting metadata."""
    directory, _ = bundle
    supported, withheld, metadata = _dated_rows()
    for row in supported + withheld:
        row["mapping_date"] = "2026-09-24"
    for values in metadata.values():
        values.update(mapping_date="2026-09-24", mapping_set_version="2026-09-24")
    pin = _replace_reviewed_rows(directory, supported, withheld, metadata=metadata)
    result = release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)
    assert result.supported_metadata["mapping_date"] == result.withheld_metadata["mapping_date"] == "2026-09-24"


@pytest.mark.parametrize(
    "field,value",
    [("mapping_date", "2026-11-03"), ("mapping_set_version", "2026-11-03"), ("mapping_date", None)],
)
def test_subset_date_metadata_cannot_inherit_the_other_partition_date(bundle, field, value):
    """Even a newly pinned complete bundle must state each dated subset's actual maximum."""
    directory, _ = bundle
    supported, withheld, metadata = _dated_rows()
    metadata["supported"][field] = value
    pin = _replace_reviewed_rows(directory, supported, withheld, metadata=metadata)
    with pytest.raises(ValueError, match="subset mapping_date/version"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


@pytest.mark.parametrize("value", ["2026-02-30", "2026-1-01", "２０２６-11-01"])
def test_invalid_row_dates_cannot_define_subset_metadata(bundle, value):
    """Malformed calendar or non-ASCII row dates remain invalid after fixture re-signing."""
    directory, _ = bundle
    supported, withheld, metadata = _dated_rows()
    supported[0]["mapping_date"] = value
    metadata["supported"].update(mapping_date=value, mapping_set_version=value)
    pin = _replace_reviewed_rows(directory, supported, withheld, metadata=metadata)
    with pytest.raises(Exception, match="(?i)date|validation|format"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


def _form_rows():
    """Separate a synthetic supplied-form registry identity from its broader parent assertion."""
    parent = dict(zip(FIELDS, SUPPORTED, strict=True))
    parent.update(subject_id="MIM:Monohydrate", subject_label="monohydrate", predicate_id="skos:broadMatch", other="")
    handle = dict(
        parent, predicate_id="skos:exactMatch", object_id="kgmicrobe.compound:monohydrate", object_label="monohydrate"
    )
    return parent, handle


def test_supported_broad_relation_retains_all_original_fields_and_predicate(bundle):
    """Structural admission returns the reviewed directional row without identity strengthening."""
    directory, _ = bundle
    parent, handle = _form_rows()
    withheld = dict(zip(FIELDS, WITHHELD, strict=True))
    pin = _replace_reviewed_rows(directory, [parent, handle], [withheld])
    result = release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)
    assert result.supported_rows == (parent, handle)
    assert [row["predicate_id"] for row in result.supported_rows] == ["skos:broadMatch", "skos:exactMatch"]
    assert result.supported_rows[0]["other"] == ""


@pytest.mark.parametrize("defect", ["missing", "wrong_subject", "wrong_slug", "withheld"])
def test_broad_relation_needs_a_supported_exact_same_subject_registry_handle(bundle, defect):
    """A parent relation cannot stand in for the publisher's separate supplied-form identity."""
    directory, _ = bundle
    parent, handle = _form_rows()
    supported = [parent, handle]
    withheld = [dict(zip(FIELDS, WITHHELD, strict=True))]
    if defect == "missing":
        supported.remove(handle)
    elif defect == "wrong_subject":
        handle["subject_id"] = "MIM:Other"
    elif defect == "wrong_slug":
        handle["object_id"] = "kgmicrobe.compound:other"
    else:
        supported.remove(handle)
        withheld.append(handle)
    pin = _replace_reviewed_rows(directory, supported, withheld)
    with pytest.raises(ValueError, match="same-subject exact registry handle"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


@pytest.mark.parametrize("predicate", ["skos:closeMatch", "skos:narrowMatch", "skos:relatedMatch"])
def test_new_supported_predicates_still_require_an_explicit_consumer_contract(bundle, predicate):
    """A re-signed disposition does not silently authorize additional relation semantics."""
    directory, _ = bundle
    parent, handle = _form_rows()
    parent["predicate_id"] = predicate
    pin = _replace_reviewed_rows(directory, [parent, handle], [dict(zip(FIELDS, WITHHELD, strict=True))])
    with pytest.raises(ValueError, match="skos:exactMatch or skos:broadMatch"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)


def test_actual_six_form_claims_keep_native_payloads_in_a_synthetic_partition(bundle):
    """Exercise the exact archived form rows without pretending the fixture is a full native export."""
    path = Path(__file__).parent / "resources/mim_reviewed_broader_20261107/source-claims.json"
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == "a08a231ea586e84b549736c76b3e8c5d6c8c4d9a8977da69cdfa481b8ef378c0"
    claims = json.loads(content)["claims"]
    rows = [claim["row"] for claim in claims]
    assert all(_hash_row(claim["row"]) == claim["decision"]["row_sha256"] for claim in claims)
    withheld = dict.fromkeys(rows[0], "")
    withheld.update(dict(zip(FIELDS, WITHHELD, strict=True)), mapping_date="2026-11-03")
    _, _, metadata = _dated_rows()
    directory, _ = bundle
    pin = _replace_reviewed_rows(directory, rows, [withheld], metadata=metadata)
    result = release.validate_reviewed_bundle(directory, expected_manifest_sha256=pin)
    assert result.supported_rows == tuple(rows)
    assert sum(row["predicate_id"] == "skos:broadMatch" for row in result.supported_rows) == 2
    assert sum(row["predicate_id"] == "skos:exactMatch" for row in result.supported_rows) == 4


@pytest.mark.parametrize("negated_claim", ["broader", "registry", "cas"])
def test_negated_supported_claims_fail_even_in_a_complete_hash_bound_partition(bundle, negated_claim):
    """A reviewed negative mapping cannot authorize positive form or identity reconstruction."""
    path = Path(__file__).parent / "resources/mim_reviewed_broader_20261107/source-claims.json"
    original = path.read_bytes()
    claims = json.loads(original)["claims"]
    rows = [dict(claim["row"], predicate_modifier="") for claim in claims]
    withheld = dict.fromkeys(rows[0], "")
    withheld.update(dict(zip(FIELDS, WITHHELD, strict=True)), mapping_date="2026-11-03")
    _, _, metadata = _dated_rows()
    directory, _ = bundle
    positive_pin = _replace_reviewed_rows(directory, rows, [withheld], metadata=metadata)
    positive = release.validate_reviewed_bundle(directory, expected_manifest_sha256=positive_pin)
    assert positive.supported_rows == tuple(rows)
    if negated_claim == "broader":
        target = next(row for row in rows if row["predicate_id"] == "skos:broadMatch")
    else:
        prefix = "kgmicrobe.compound:" if negated_claim == "registry" else "cas:"
        target = next(row for row in rows if row["object_id"].startswith(prefix))
    target["predicate_modifier"] = "Not"
    negative_pin = _replace_reviewed_rows(directory, rows, [withheld], metadata=metadata)
    with pytest.raises(ValueError, match="Supported MIM predicate modifiers cannot become positive assertions"):
        release.validate_reviewed_bundle(directory, expected_manifest_sha256=negative_pin)
    assert path.read_bytes() == original
