"""Native solution identity and finite source-material dispositions (#1317–1319)."""

import csv
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from kg_microbe.transform_utils.mediadive import mediadive as mod
from kg_microbe.transform_utils.mediadive import recipe_identity as identity
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows, verify_finalized_source_files

RESOURCE = Path(__file__).parent / "resources"
FIXTURE = RESOURCE / "mediadive_recipe_identity"


def _loader(target=None):
    """Inject successful wrong candidates; source identity must not depend on their absence."""
    return SimpleNamespace(
        find_chebi_by_name=lambda name: target,
        get_canonical_name=lambda identifier: "",
        get_node_enrichment=lambda identifier: {"xref": "", "synonym": ""},
        get_parents=lambda identifier: [],
        get_category=lambda identifier: "",
    )


def _resolver(raw, candidate):
    """Exercise the actual nested branch without claiming producer completion."""
    value = mod.MediaDiveTransform.__new__(mod.MediaDiveTransform)
    value.using_bulk_data = True
    value.solutions_data = {"1": {"recipe": raw}}
    value.compounds_data = {}
    value.compound_mappings = {"same name": "CHEBI:16411"}
    value.chebi_labels = {}
    value.chemical_loader = _loader(candidate)
    value.translation_table = str.maketrans(mod.TRANSLATION_TABLE_FOR_LABELS)
    value.api_calls_avoided = value.api_calls_made = 0
    return value


@pytest.mark.parametrize("candidate", [None, "NCIT:C29321", "MICRO:0000460", "CHEBI:16411"])
def test_explicit_children_precede_unified_and_legacy_lookup(candidate):
    """Same names and repeated children cannot collapse three native occurrences."""
    raw = [
        {"solution": "Same name", "solution_id": child, "amount": amount, "unit": "ml"}
        for child, amount in ((2, 1), (3, 1), (2, 10))
    ]
    transform = _resolver(raw, candidate)
    actual = transform.get_solution_recipe_occurrences("1")
    assert [row["id"] for row in actual] == ["mediadive.solution:2", "mediadive.solution:3", "mediadive.solution:2"]
    assert [row["amount"] for row in actual] == [1, 1, 10]
    assert [json.loads(row["source_record"]) for row in actual] == raw


@pytest.mark.parametrize("value", [None, True, 0, -1, 2.0, "02", "../2", "2|3"])
def test_malformed_child_ids_fail(value):
    """Reject ambiguous identifiers before a native CURIE can be minted."""
    with pytest.raises(SourceFinalizationRequired):
        identity.nested_identifier({"solution_id": value, "solution": "X"})


def test_genuine_compound_route_not_disabled_by_nested_rule():
    """The same lexical spelling remains eligible in the separate compound branch."""
    value = _resolver([{"compound": "Glucose", "compound_id": 16}], "CHEBI:17234")
    assert value.get_solution_recipe_occurrences("1")[0]["id"] == "CHEBI:17234"


def _build(tmp_path, monkeypatch, raw_mutator=None):
    """Real producer reads/writer using complete native excerpts and offline authority closure."""
    raw = tmp_path / "raw"
    shutil.copytree(FIXTURE / "raw", raw)
    origin = json.loads((FIXTURE / "fixture-origins.json").read_text())
    for relative, record in origin["fixtures"].items():
        assert hashlib.sha256((raw / relative).read_bytes()).hexdigest() == record["fixture_sha256"]
    if raw_mutator is not None:
        raw_mutator(raw)
    native = json.loads((RESOURCE / "ingredient_bundle/native/legacy-closure-statements.json").read_text())
    with sqlite3.connect(raw / "chebi.db") as connection:
        connection.execute("CREATE TABLE statements(stanza,subject,predicate,object,value,datatype,language,graph)")
        connection.executemany("INSERT INTO statements VALUES (?,?,?,?,?,?,?,?)", native["statements"])
        connection.execute("CREATE INDEX subject_idx ON statements(subject)")
    monkeypatch.setattr(mod, "BACDIVE_TMP_DIR", RESOURCE / "provenance_serialization")
    monkeypatch.setattr(mod, "MEDIADIVE_TMP_DIR", tmp_path)
    with (
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_roles"),
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_categories"),
        mock.patch.object(mod, "ChemicalMappingLoader", return_value=_loader()),
    ):
        value = mod.MediaDiveTransform(raw, tmp_path / "transformed")
    monkeypatch.setattr(value, "_get_mediadive_json", lambda *args: pytest.fail("network fallback"))
    value.run(show_status=False)
    return value


@pytest.fixture
def produced(tmp_path, monkeypatch):
    """Retain a full native proof rather than injecting fabricated consumed-input receipts."""
    return _build(tmp_path, monkeypatch)


