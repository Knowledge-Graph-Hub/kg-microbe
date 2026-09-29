"""Test conservative migration without repository data or live ontology services."""

import csv
import gzip
import io
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from kg_microbe.utils import chemical_mapping_utils as runtime
from scripts import mim_conservative_refresh as refresh
from tests import test_mim_reviewed_release as release_fixtures
from tests.test_mim_reviewed_release import bundle as release_fixture

bundle = release_fixture

FIELDS = (
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "object_source",
    "mapping_justification",
    "source",
    "mapping_date",
    "confidence",
    "comment",
    "object_formula",
    "object_category",
)
NODE_FIELDS = ("id", "category", "name", "synonym", "xref", "deprecated", "same_as")


def test_lexical_identifiers_preserve_prime_locants():
    """Different ring positions must not publish the same lexical subject."""
    assert refresh._slug("4-hydroxychalcone") == "4-hydroxychalcone"
    assert refresh._slug("4'-hydroxychalcone") == "4_prime-hydroxychalcone"
    assert refresh._slug("4′-hydroxychalcone") == "4_prime-hydroxychalcone"
    assert refresh._slug("4″-hydroxychalcone") == "4_prime_prime-hydroxychalcone"


def _row(subject, target, label, source="independent_prior", predicate="skos:exactMatch", name="", comment=""):
    """Describe one immutable historical assertion using the unified schema."""
    result = dict.fromkeys(FIELDS, "")
    result.update(
        subject_id=subject,
        subject_label=name,
        predicate_id=predicate,
        object_id=target,
        object_label=label,
        object_source="obo:chebi.owl",
        source=source,
        mapping_justification="semapv:ManualMappingCuration",
        mapping_date="2026-01-01",
        comment=comment,
        object_category="biolink:ChemicalEntity",
    )
    return result