def test_actual_writer_retains_all_six_and_missing_children(produced):
    """Assert output and separate source evidence, not only helper return values."""
    value = produced
    with value.output_edge_file.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    expected = value._recipe_identity_guard.index["occurrences"]
    actual = {row["source_assertion_id"]: row for row in rows if row.get("source_assertion_id")}
    assert set(actual) == set(expected)
    for key, entry in expected.items():
        assert actual[key]["source_record"] == identity.encoded(entry["raw"])
        if entry["target"]:
            assert actual[key]["object"] == entry["target"]
    with value.output_node_file.open() as stream:
        nodes = {row["id"]: row for row in csv.DictReader(stream, delimiter="\t")}
    for child in ("2269", "6420", "6572"):
        assert nodes[f"mediadive.solution:{child}"]["category"] == "biolink:NamedThing"
    assert len(value._recipe_identity_guard.rows["oatmeal"]) == 5
    assert len(value._recipe_identity_guard.rows["substrate"]) == 1
    assert len(value._recipe_identity_guard.rows["missing"]) == 3
    assert value.producer_native_inputs["version"] == 2


@pytest.mark.parametrize("cohort", ["oatmeal", "substrate"])
@pytest.mark.parametrize("candidate", ["NCIT:C29298", "NCIT:C120264", "CHEBI:17234"])
def test_all_primary_fallback_candidates_bypassed_for_reviewed_observations(produced, cohort, candidate):
    """Primary/legacy/embedded candidate injection cannot resurrect source substitutions."""
    value = produced
    value.chemical_loader = _loader(candidate)
    for assertion, item in value._recipe_identity_guard.index["occurrences"].items():
        if item["cohort"] != cohort:
            continue
        raw = item["raw"]
        value.compound_mappings[raw["compound"].lower()] = candidate
        assert (
            value.standardize_compound_id(
                str(raw["compound_id"]), raw["compound"], source_record=raw, source_assertion_id=assertion
            )
            == item["target"]
        )


@pytest.mark.parametrize("change", ["name", "quantity", "position"])
def test_finite_decision_rejects_new_or_contradictory_source_context(produced, change):
    """A reviewed native ID alone never grants a general alias disposition."""
    value = produced
    row = next(item for item in value._recipe_identity_guard.rows["oatmeal"])
    raw = json.loads(row["source_record"])
    assertion = row["source_assertion_id"]
    if change == "name":
        raw["compound"] = "Oatmeal Powder"
    elif change == "quantity":
        raw["amount"] += 1
    else:
        assertion += "0"
    with pytest.raises(SourceFinalizationRequired):
        value.standardize_compound_id("471", raw["compound"], source_record=raw, source_assertion_id=assertion)


@pytest.mark.usefixtures("local_source_schema")
def test_finalization_repeat_and_public_admission(produced):
    """New native/audit contracts survive the actual public lifecycle."""
    report = produced.finalize(fresh_run=True)
    assert report["producer_native_inputs"]["recipe_identity"]["sealed"] is True
    assert produced.finalize() == report
    verify_finalized_source_files([produced.output_node_file, produced.output_edge_file])
    assert (
        len([row for row in graph_rows(produced.output_edge_file) if row.get("source_assertion_id")])
        == report["producer_native_inputs"]["recipe_identity"]["native_occurrences"]
    )


@pytest.mark.parametrize("target", ["policy", "index", "rows"])
def test_parsed_witness_mutation_refused(produced, target):
    """Changing cached decisions cannot be hidden by an unchanged original file checksum."""
    guard = produced._recipe_identity_guard
    getattr(guard, target).clear()
    with pytest.raises(SourceFinalizationRequired, match="cached"):
        produced.verify_consumed_inputs()


@pytest.mark.parametrize("cohort", ["nested", "missing", "oatmeal", "substrate"])
def test_audit_content_not_optional(produced, cohort):
    """Evidence removal is a producer failure even when the graph remains unchanged."""
    path = produced.output_dir / identity.AUDITS[cohort]
    header = path.read_text().splitlines()[0]
    path.write_text(header + "\n")
    with pytest.raises(SourceFinalizationRequired):
        produced.verify_consumed_inputs()


def test_zero_cohort_writes_four_honest_empty_audits(tmp_path, monkeypatch):
    """No native nested/finite material observations is valid, not missing evidence."""
    from tests.test_mediadive_recipe_occurrences import _run_transform

    value = _run_transform(tmp_path, monkeypatch, {})
    assert value.producer_native_inputs["recipe_identity"]["native_occurrences"] == 0
    for name in identity.AUDITS.values():
        assert (value.output_dir / name).read_text().splitlines() == ["\t".join(identity.HEADER)]


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("mutation", ["all", "partial", "rewritten"])
def test_outer_audit_restamp_cannot_hide_native_evidence_loss(produced, mutation):
    """The public validator reconstructs full evidence from native bytes, not outer hashes."""
    produced.finalize(fresh_run=True)
    name = identity.AUDITS["oatmeal"]
    path = produced.output_dir / name
    with path.open() as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        header, rows = reader.fieldnames, list(reader)
    if mutation == "all":
        rows = []
    elif mutation == "partial":
        rows.pop()
    else:
        payload = json.loads(rows[0]["source_record"])
        payload["attribute"] = "invented colloidal evidence"
        rows[0]["source_record"] = identity.encoded(payload)
        rows[0]["source_record_sha256"] = identity.digest(payload)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=header, delimiter="\t", quoting=csv.QUOTE_NONE, quotechar=None, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    report_path = produced.output_dir / "source_finalization.json"
    report = json.loads(report_path.read_text())
    restamped = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    report["audit_members"][name] = restamped
    report["producer_audit_members"][name] = restamped
    report_path.write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([produced.output_node_file, produced.output_edge_file])


def test_native_concept_access_is_not_globally_denied():
    """Source-scoped decisions leave the native class metadata and direct queries eligible."""
    from kg_microbe.utils.ingredient_context import ingredient_context_allowed

    assert ingredient_context_allowed("NCIT:C29298")
    assert ingredient_context_allowed("NCIT:C120264")


def test_medium_display_cleaning_does_not_mutate_native_list(produced):
    """Real native names exercise cleanup; original admitted source records stay identical (#1320)."""
    original = json.loads((produced.input_base_dir / "mediadive.json").read_text())
    assert produced._bulk_parsed_payloads["mediadive_media_list"] == original
    assert any(
        row["name"] != row["name"].translate(produced.translation_table).replace('""', "").strip()
        for row in original["data"]
    )
    produced._bulk_parsed_payloads["mediadive_media_list"]["data"][0]["name"] += " tampered"
    with pytest.raises(SourceFinalizationRequired, match="cached native payload changed"):
        produced.verify_consumed_inputs()


@pytest.mark.parametrize("synthetic_controls", [False, True])
def test_strain_writer_is_linear_and_preserves_native_observations(tmp_path, monkeypatch, synthetic_controls):
    """Actual writer retains order/true duplicates without accumulated-prefix rewrites."""
    original_writer = mod.tsv_writer
    written = []

    def spy(stream):
        """Observe emitted BacDive growth rows while preserving the real writer."""
        actual = original_writer(stream)
        if Path(stream.name).name != "edges.tsv":
            return actual

        def writerows(rows):
            """Retain the actual growth-row occurrences before forwarding them."""
            rows = list(rows)
            written.extend(
                tuple(row)
                for row in rows
                if len(row) > 4
                and row[4] == "infores:bacdive"
                and row[1] in (mod.NCBI_TO_MEDIUM_EDGE, mod.NCBI_TO_MEDIUM_NEGATIVE_EDGE)
            )
            actual.writerows(rows)

        return SimpleNamespace(writerow=actual.writerow, writerows=writerows)

    def controls(raw):
        """Create explicit synthetic growth controls without changing native recipes."""
        # Explicitly synthetic growth controls, separate from the intact native
        # recipe/material witnesses: preserve a real duplicate, both polarities,
        # and do not emit unknown-growth or absent-BacDive observations.
        medium = str(json.loads((raw / "mediadive.json").read_text())["data"][0]["id"])
        positive = {"bacdive_id": 12345678, "species": "Synthetic test strain", "growth": 1}
        observations = [
            positive,
            {**positive, "growth": 0},
            positive,
            {**positive, "growth": None},
            {**positive, "bacdive_id": None},
        ]
        (raw / "mediadive/media_strains.json").write_text(json.dumps({medium: observations}))

    monkeypatch.setattr(mod, "tsv_writer", spy)
    value = _build(tmp_path, monkeypatch, controls if synthetic_controls else None)
    selected = [str(row["id"]) for row in json.loads((value.input_base_dir / "mediadive.json").read_text())["data"]]
    expected = []
    for medium in selected:
        for strain in value.media_strains.get(medium, []):
            if strain.get("bacdive_id") and strain.get("growth") in (0, 1):
                predicate = mod.NCBI_TO_MEDIUM_EDGE if strain["growth"] == 1 else mod.NCBI_TO_MEDIUM_NEGATIVE_EDGE
                expected.append(
                    (
                        predicate,
                        mod.MEDIADIVE_MEDIUM_PREFIX + medium,
                        mod.bacdive_record_url("bacdive:" + str(strain["bacdive_id"])),
                    )
                )
    assert [(row[1], row[2], row[9]) for row in written] == expected
    assert len(written) == len(expected)
    if synthetic_controls:
        assert len(written) == 3 and written[0] == written[2] and written[0][1] != written[1][1]
    # The legacy accumulated-prefix algorithm changes multiplicity only; exact
    # complete row identities after deduplication are conserved.
    old_rows = []
    for medium in selected:
        prefix = []
        for row in written:
            if row[2] == mod.MEDIADIVE_MEDIUM_PREFIX + medium:
                prefix.append(row)
                old_rows.extend(prefix)
    assert set(old_rows) == set(written)
    with value.output_edge_file.open() as stream:
        output = list(csv.DictReader(stream, delimiter="\t"))
    actual = {
        tuple(row[field] for field in value.edge_header[:10])
        for row in output
        if row[mod.PRIMARY_KNOWLEDGE_SOURCE_COLUMN] == "infores:bacdive"
        and row[mod.PREDICATE_COLUMN] in (mod.NCBI_TO_MEDIUM_EDGE, mod.NCBI_TO_MEDIUM_NEGATIVE_EDGE)
    }
    assert actual == {tuple(str(field) for field in row) for row in written}