def _table(path, fields, rows, metadata=None):
    """Write only small test-owned files inside tmp_path."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        if metadata:
            for line in yaml.safe_dump(metadata).splitlines():
                handle.write("# " + line + "\n")
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _metadata():
    """Supply valid local SSSOM metadata for the historical fixture."""
    return {
        "mapping_set_id": "https://example.org/historical",
        "mapping_set_version": "2026-01-01",
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "predicate_semantics": "skos",
        "curie_map": {
            "MIM": "https://example.org/mim/",
            "CHEBI": "http://purl.obolibrary.org/obo/CHEBI_",
            "FOODON": "http://purl.obolibrary.org/obo/FOODON_",
            "cas": "https://example.org/cas/",
            "kgm.name": "https://w3id.org/kg-microbe/name/",
            "obo": "http://purl.obolibrary.org/obo/",
            "skos": "http://www.w3.org/2004/02/skos/core#",
            "semapv": "https://w3id.org/semapv/vocab/",
        },
        "extension_definitions": [
            {"slot_name": name, "property": "https://example.org/" + name, "type_hint": "xsd:string"}
            for name in ("source", "object_formula", "object_category")
        ],
    }


def _node(curie, name, synonyms="", xrefs=""):
    """Create one native current ontology record."""
    return dict(
        id=curie, name=name, synonym=synonyms, xref=xrefs, category="biolink:ChemicalEntity", deprecated="", same_as=""
    )


@pytest.fixture
def inputs(tmp_path, request):
    """Provide old mixed-source claims, connected contamination, and current evidence."""
    # CAS values are checksum-valid graph fixtures, not substance assignments.
    release_directory, pin = request.getfixturevalue("bundle")
    baseline = tmp_path / "baseline.tsv"
    rows = [
        _row("MIM:Old", "CHEBI:1", "Unsupported old name", "mediaingredientmech_reviewed|chebi_xrefs"),
        _row(
            "kgm.name:unsupported",
            "CHEBI:1",
            "Unsupported old name",
            "mediaingredientmech_reviewed|chebi_xrefs",
            name="Unsupported old name",
            comment="canonical_name",
        ),
        _row("cas:50-00-0", "CHEBI:1", "Unsupported old name", "culturebotai_reviewed"),
        _row("cas:50-00-0", "CHEBI:2", "Two"),
        _row(
            "kgm.name:poison",
            "CHEBI:2",
            "Two",
            predicate="skos:closeMatch",
            name="Copied MIM poison",
            comment="synonym",
        ),
        _row("CHEBI:2", "CHEBI:3", "Three"),
        _row("kgm.name:untouched", "CHEBI:4", "Untouched", name="Untouched", comment="canonical_name"),
        _row("CHEBI:1", "CHEBI:5", "Hydrate", predicate="skos:closeMatch", comment="recipe_equivalent_hydrate"),
        _row("CHEBI:4", "CHEBI:1", "Unsupported old name", predicate="skos:broadMatch"),
        _row("CHEBI:1", "CHEBI:6", "Six", "mediaingredientmech_reviewed", predicate="skos:broadMatch"),
        _row("MIM:Water", "CHEBI:15377", "Old water label", "mediaingredientmech_reviewed"),
        _row(
            "kgm.name:oldwater",
            "CHEBI:15377",
            "Old water label",
            "mediaingredientmech_reviewed",
            name="Old water label",
            comment="canonical_name",
        ),
    ]
    _table(baseline, FIELDS, rows, _metadata())
    native = tmp_path / "chebi_nodes.tsv"
    _table(
        native,
        NODE_FIELDS,
        [
            _node("CHEBI:1", "One", "Legitimate independent alias", "cas:64-17-5"),
            _node("CHEBI:2", "Two"),
            _node("CHEBI:3", "Three"),
            _node("CHEBI:4", "Untouched"),
            _node("CHEBI:5", "Hydrate"),
            _node("CHEBI:6", "Six"),
            _node("CHEBI:15377", "water", "aqua"),
        ],
    )
    imported = tmp_path / "foodon_nodes.tsv"
    _table(imported, NODE_FIELDS, [_node("CHEBI:1", "Foreign imported wrong label"), _node("FOODON:1", "food")])
    independent = tmp_path / "independent.tsv"
    _table(
        independent,
        ["object_id", "object_label", "subject_label", "subject_label_normalized"],
        [
            {
                "object_id": "CHEBI:1",
                "object_label": "One",
                "subject_label": "Sample",
                "subject_label_normalized": "sample",
            },
        ],
    )
    return dict(
        baseline=baseline,
        release_directory=release_directory,
        expected_manifest_sha256=pin,
        ontology_paths=(native, imported),
        independent_sources=(refresh.IndependentSource("metatraits_chemical_mappings", independent),),
        output_directory=tmp_path / "candidate",
    )


def _read(path):
    """Read the tiny output fixture without changing runtime global caches."""
    with gzip.open(path, "rt") as handle:
        return list(csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t"))


def test_potato_historical_mapping_is_losslessly_quarantined_and_not_reasserted(inputs, monkeypatch):
    """The supported-only candidate retains old full rows, not a generic-to-extract identity."""
    fixture = json.loads((Path(__file__).parent / "resources/mediadive/potato_scope.json").read_text())
    held = fixture["mapping_claims"]["unified"]["row"]
    target, label = fixture["authority"]["cas"], fixture["authority"]["label"]
    positive = _row("kgm.name:explicit_extract", target, label, name=label, comment="canonical_name")
    _table(inputs["baseline"], FIELDS, [*refresh._rows(inputs["baseline"]), held, dict(held), positive], _metadata())
    original = inputs["baseline"].read_bytes()
    first = refresh.build_conservative_candidate(**inputs)
    quarantined = [row for row in _read(first.quarantine_path) if row["subject_id"] == held["subject_id"]]
    assert len(quarantined) == 2
    assert all(row.pop("quarantine_reason") == "reviewed_identity_policy_name" for row in quarantined)
    assert quarantined == [held, held]
    assert positive in _read(first.candidate_path)
    assert not any(row["subject_id"] == held["subject_id"] for row in _read(first.candidate_path))
    assert inputs["baseline"].read_bytes() == original
    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=first.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(second.candidate_path)
    assert runtime.find_chebi_by_name("Potato") is None
    assert runtime.find_chebi_by_name(label) == target


def test_conservative_refresh_rebuilds_connected_claims_and_preserves_independent_relations(inputs):
    """Reset mixed/propagated claims while retaining separately supported identity."""
    result = refresh.build_conservative_candidate(**inputs)
    rows = _read(result.candidate_path)
    assert {"CHEBI:1", "CHEBI:2", "CHEBI:3"} <= set(result.report["affected_entities"])
    assert "CHEBI:4" not in result.report["affected_entities"]
    assert "CHEBI:5" not in result.report["affected_entities"]
    assert not any(row["subject_id"] == "MIM:Old" for row in rows)
    assert not any("Copied MIM poison" in row.values() for row in rows)
    assert not any("Unsupported old name" in row.values() for row in rows)
    assert not any("Foreign imported wrong label" in row.values() for row in rows)
    assert any(row["subject_label"] == "Sample" and row["object_id"] == "CHEBI:1" for row in rows)
    assert not any(row["subject_id"] == "cas:64-17-5" for row in rows)
    assert any(
        row["subject_id"] == "CHEBI:4" and row["predicate_id"] == "skos:broadMatch" and row["object_label"] == "One"
        for row in rows
    )
    assert any(row["comment"] == "recipe_equivalent_hydrate" and row["object_id"] == "CHEBI:5" for row in rows)
    assert not any(row["object_id"] == "CHEBI:6" and row["predicate_id"] == "skos:broadMatch" for row in rows)
    assert {row["object_label"] for row in rows if row["object_id"] == "CHEBI:15377"} == {"Water"}
    assert result.report["supported_name_lookup_conflicts"] == []
    assert result.report["supported_xref_lookup_conflicts"] == []
    assert result.report["counts"]["removed_mim_nonidentity_rows"] == 1
    assert len(_read(result.quarantine_path)) == result.report["counts"]["quarantined_rows"]


def test_second_cycle_is_byte_identical_and_runtime_lookups_are_clean(inputs, monkeypatch):
    """An exported candidate must not restore stale labels during reseeding."""
    first = refresh.build_conservative_candidate(**inputs)
    second = refresh.build_conservative_candidate(
        **dict(
            inputs,
            baseline=first.candidate_path,
            output_directory=inputs["output_directory"].with_name("second"),
        )
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(second.candidate_path)
    assert runtime.find_chebi_by_name("Water") == "CHEBI:15377"
    assert runtime.find_chebi_by_name("Old water label") is None
    assert runtime.find_chebi_by_name("Unsupported old name") is None
    assert runtime.find_chebi_by_name("Copied MIM poison") is None
    assert runtime.find_chebi_by_name("Legitimate independent alias") == "CHEBI:1"
    assert runtime.find_chebi_by_name("Sample") == "CHEBI:1"
    assert runtime.find_chebi_by_xref("MIM:Old") is None
    assert runtime.find_chebi_by_xref("MIM:Water") == "CHEBI:15377"
    assert runtime.get_parents("CHEBI:4") == ["CHEBI:1"]
    assert runtime.get_hydrate_equivalents("CHEBI:1") == ["CHEBI:5"]


@pytest.fixture
def untouched_claims(inputs):
    """Give the untainted target a legacy alias, duplicate, and explicit identity."""
    baseline = inputs["baseline"]
    rows = list(refresh._rows(baseline))
    alias = _row(
        "kgm.name:legacy_four_alias",
        "CHEBI:4",
        "Untouched",
        source="independent_prior|fixture_curator",
        predicate="skos:closeMatch",
        name="Legacy four alias",
        comment="synonym",
    )
    alias.update(confidence="0.73", object_formula="FixtureFormula")
    rows.extend([alias, dict(alias), _row("cas:67-56-1", "CHEBI:4", "Untouched")])
    _table(baseline, FIELDS, rows, _metadata())
    return [row for row in rows if row["object_id"] == "CHEBI:4"]


def _assert_untouched_lookup_and_rows(candidate, expected, monkeypatch):
    """Verify complete preserved claims and query them through the real runtime."""
    actual = [row for row in _read(candidate) if row["object_id"] == "CHEBI:4"]
    assert Counter(tuple(sorted(row.items())) for row in actual) == Counter(
        tuple(sorted(row.items())) for row in expected
    )
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(candidate)
    assert runtime.find_chebi_by_name("Legacy four alias") == "CHEBI:4"
    assert runtime.find_chebi_by_xref("cas:67-56-1") == "CHEBI:4"


@pytest.mark.parametrize("bridge", ["direct", "shared_cas"])
@pytest.mark.parametrize("native_relation", ["xref", "same_as"])
@pytest.mark.parametrize("owner", ["CHEBI:1", "CHEBI:15377"])
def test_native_annotation_bridge_does_not_reset_unrelated_claims(
    inputs, untouched_claims, monkeypatch, bridge, native_relation, owner
):
    """Only explicit native identity may extend a recorded historical taint path."""
    baseline = inputs["baseline"]
    target = "CHEBI:4" if bridge == "direct" else "cas:67-64-1"
    if bridge == "shared_cas":
        historical_bridge = _row(target, "CHEBI:4", "Untouched")
        _table(baseline, FIELDS, [*refresh._rows(baseline), historical_bridge], _metadata())
        untouched_claims.append(historical_bridge)
    path = inputs["ontology_paths"][0]
    native = list(refresh._rows(path))
    next(row for row in native if row["id"] == owner)[native_relation] = target
    _table(path, NODE_FIELDS, native)

    first = refresh.build_conservative_candidate(**inputs)
    rows = _read(first.candidate_path)
    assert {"CHEBI:1", "CHEBI:2", "CHEBI:3"} <= set(first.report["affected_entities"])
    assert not any("Copied MIM poison" in row.values() for row in rows)
    assert ("CHEBI:4" in first.report["affected_entities"]) == (native_relation == "same_as")
    native_identity = [
        row
        for row in rows
        if row["subject_id"] == target and row["object_id"] == owner and row["predicate_id"] == "skos:exactMatch"
    ]
    if native_relation == "same_as":
        assert len(native_identity) == 1
        assert native_identity[0]["source"] == "native_ontology:chebi"
    else:
        assert native_identity == []
        _assert_untouched_lookup_and_rows(first.candidate_path, untouched_claims, monkeypatch)
        if bridge == "shared_cas":
            assert runtime.find_chebi_by_xref(target) == "CHEBI:4"

    second = refresh.build_conservative_candidate(
        **dict(
            inputs,
            baseline=first.candidate_path,
            output_directory=inputs["output_directory"].with_name("second"),
        )
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    if owner == "CHEBI:15377":
        assert owner in first.report["initial_affected_entities"]
        assert owner in second.report["initial_affected_entities"]
    if native_relation == "xref":
        _assert_untouched_lookup_and_rows(second.candidate_path, untouched_claims, monkeypatch)


@pytest.mark.parametrize(
    "relations", [("xref", "xref"), ("xref", "same_as"), ("same_as", "xref"), ("same_as", "same_as")]
)
@pytest.mark.parametrize("reverse_native_order", [False, True])
@pytest.mark.parametrize("owner", ["CHEBI:1", "CHEBI:15377"])
def test_native_only_intermediate_cannot_bridge_across_an_annotation(
    inputs, untouched_claims, monkeypatch, relations, reverse_native_order, owner
):
    """Follow full explicit-identity chains, never a chain with an annotation hop."""
    intermediate = "CHEBI:900001"
    assert not any(intermediate in (row["subject_id"], row["object_id"]) for row in refresh._rows(inputs["baseline"]))
    path = inputs["ontology_paths"][0]
    native = list(refresh._rows(path))
    next(row for row in native if row["id"] == owner)[relations[0]] = intermediate
    middle = _node(intermediate, "Native-only intermediate")
    middle[relations[1]] = "CHEBI:4"
    native.append(middle)
    _table(path, NODE_FIELDS, list(reversed(native)) if reverse_native_order else native)

    first = refresh.build_conservative_candidate(**inputs)
    rows = _read(first.candidate_path)
    fully_explicit = relations == ("same_as", "same_as")
    assert ("CHEBI:4" in first.report["affected_entities"]) == fully_explicit
    assert {"CHEBI:1", "CHEBI:2", "CHEBI:3"} <= set(first.report["affected_entities"])
    assert not any("Copied MIM poison" in row.values() for row in rows)
    assert intermediate not in first.report["affected_entities"]
    assert not any(row["object_id"] == intermediate for row in rows)
    identities = [
        row
        for row in rows
        if row["subject_id"] == intermediate and row["object_id"] == owner and row["predicate_id"] == "skos:exactMatch"
    ]
    assert bool(identities) == (relations[0] == "same_as")
    if identities:
        assert len(identities) == 1
        assert identities[0]["source"] == "native_ontology:chebi"
    if not fully_explicit:
        _assert_untouched_lookup_and_rows(first.candidate_path, untouched_claims, monkeypatch)

    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=first.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    if owner == "CHEBI:15377":
        assert owner in first.report["initial_affected_entities"]
        assert owner in second.report["initial_affected_entities"]
    if not fully_explicit:
        _assert_untouched_lookup_and_rows(second.candidate_path, untouched_claims, monkeypatch)


@pytest.mark.parametrize("same_as", ["CHEBI:4", " CHEBI:4", "CHEBI:4 ", " CHEBI:4 "])
def test_native_same_as_whitespace_closes_scope_in_first_cycle(inputs, untouched_claims, same_as):
    """Normalize explicit identity before scope closure, using a persistent MIM seed."""
    owner = "CHEBI:15377"
    path = inputs["ontology_paths"][0]
    native = list(refresh._rows(path))
    next(row for row in native if row["id"] == owner)["same_as"] = same_as
    _table(path, NODE_FIELDS, native)

    first = refresh.build_conservative_candidate(**inputs)
    rows = _read(first.candidate_path)
    assert owner in first.report["initial_affected_entities"]
    assert "CHEBI:4" in first.report["affected_entities"]
    identities = [
        row
        for row in rows
        if row["subject_id"].strip() == "CHEBI:4"
        and row["object_id"] == owner
        and row["predicate_id"] == "skos:exactMatch"
    ]
    assert len(identities) == 1
    assert identities[0]["subject_id"] == "CHEBI:4"
    assert identities[0]["source"] == "native_ontology:chebi"
    quarantined = [row for row in _read(first.quarantine_path) if row["object_id"] == "CHEBI:4"]
    assert Counter(
        tuple(sorted((key, value) for key, value in row.items() if key != "quarantine_reason")) for row in quarantined
    ) == Counter(tuple(sorted(row.items())) for row in untouched_claims)
    assert {row["quarantine_reason"] for row in quarantined} == {"historical_entity_provenance_or_identity_component"}
    assert not any(row["subject_id"] == "kgm.name:legacy_four_alias" for row in rows)

    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=first.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert owner in second.report["initial_affected_entities"]
    assert "CHEBI:4" in second.report["affected_entities"]
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()


@pytest.mark.parametrize("same_as", ["CHEBI: 4", "   ", "UnknownPrefix:4", " CHEBI:15377 "])
def test_native_same_as_invalid_tokens_do_not_expand_scope(inputs, untouched_claims, monkeypatch, same_as):
    """Trimming must not admit malformed, unknown-prefix, blank, or self identities."""
    owner = "CHEBI:15377"
    path = inputs["ontology_paths"][0]
    native = list(refresh._rows(path))
    next(row for row in native if row["id"] == owner)["same_as"] = same_as
    _table(path, NODE_FIELDS, native)

    first = refresh.build_conservative_candidate(**inputs)
    for row in _read(first.candidate_path):
        assert not (
            row["subject_id"] in {same_as, same_as.strip()}
            and row["object_id"] == owner
            and row["predicate_id"] == "skos:exactMatch"
        )
    assert owner in first.report["initial_affected_entities"]
    assert "CHEBI:4" not in first.report["affected_entities"]
    _assert_untouched_lookup_and_rows(first.candidate_path, untouched_claims, monkeypatch)

    second = refresh.build_conservative_candidate(
        **dict(inputs, baseline=first.candidate_path, output_directory=inputs["output_directory"].with_name("second"))
    )
    assert owner in second.report["initial_affected_entities"]
    assert "CHEBI:4" not in second.report["affected_entities"]
    assert first.candidate_path.read_bytes() == second.candidate_path.read_bytes()
    _assert_untouched_lookup_and_rows(second.candidate_path, untouched_claims, monkeypatch)


def test_explicit_same_as_is_restored_but_native_dbxref_is_not(inputs):
    """Generic database references do not establish new chemical equivalence."""
    path = inputs["ontology_paths"][0]
    rows = list(csv.DictReader(io.StringIO(path.read_text()), delimiter="\t"))
    rows[0]["same_as"] = "CHEBI:3"
    rows[0]["xref"] = "cas:64-17-5|pubmed:123"
    _table(path, NODE_FIELDS, rows)
    result = refresh.build_conservative_candidate(**inputs)
    output = _read(result.candidate_path)
    assert any(row["subject_id"] == "CHEBI:3" and row["object_id"] == "CHEBI:1" for row in output)
    assert not any(row["subject_id"] in {"cas:64-17-5", "pubmed:123"} for row in output)


def test_existing_prefix_expansions_are_preserved_and_differences_reported(inputs):
    """Do not reinterpret unrelated historical CURIEs when upstream uses another URI."""
    path = inputs["baseline"]
    baseline_uri = "https://example.org/legacy-chebi/"
    path.write_text(path.read_text().replace("http://purl.obolibrary.org/obo/CHEBI_", baseline_uri))
    result = refresh.build_conservative_candidate(**inputs)
    metadata, _ = refresh._header(result.candidate_path)
    assert metadata["curie_map"]["CHEBI"] == baseline_uri
    assert result.report["upstream_prefix_differences"]["CHEBI"] == {
        "baseline_uri": baseline_uri,
        "upstream_uri": "http://purl.obolibrary.org/obo/CHEBI_",
    }
    untouched = next(row for row in _read(result.candidate_path) if row["subject_id"] == "kgm.name:untouched")
    assert untouched["object_id"] == "CHEBI:4"
    assert untouched["mapping_date"] == "2026-01-01"


def test_multiple_supported_targets_survive_and_runtime_resolves_an_approved_target(inputs, monkeypatch):
    """Keep a publisher's valid CAS/ontology alternatives for the same MIM subject."""
    directory = inputs["release_directory"]
    supported_path = directory / release_fixtures.release.SUPPORTED_FILE
    supported = dict(zip(release_fixtures.FIELDS, release_fixtures.SUPPORTED, strict=True))
    second = dict(supported, object_id="cas:7732-18-5")
    metadata = release_fixtures._metadata("supported")
    metadata["curie_map"]["cas"] = "https://example.org/cas/"
    supported_path.write_text(release_fixtures._sssom(metadata, [supported, second]))
    dispositions_path = directory / release_fixtures.release.DISPOSITIONS_FILE
    dispositions = list(csv.DictReader(io.StringIO(dispositions_path.read_text()), delimiter="\t"))
    dispositions.append(release_fixtures._decision(second, 3, "SUPPORTED"))
    dispositions_path.write_text(release_fixtures._tsv(release_fixtures.release.DISPOSITION_FIELDS, dispositions))
    inputs["expected_manifest_sha256"] = release_fixtures._repin(
        directory, lambda manifest: manifest["counts"].update(supported=2, source=3)
    )
    result = refresh.build_conservative_candidate(**inputs)
    approved = {"CHEBI:15377", "cas:7732-18-5"}
    assert {row["object_id"] for row in _read(result.candidate_path) if row["subject_id"] == "MIM:Water"} == approved
    assert result.report["supported_xref_lookup_conflicts"] == []
    assert set(result.report["supported_multitarget_subjects"]["MIM:Water"]) == approved
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(result.candidate_path)
    assert runtime.find_chebi_by_xref("MIM:Water") in approved


@pytest.mark.parametrize("which", ["ontology", "independent", "release"])
def test_missing_required_input_never_creates_output(inputs, which):
    """Fail before producing an apparently complete bundle on missing evidence."""
    path = {
        "ontology": inputs["ontology_paths"][0],
        "independent": inputs["independent_sources"][0].path,
        "release": inputs["release_directory"] / "mapping-dispositions.tsv",
    }[which]
    path.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        refresh.build_conservative_candidate(**inputs)
    assert not inputs["output_directory"].exists()


def test_validation_failure_and_changing_input_never_publish_partial_bundle(inputs, monkeypatch):
    """Keep partial candidate/quarantine outputs private until every check passes."""

    def fail(*_):
        """Simulate candidate schema validation failure."""
        raise ValueError("fixture validation failure")

    monkeypatch.setattr(refresh, "_validate_output", fail)
    with pytest.raises(ValueError, match="fixture validation"):
        refresh.build_conservative_candidate(**inputs)
    assert not inputs["output_directory"].exists()

    def change_input(*_):
        """Simulate evidence changing before atomic publication."""
        inputs["ontology_paths"][0].write_text(inputs["ontology_paths"][0].read_text() + "\n")

    monkeypatch.setattr(refresh, "_validate_output", change_input)
    with pytest.raises(ValueError, match="Input changed"):
        refresh.build_conservative_candidate(**inputs)
    assert not inputs["output_directory"].exists()