def _fresh_instance(produced):
    """Use an actual new constructor over the same unchanged native fixture epoch."""
    with (
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_roles"),
        mock.patch.object(mod.MediaDiveTransform, "_load_chebi_categories"),
        mock.patch.object(mod, "ChemicalMappingLoader", return_value=_loader()),
    ):
        return mod.MediaDiveTransform(produced.input_base_dir, produced.output_dir.parent)


@pytest.mark.usefixtures("local_source_schema")
def test_fresh_instance_checkpoint_reconsumes_native_evidence(produced):
    """A new instance gets genuine read guards, not receipt-only checkpoint reuse."""
    report = produced.finalize(fresh_run=True)
    fresh = _fresh_instance(produced)
    assert fresh.finalize() == report
    assert fresh.producer_native_inputs == report["producer_native_inputs"]
    assert fresh._recipe_identity_guard is not produced._recipe_identity_guard
    fresh.verify_consumed_inputs()
    verify_finalized_source_files([fresh.output_node_file, fresh.output_edge_file])


@pytest.mark.usefixtures("local_source_schema")
def test_rerun_over_previous_finalization_writes_and_refinalizes(produced, monkeypatch):
    """A previous run's report must not switch a new writer's TSVs to the canonical reader."""
    first = produced.finalize(fresh_run=True)
    rerun = _fresh_instance(produced)
    monkeypatch.setattr(rerun, "_get_mediadive_json", lambda *args: pytest.fail("network fallback"))
    rerun.run(show_status=False)
    second = rerun.finalize(fresh_run=True)
    assert second["members"] == first["members"]
    verify_finalized_source_files([rerun.output_node_file, rerun.output_edge_file])


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("mutation", ["cached_native", "role", "source_file", "deleted_audit"])
def test_fresh_checkpoint_never_erases_existing_conflicts(produced, mutation):
    """Original constructor state, native bytes and mandatory evidence remain authoritative."""
    produced.finalize(fresh_run=True)
    fresh = _fresh_instance(produced)
    if mutation == "cached_native":
        fresh.solutions_data.clear()
    elif mutation == "role":
        fresh._consumed_input_snapshots["mediadive_solutions"]["sha256"] = "0" * 64
    elif mutation == "source_file":
        path = fresh.input_base_dir / "mediadive/solutions.json"
        path.write_text(path.read_text() + "\n")
    else:
        (fresh.output_dir / identity.AUDITS["oatmeal"]).unlink()
    with pytest.raises(SourceFinalizationRequired):
        fresh.finalize()


def test_completion_flag_cannot_disable_native_graph_verification(produced):
    """The supported guard surface is monotonic once actual writer evidence is sealed."""
    with pytest.raises(AttributeError):
        produced._recipe_identity_guard.sealed = False


def test_whole_guard_removal_cannot_hide_required_contract(produced):
    """Even erasing the preparation sentinel must not erase mandatory source evidence."""
    produced._recipe_identity_guard = None
    produced._recipe_identity_prepared = False
    with pytest.raises(SourceFinalizationRequired, match="recipe identity guard is missing"):
        produced.verify_consumed_inputs()


@pytest.mark.parametrize("mutation", ["xref", "outgoing"])
def test_finite_materials_cannot_regain_invented_identity(produced, mutation):
    """Retaining a local endpoint does not permit NCIT identity to leak via enrichment."""
    if mutation == "xref":
        path = produced.output_node_file
        with path.open() as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            header, rows = reader.fieldnames, list(reader)
        for row in rows:
            if row["id"] == "mediadive.ingredient:471":
                row["xref"] = "NCIT:C29298"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=header, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
    else:
        with produced.output_edge_file.open("a", newline="") as stream:
            row = dict.fromkeys(produced.edge_header, "")
            row.update(subject="mediadive.ingredient:471", predicate="biolink:same_as", object="NCIT:C29298")
            csv.DictWriter(stream, fieldnames=produced.edge_header, delimiter="\t").writerow(row)
    with pytest.raises(SourceFinalizationRequired):
        produced.verify_consumed_inputs()


@pytest.mark.usefixtures("local_source_schema")
@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize(
    "identifier,column,replacement,node",
    [
        ("mediadive.ingredient:471", "name", "Glucose", True),
        ("mediadive.ingredient:672", "name", "Glucose", True),
        ("mediadive.ingredient:471", "provided_by", "infores:unrelated", True),
        ("mediadive.solution:2269", "provided_by", "infores:unrelated", True),
        ("mediadive.ingredient:471", "primary_knowledge_source", "infores:unrelated", False),
        ("mediadive.ingredient:471", "relation", "RO:0002503", False),
        ("mediadive.ingredient:471", "knowledge_level", "prediction", False),
        ("mediadive.ingredient:471", "agent_type", "automated_agent", False),
        ("mediadive.ingredient:471", "publications", "PMID:1", False),
    ],
)
def test_native_metadata_is_not_replaceable_by_restamped_output(
    produced, published, identifier, column, replacement, node
):
    """Full source-derived metadata is checked live and in recorded admission (#1326)."""
    expected_error = (
        "native declaration provenance changed"
        if column == "provided_by"
        else "source-owned material declaration changed"
        if node
        else "native recipe relation/provenance/knowledge metadata changed"
    )
    if published:
        produced.finalize(fresh_run=True)
    path = produced.output_node_file if node else produced.output_edge_file
    quoting = csv.QUOTE_NONE if published else csv.QUOTE_MINIMAL
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=quoting)
        header, rows = reader.fieldnames, list(reader)
    for row in rows:
        if (node and row["id"] == identifier) or (
            not node and row.get("object") == identifier and row.get("source_assertion_id")
        ):
            row[column] = replacement
            break
    else:
        pytest.fail("Protected native fixture observation missing")
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=header,
            delimiter="\t",
            quoting=quoting,
            quotechar=None if published else '"',
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    if published:
        report_path = produced.output_dir / "source_finalization.json"
        report = json.loads(report_path.read_text())
        report["members"][path.name] = {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        report_path.write_text(json.dumps(report))
        with pytest.raises(SourceFinalizationRequired, match=expected_error):
            verify_finalized_source_files([produced.output_node_file, produced.output_edge_file])
    else:
        with pytest.raises(SourceFinalizationRequired, match=expected_error):
            produced.verify_consumed_inputs()


@pytest.mark.parametrize(
    "relative",
    [
        "mediadive.json",
        "mediadive/media_detailed.json",
        "mediadive/media_strains.json",
        "mediadive/solutions.json",
        "mediadive/compounds.json",
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_native_duplicate_keys_fail_before_graph_output(tmp_path, monkeypatch, relative, nested):
    """Neither duplicate catalog IDs nor ambiguous record fields are silently collapsed (#1319)."""

    def duplicate(raw):
        """Add an explicit synthetic ambiguity to otherwise intact immutable native excerpts."""
        path = raw / relative
        text = path.read_text()
        if nested:
            # A duplicate field in a nested record is equally ambiguous even if
            # its values happen to agree; preserve no last-key-wins assumption.
            text = (
                text.replace('"id":', '"id": 999999999, "id":', 1)
                if '"id":' in text
                else text.replace('"compound_id":', '"compound_id": 999999999, "compound_id":', 1)
            )
        else:
            payload = json.loads(text)
            key = next(iter(payload))
            text = "{" + json.dumps(key) + ":" + json.dumps(payload[key]) + "," + text.lstrip()[1:]
        path.write_text(text)

    with pytest.raises(SourceFinalizationRequired, match="duplicate JSON key"):
        _build(tmp_path, monkeypatch, duplicate)
    assert not (tmp_path / "transformed/mediadive/nodes.tsv").exists()
    assert not (tmp_path / "transformed/mediadive/edges.tsv").exists()