def test_existing_output_is_not_overwritten(inputs):
    """The candidate builder never overwrites a previous audited bundle."""
    result = refresh.build_conservative_candidate(**inputs)
    original = result.candidate_path.read_bytes()
    with pytest.raises(ValueError, match="must not already exist"):
        refresh.build_conservative_candidate(**inputs)
    assert result.candidate_path.read_bytes() == original


def test_current_special_chemical_layout_requires_separate_evidence_review(inputs):
    """Do not reinterpret the upstream-dependent special table as independent."""
    sources = inputs["independent_sources"]
    inputs["independent_sources"] = (refresh.IndependentSource("metatraits_special_chemicals", sources[0].path),)
    with pytest.raises(ValueError, match="Unknown independent source kind"):
        refresh.build_conservative_candidate(**inputs)
    assert not inputs["output_directory"].exists()


@pytest.mark.parametrize("kind", ["manual_annotations", "metatraits_chemical_mappings"])
@pytest.mark.parametrize(
    "defect", ["wrong_columns", "duplicate_column", "missing_cell", "extra_cell", "empty", "preamble"]
)
def test_independent_tsv_schema_fails_closed_before_output(inputs, kind, defect):
    """Legacy parsers cannot silently treat malformed required sources as zero evidence."""
    path = inputs["baseline"].with_name("independent-schema.tsv")
    fields = (
        ["object_id", "object_label", "traits_dataset_term", "action"]
        if kind == "manual_annotations"
        else ["object_id", "object_label", "subject_label", "subject_label_normalized"]
    )
    row = dict(
        zip(fields, ["CHEBI:1", "One", "Sample", "REPLACE" if kind == "manual_annotations" else "sample"], strict=True)
    )
    _table(path, fields, [row])
    content = path.read_text()
    if defect == "wrong_columns":
        content = "wrong_id\twrong_name\nCHEBI:1\tSample\n"
    elif defect == "duplicate_column":
        content = content.replace("object_label", "object_id", 1)
    elif defect == "missing_cell":
        content = content.rsplit("\t", 1)[0] + "\n"
    elif defect == "extra_cell":
        content = content.rstrip("\n") + "\textra\n"
    elif defect == "empty":
        content = content.splitlines()[0] + "\n"
    else:
        content = "# metadata that the legacy parser would mistake for a header\n" + content
    path.write_text(content)
    inputs["independent_sources"] = (refresh.IndependentSource(kind, path),)
    with pytest.raises(ValueError, match="independent TSV"):
        refresh.build_conservative_candidate(**inputs)
    assert not inputs["output_directory"].exists()


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        "{}",
        '{"CHEBI:1": []}',
        '{"CHEBI:1": 42}',
        '{"CHEBI:1": ""}',
        '{"FOODON:1": "One"}',
        '{"CHEBI:1": "One", "CHEBI:1": "Other"}',
    ],
)
def test_metabolite_json_requires_its_actual_mapping_shape(inputs, content):
    """Reject non-object, duplicate, empty, or non-CHEBI metabolite evidence."""
    path = inputs["baseline"].with_name("metabolites.json")
    path.write_text(content)
    inputs["independent_sources"] = (refresh.IndependentSource("metabolite_json", path),)
    with pytest.raises(ValueError, match="(?i)metabolite JSON"):
        refresh.build_conservative_candidate(**inputs)
    assert not inputs["output_directory"].exists()


@pytest.mark.parametrize("kind", ["metabolite_json", "manual_annotations"])
def test_valid_audited_legacy_sources_still_restore_direct_claims(inputs, kind):
    """Strict preflight preserves valid BacDive and Madin evidence ingestion."""
    path = inputs["baseline"].with_name("legacy-source.json" if kind == "metabolite_json" else "legacy-source.tsv")
    if kind == "metabolite_json":
        path.write_text('{"CHEBI:1": "Direct historical name"}')
    else:
        _table(
            path,
            ["object_id", "object_label", "traits_dataset_term", "action"],
            [
                {
                    "object_id": "CHEBI:1",
                    "object_label": "One",
                    "traits_dataset_term": "Direct historical name",
                    "action": "REPLACE",
                }
            ],
        )
    inputs["independent_sources"] = (refresh.IndependentSource(kind, path),)
    result = refresh.build_conservative_candidate(**inputs)
    assert any(row["subject_label"] == "Direct historical name" for row in _read(result.candidate_path))


@pytest.mark.parametrize("authority_state", ["native", "empty_category", "missing_evidence"])
def test_preserved_nonidentity_category_uses_same_fresh_fallback_as_rebuilt_rows(inputs, monkeypatch, authority_state):
    """The first retained parent row cannot reintroduce a stale runtime category."""
    baseline = inputs["baseline"]
    metadata, fields = refresh._header(baseline)
    historical = list(refresh._rows(baseline))
    for row in historical:
        if row["subject_id"] == "CHEBI:4" and row["object_id"] == "CHEBI:1":
            row["object_category"] = "biolink:NamedThing"
    _table(baseline, fields, historical, metadata)
    native = inputs["ontology_paths"][0]
    nodes = list(refresh._rows(native))
    if authority_state == "empty_category":
        for row in nodes:
            if row["id"] == "CHEBI:1":
                row["category"] = ""
    elif authority_state == "missing_evidence":
        nodes = [row for row in nodes if row["id"] != "CHEBI:1"]
        source = inputs["independent_sources"][0].path
        source.write_text(source.read_text().replace("CHEBI:1", "CHEBI:4"))
    _table(native, NODE_FIELDS, nodes)
    result = refresh.build_conservative_candidate(**inputs)
    rows = _read(result.candidate_path)
    affected_rows = [row for row in rows if row["object_id"] == "CHEBI:1"]
    assert affected_rows[0]["subject_id"] == "CHEBI:4"
    assert {row["object_category"] for row in affected_rows} == {"biolink:ChemicalEntity"}
    monkeypatch.setattr(runtime, "_LOADED", False)
    monkeypatch.setattr(runtime, "_CACHED_PATH", None)
    runtime.load_unified_mappings(result.candidate_path)
    assert runtime.get_category("CHEBI:1") == "biolink:ChemicalEntity"


def test_environment_change_during_build_prevents_publication(inputs, monkeypatch):
    """A changed execution context cannot receive a successful candidate report (#974)."""
    generation = [0]
    original_validate = refresh._validate_output
    monkeypatch.setattr(refresh, "reproducibility_context", lambda _root: {"generation": generation[0]})

    def change_environment(*args):
        """Simulate a changed dependency inventory after output validation."""
        original_validate(*args)
        generation[0] += 1

    monkeypatch.setattr(refresh, "_validate_output", change_environment)
    with pytest.raises(ValueError, match="Code or environment changed"):
        refresh.build_conservative_candidate(**inputs)
    assert not inputs["output_directory"].exists()
