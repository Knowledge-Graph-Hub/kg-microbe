"""Controls for full-row historical source reconciliation, without live source inputs."""

import csv
import json
import subprocess
from pathlib import Path

import pytest

from scripts import reconcile_kgm_source_rows as rows


def _json(path, value):
    """Write one local fixture and return its exact byte binding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n")
    return {"path": str(path), **rows.fingerprint(path)}


def _table(path, records, *, graph=False, delimiter="\t"):
    """Write a fixture with the declared graph or transport dialect."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(records[0]),
            delimiter=delimiter,
            quoting=csv.QUOTE_NONE if graph else csv.QUOTE_MINIMAL,
            quotechar=None if graph else '"',
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(records)
    return {"path": str(path), **rows.fingerprint(path)}


def _git(root, *args):
    """Create an isolated fixture checkout with no dependence on caller Git settings."""
    import os

    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return (
        subprocess.check_output(  # noqa: S603 - fixed fixture-only Git operations
            ["git", *args],  # noqa: S607 - fixture Git from PATH
            cwd=root,
            env=environment,
        )
        .decode()
        .strip()
    )


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    """Build all four historical provider paths, including a shared ID and subset ordinal."""
    root, kg, combined = (tmp_path / name for name in ("source", "kg", "combined"))
    root.mkdir()
    _git(root, "init", "-q")
    _git(
        root, "-c", "user.name=Fixture", "-c", "user.email=fixture.invalid", "commit", "--allow-empty", "-qm", "fixture"
    )
    revision = _git(root, "rev-parse", "HEAD")
    identifiers = {
        "mediadive": "mediadive.ingredient:9",
        "metatraits": "kgmicrobe.compound:a",
        "metatraits_gtdb": "kgmicrobe.compound:a",
        "microbedecoder": "kgmicrobe.compound:pyg",
    }
    refs, finalizations, graphs, graph_nodes = {}, {}, {}, {}
    recipe = {"compound_id": 9, "amount": 5, "unit": "mg"}
    solution = {"id": 5, "recipe": [recipe]}
    refs["solutions"] = _json(root / "data/raw/solutions.json", {"5": solution})
    refs["generation_manifest"] = _json(root / "data/raw/generation.json", {"generation": 1})
    refs["generation_pointer"] = _json(root / "data/raw/current.json", {"generation": 1})
    compound = {"id": 9, "name": "Example"}
    refs["compounds"] = _json(kg / "inputs/compounds.json", {"9": compound})
    raw_row = {"taxon": "sample", "literal": "PYG"}
    raw_database = _table(root / "data/raw/database.csv", [{"taxon": "other", "literal": "NA"}, raw_row], delimiter=",")
    source_record = f"sha256:{raw_database['sha256']}#record=2"
    micro_edge = {
        "subject": "lpsn:1",
        "predicate": "biolink:consumes",
        "object": identifiers["microbedecoder"],
        "relation": "RO:0002438",
        "source_citation": "doi:fixture",
        "primary_knowledge_source": "infores:fixture",
        "knowledge_level": "knowledge_assertion",
        "agent_type": "manual_agent",
        "value_encoding": "backslash",
        "source_record": source_record,
        "source_column": "literal",
        "value": "PYG",
        "qualifier": "held",
    }
    literal = json.dumps(raw_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    raw_digest = hashlib.sha256(literal.encode()).hexdigest()
    hold = {
        **{
            key: micro_edge[key]
            for key in (
                "subject",
                "predicate",
                "relation",
                "source_citation",
                "primary_knowledge_source",
                "knowledge_level",
                "agent_type",
                "value_encoding",
                "source_record",
                "source_column",
            )
        },
        "object_curie": identifiers["microbedecoder"],
        "source_literal": "PYG",
        "identity_status": "unresolved",
        "identity_approved": "false",
        "raw_record_sha256": raw_digest,
        "curation_rationale": "Still held",
    }
    raw = {
        "source_record": source_record,
        "raw_record_sha256": raw_digest,
        "raw_row": raw_row,
        "bound_dispositions": [hold],
    }
    refs["microbedecoder_raw"] = _json(kg / "inputs/raw.json", {"2": raw})
    refs["microbedecoder_holds"] = _json(kg / "inputs/holds.json", [hold])
    refs["microbedecoder_edges"] = _table(kg / "inputs/micro-edges.tsv", [micro_edge])
    originals = {}
    media_original = {
        "source_id": identifiers["mediadive"],
        "raw_compound_id": "9",
        "raw_record_found": "True",
        "raw_source_sha256": refs["compounds"]["sha256"],
        "raw_record_json": rows.compact(compound),
    }
    micro_original = {
        "placeholder_curie": identifiers["microbedecoder"],
        "category": "biolink:ChemicalEntity",
        "label": "PYG",
        "source_columns": "literal",
        "occurrences": "1",
        "mapping_status": "UNMAPPED",
    }
    other_originals = []
    for source in rows.SOURCES:
        identifier = identifiers[source]
        node = {"id": identifier, "name": source, "category": "biolink:ChemicalEntity"}
        graph_nodes[source] = node
        if source == "mediadive":
            edges = [
                {
                    "subject": "mediadive.solution:5",
                    "predicate": "biolink:has_part",
                    "object": identifier,
                    "source_assertion_id": "mediadive.solution:5#recipe/1",
                    "source_record": rows.compact(recipe),
                }
            ]
        elif source == "microbedecoder":
            edges = [{**micro_edge, "object": "CHEBI:1", "value": "other"}, micro_edge]
        else:
            edges = [
                {
                    "subject": identifier,
                    "predicate": "biolink:related_to",
                    "object": identifier,
                    "qualifier": '"literal"',
                }
            ]
            other_originals.append(
                {
                    "source": source,
                    "source_id": identifier,
                    "node_record_json": rows.compact(node),
                    "occurrences": "1",
                    "predicate_counts": rows.compact({"biolink:related_to": 1}),
                }
            )
        directory = root / f"data/transformed/{source}"
        edge_ref = _table(directory / "edges.tsv", edges, graph=True)
        node_ref = _table(directory / "nodes.tsv", [node], graph=True)
        graphs[source] = edges
        refs[source + "_edges"] = edge_ref
        marker = {
            "source": source,
            "tsv_quoting": "none",
            "members": {"edges.tsv": edge_ref, "nodes.tsv": node_ref},
            "summaries": {"rows": {"edges": len(edges), "nodes": 1}},
            "consumed_inputs": {},
        }
        if source == "mediadive":
            marker["consumed_inputs"] = {
                "mediadive_solutions": refs["solutions"],
                "mediadive_compounds": refs["compounds"],
                "mediadive_generation_manifest": refs["generation_manifest"],
                "mediadive_generation_pointer": refs["generation_pointer"],
            }
        if source == "microbedecoder":
            marker["consumed_inputs"] = {"crosswalk_raw": raw_database}
        finalizations[source] = _json(directory / "source_finalization.json", marker)
    refs["microbedecoder_edges"] = _table(kg / "inputs/micro-edges.tsv", [micro_edge])
    refs["mediadive_nodes"] = _table(kg / "inputs/media-nodes.tsv", [media_original])
    refs["microbedecoder_nodes"] = _table(kg / "inputs/micro-nodes.tsv", [micro_original])
    refs["other_nodes"] = _table(kg / "inputs/other-nodes.tsv", other_originals)
    originals["mediadive"] = ("mediadive_nodes", 1, media_original)
    originals["microbedecoder"] = ("microbedecoder_nodes", 1, micro_original)
    for position, source in enumerate(("metatraits", "metatraits_gtdb"), 1):
        originals[source] = ("other_nodes", position, other_originals[position - 1])
    refs["microbedecoder_proof"] = _json(
        kg / "inputs/micro-proof.json",
        {
            "raw_path": raw_database["path"],
            "raw_sha256": raw_database["sha256"],
            "raw_selected_records": 1,
            "material_disposition_rows": 1,
            "graph_sha256": refs["microbedecoder_edges"]["sha256"],
        },
    )
    # The detached subset and complete graph have different hashes and row coordinates.
    proof = json.loads(Path(refs["microbedecoder_proof"]["path"]).read_text())
    proof["graph_sha256"] = rows.fingerprint(root / "data/transformed/microbedecoder/edges.tsv")["sha256"]
    refs["microbedecoder_proof"] = _json(Path(refs["microbedecoder_proof"]["path"]), proof)
    nodes = []
    for identifier in sorted(set(identifiers.values())):
        providers = [source for source in rows.SOURCES if identifiers[source] == identifier]
        nodes.append(
            {
                "source_id": identifier,
                "providers_json": rows.compact(providers),
                "original_case_ids_json": rows.compact([source + ":case" for source in providers]),
                "original_node_rows_json": rows.compact(
                    [
                        {
                            "provider": source,
                            "input": originals[source][0],
                            "position": originals[source][1],
                            "row": originals[source][2],
                        }
                        for source in providers
                    ]
                ),
                "current_graph_node_rows_json": rows.compact(
                    [
                        {
                            "provider": source,
                            "position": 1,
                            "row": graph_nodes[source],
                            "input": {
                                "path": str(root / f"data/transformed/{source}/nodes.tsv"),
                                **rows.fingerprint(root / f"data/transformed/{source}/nodes.tsv"),
                            },
                        }
                        for source in providers
                    ]
                ),
            }
        )
    occurrences = []
    for source in rows.SOURCES:
        identifier = identifiers[source]
        if source == "mediadive":
            kind, ref, position, locator, payload = (
                "raw_solution_recipe",
                refs["solutions"],
                1,
                "mediadive.solution:5#recipe/1",
                recipe,
            )
            context = {
                "solution_key": "5",
                "solution_record": solution,
                "direct_incoming_solution_references": [],
                "scope": (
                    "Every direct raw compound assertion in the admitted solutions; "
                    "incoming references are context, not extra material counts"
                ),
            }
        elif source == "microbedecoder":
            kind, ref, position, locator, payload = (
                "material_graph_observation",
                refs["microbedecoder_edges"],
                1,
                source_record + "::literal::PYG",
                micro_edge,
            )
            context = {"raw_record": raw, "original_material_disposition": hold}
        else:
            kind, ref, position, locator, payload = (
                "incident_graph_edge",
                refs[source + "_edges"],
                1,
                "rows/1",
                graphs[source][0],
            )
            context = {"source_node_row": originals[source][2], "incident_roles": ["subject", "object"]}
        occurrences.append(
            dict(
                zip(
                    rows.OCC_FIELDS,
                    [
                        identifier,
                        source,
                        kind,
                        ref["path"],
                        ref["sha256"],
                        str(position),
                        locator,
                        rows.compact(payload),
                        rows.compact(context),
                    ],
                    strict=True,
                )
            )
        )
    products = {}
    combined_products = {}
    for kind, records in (("nodes", nodes), ("occurrences", occurrences)):
        name = f"source-{kind}.tsv"
        products[name] = _table(kg / name, records)["sha256"]
        _table(combined / f"originals/kg_{kind}.tsv", records)
        cm = {key: "" for key in records[0]}
        cm["source_id"] = "MIMCMREFv1:unrelated"
        combined_records = [
            {
                **cm,
                "assembly_original_table": f"originals/cm_{kind}.tsv",
                "assembly_original_position": "1",
                "assembly_original_sha256": "c" * 64,
            }
        ]
        combined_records += [
            {
                **row,
                "assembly_original_table": f"originals/kg_{kind}.tsv",
                "assembly_original_position": str(position),
                "assembly_original_sha256": products[name],
            }
            for position, row in enumerate(records, 1)
        ]
        combined_products[name] = _table(combined / name, combined_records)
    unmapped = {key: value for key, value in micro_original.items() if key != "mapping_status"}
    unmapped_ref = _table(root / "data/transformed/microbedecoder/unmapped_labels.tsv", [unmapped])
    historical_files = {
        "snapshots/data/transformed/" + source + "/source_finalization.json": ref
        for source, ref in finalizations.items()
    }
    historical_files["snapshots/data/transformed/microbedecoder/unmapped_labels.tsv"] = unmapped_ref
    historical_ref = _json(
        tmp_path / "historical/receipt.json",
        {
            "upstream_root": str(root),
            "upstream_revision": revision,
            "files": historical_files,
            "complete_microbedecoder_compound_subset": {
                "native_helper_prefix": "compound",
                "native_helper_min_occurrences": 0,
                "input_rows": 1,
                "compound_rows": 1,
                "rare_rows_under10": 1,
            },
        },
    )
    cases = [{"source": "culturemech", "case_id": "CM:fixture"}]
    for node in nodes:
        for source, case_id in zip(
            json.loads(node["providers_json"]), json.loads(node["original_case_ids_json"]), strict=True
        ):
            cases.append(
                {
                    "source": source,
                    "case_id": case_id,
                    "source_case_id": node["source_id"],
                    "original_kg_entry": {"source_id": node["source_id"]},
                }
            )
    refs["cases"] = _json(kg / "inputs/cases.json", cases)
    kg_ref = _json(kg / "manifest.json", {"files": products, "inputs": refs})
    combined_ref = _json(combined / "manifest.json", {"products": combined_products})
    monkeypatch.setattr(
        rows, "COUNTS", {"kg_source_ids": 3, "provider_cases": 4, "kg_occurrences": 4, "shared_metatraits_gtdb_ids": 1}
    )
    monkeypatch.setattr(rows, "EXPECTED", {source: {"cases": 1, "occurrences": 1} for source in rows.SOURCES})
    return {
        "source_root": root,
        "historical_receipt": historical_ref["path"],
        "historical_sha256": historical_ref["sha256"],
        "kg_inputs": kg,
        "kg_manifest_sha256": kg_ref["sha256"],
        "combined_inputs": combined,
        "combined_manifest_sha256": combined_ref["sha256"],
        "output": tmp_path / "new-proof",
    }


def test_complete_row_handoff_retains_subset_and_global_positions(cohort):
    """A success retains full raw holds and graph rows while keeping approval false."""
    report = rows.reconcile(**cohort)
    assert report["status"] == "PASS_HISTORICAL_SOURCE_ROW_RECONCILIATION"
    assert not report["production_admission"] and not report["scientific_approval"]
    assert len(report["graph_members"]) == 8
    assert report["inputs_before"] == report["inputs_after"]
    ledger = json.loads((cohort["output"] / "full-row-ledger.json").read_text())
    micro = next(row for row in ledger if row["provider"] == "microbedecoder")
    assert micro["occurrence"]["physical_position"] == "1"
    assert micro["graph_row"] == 2
    assert micro["combined_global_row"] == 5
    assert (
        json.loads(micro["occurrence"]["context_json"])["original_material_disposition"]["identity_approved"] == "false"
    )
    assert micro["graph_full_row"]["qualifier"] == "held"
    mt = next(row for row in ledger if row["provider"] == "metatraits")
    assert json.loads(mt["occurrence"]["context_json"])["incident_roles"] == ["subject", "object"]


@pytest.mark.parametrize("target", ["source_graph", "occurrences", "frozen_projection", "raw_database"])
def test_changed_input_bytes_fail_without_success_receipt(cohort, target):
    """Changed graph, transport, frozen copy or raw CSV cannot be digest-restamped implicitly."""
    paths = {
        "source_graph": cohort["source_root"] / "data/transformed/metatraits/edges.tsv",
        "occurrences": cohort["kg_inputs"] / "source-occurrences.tsv",
        "frozen_projection": cohort["combined_inputs"] / "originals/kg_occurrences.tsv",
        "raw_database": cohort["source_root"] / "data/raw/database.csv",
    }
    with paths[target].open("a") as handle:
        handle.write("changed\n")
    with pytest.raises(ValueError, match="differs"):
        rows.reconcile(**cohort)
    assert not (cohort["output"] / "row-reconciliation.json").exists()


def test_existing_output_is_not_replaced(cohort):
    """A prior evidence directory is preserved even if empty."""
    cohort["output"].mkdir()
    with pytest.raises(ValueError, match="output already exists"):
        rows.reconcile(**cohort)


@pytest.mark.parametrize("change", ["cell", "position", "hash", "marker", "duplicate", "missing"])
def test_projection_rejects_incoherent_or_incomplete_original_rows(change):
    """Every transport cell, row and assembly coordinate participates in reconciliation."""
    original = [(1, {"source_id": "kg:x", "provider": "metatraits", "qualifier": "held"})]
    row = {
        **original[0][1],
        "assembly_original_table": "originals/kg_occurrences.tsv",
        "assembly_original_position": "1",
        "assembly_original_sha256": "a" * 64,
    }
    combined = [(8, row)]
    if change == "cell":
        row["qualifier"] = "approved"
    elif change == "position":
        row["assembly_original_position"] = "2"
    elif change == "hash":
        row["assembly_original_sha256"] = "b" * 64
    elif change == "marker":
        row["assembly_original_table"] = "originals/cm_occurrences.tsv"
    elif change == "duplicate":
        combined.append((9, dict(row)))
    else:
        combined.clear()
    with pytest.raises(ValueError):
        rows.projection(original, combined, "kg_occurrences", "a" * 64)


def test_graph_quote_none_retains_literal_quotes(tmp_path):
    """Historical graph quotes are literal characters rather than CSV quoting syntax."""
    path = tmp_path / "graph.tsv"
    path.write_text('id\tname\nx\t"literal"\n')
    assert list(rows.table(path, graph=True))[0][1]["name"] == '"literal"'
    assert list(rows.table(path))[0][1]["name"] == "literal"


@pytest.mark.parametrize("content", ["a\ta\n1\t2\n", "a\tb\n1\n", "a\tb\n1\t2\t3\n"])
def test_malformed_table_width_or_duplicate_header_is_rejected(tmp_path, content):
    """Every parsed row must retain exactly one value for every declared column."""
    path = tmp_path / "bad.tsv"
    path.write_text(content)
    with pytest.raises(ValueError):
        list(rows.table(path, graph=True))


def test_input_second_read_detects_same_size_change(tmp_path):
    """The final guard detects a same-length edit after an input was consumed."""
    path = tmp_path / "input"
    path.write_text("first")
    inputs = rows.Inputs()
    inputs.add(path)
    path.write_text("other")
    with pytest.raises(ValueError, match="changed"):
        inputs.finish()


def test_symlink_input_is_rejected(tmp_path):
    """A linked alias cannot impersonate the selected physical source."""
    original = tmp_path / "original"
    original.write_text("fixed")
    alias = tmp_path / "alias"
    alias.symlink_to(original)
    with pytest.raises(ValueError, match="symlink"):
        rows.fingerprint(alias)


@pytest.mark.parametrize("left,right", [(True, 1), (5, 5.0), ({"value": "NA"}, {"value": ""})])
def test_typed_payloads_are_not_normalized(left, right):
    """No normalization may erase an original literal or its JSON type."""
    with pytest.raises(ValueError):
        rows.same_json(left, right, "changed payload")


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_ambiguous_json_is_refused(text):
    """Duplicate keys and nonfinite values cannot create alternate payload interpretations."""
    with pytest.raises(ValueError):
        rows.document(text)


def _replace_occurrence(cohort, source, update):
    """Coherently repin transport copies while leaving original graph evidence immutable."""
    kg, combined = cohort["kg_inputs"], cohort["combined_inputs"]
    occurrences = [row for _, row in rows.table(kg / "source-occurrences.tsv")]
    selected = next(row for row in occurrences if row["provider"] == source)
    update(selected)
    ref = _table(kg / "source-occurrences.tsv", occurrences)
    _table(combined / "originals/kg_occurrences.tsv", occurrences)
    manifest = json.loads((kg / "manifest.json").read_text())
    manifest["files"]["source-occurrences.tsv"] = ref["sha256"]
    cohort["kg_manifest_sha256"] = _json(kg / "manifest.json", manifest)["sha256"]
    combined_rows = [row for _, row in rows.table(combined / "source-occurrences.tsv")]
    cm = combined_rows[0]
    updated = [cm] + [
        {
            **row,
            "assembly_original_table": "originals/kg_occurrences.tsv",
            "assembly_original_position": str(position),
            "assembly_original_sha256": ref["sha256"],
        }
        for position, row in enumerate(occurrences, 1)
    ]
    combined_ref = _table(combined / "source-occurrences.tsv", updated)
    manifest = json.loads((combined / "manifest.json").read_text())
    manifest["products"]["source-occurrences.tsv"] = combined_ref
    cohort["combined_manifest_sha256"] = _json(combined / "manifest.json", manifest)["sha256"]


@pytest.mark.parametrize(
    "source,change",
    [
        ("mediadive", "raw_type"),
        ("metatraits", "roles"),
        ("microbedecoder", "hold"),
        ("microbedecoder", "qualifier"),
        ("microbedecoder", "subset_position"),
    ],
)
def test_coherent_transport_repin_cannot_change_source_meaning(cohort, source, change):
    """Consistent transport hashes never authorize changed raw meaning, holds or graph rows."""

    def alter(row):
        """Modify exactly the claimed source payload while keeping native transports coherent."""
        context = json.loads(row["context_json"])
        record = json.loads(row["source_record_json"])
        if change == "raw_type":
            record["amount"] = 5.0
        elif change == "roles":
            context["incident_roles"] = ["object"]
        elif change == "hold":
            context["original_material_disposition"]["identity_approved"] = "true"
        elif change == "qualifier":
            record["qualifier"] = "approved"
        else:
            row["physical_position"] = "2"
        row["context_json"] = rows.compact(context)
        row["source_record_json"] = rows.compact(record)

    _replace_occurrence(cohort, source, alter)
    with pytest.raises(ValueError):
        rows.reconcile(**cohort)
    assert not (cohort["output"] / "row-reconciliation.json").exists()


@pytest.mark.parametrize("selector", ["output", "source_root", "kg_inputs", "combined_inputs", "historical_receipt"])
def test_parent_traversal_is_refused_before_any_output(cohort, selector):
    """Lexical containment cannot conceal a write or read inside an aliased input tree."""
    original = Path(cohort[selector])
    cohort[selector] = original.parent / "safe" / ".." / original.name
    if selector == "output":
        cohort[selector] = cohort["source_root"].parent / "safe" / ".." / "source" / "new-proof"
    with pytest.raises(ValueError, match="parent traversal"):
        rows.reconcile(**cohort)
    assert not (cohort["source_root"] / "new-proof").exists()
    assert not (original.parent / "safe").exists()


def test_graph_fixture_writes_literal_json_quotes_without_escape_changes(tmp_path):
    """QUOTE_NONE graph fixtures retain JSON quotes as literal production TSV bytes."""
    payload = {"amount": 5, "compound_id": 9}
    path = tmp_path / "graph.tsv"
    _table(path, [{"source_record": rows.compact(payload)}], graph=True)
    assert path.read_text().splitlines()[1] == rows.compact(payload)
    assert list(rows.table(path, graph=True))[0][1]["source_record"] == rows.compact(payload)


def test_coherently_repinned_compounds_must_match_producer_consumed_authority(cohort):
    """Changed detached compounds and matching candidate rows cannot replace production authority."""
    manifest = json.loads((cohort["kg_inputs"] / "manifest.json").read_text())
    marker = json.loads((cohort["source_root"] / "data/transformed/mediadive/source_finalization.json").read_text())
    original_pin = marker["consumed_inputs"]["mediadive_compounds"]["sha256"]
    changed = {"id": 9, "name": "Unsupported replacement"}
    ref = _json(Path(manifest["inputs"]["compounds"]["path"]), {"9": changed})
    manifest["inputs"]["compounds"] = ref
    node = list(rows.table(manifest["inputs"]["mediadive_nodes"]["path"]))[0][1]
    node["raw_source_sha256"] = ref["sha256"]
    node["raw_record_json"] = rows.compact(changed)
    assert ref["sha256"] != original_pin
    graph = list(rows.table(cohort["source_root"] / "data/transformed/mediadive/edges.tsv", graph=True))
    with pytest.raises(ValueError, match="MediaDive acquisition binding differs"):
        rows.mediadive_rows(rows.Inputs(), manifest, marker, {node["source_id"]: node}, graph)


@pytest.mark.parametrize("refuse", [False, True])
def test_csv_field_limit_restored_after_reconciliation_success_or_refusal(cohort, refuse):
    """Large complete payloads do not leak a changed CSV parser limit to the caller."""
    previous = csv.field_size_limit()
    try:
        csv.field_size_limit(64)
        if refuse:
            cohort["output"].mkdir()
            with pytest.raises(ValueError, match="output already exists"):
                rows.reconcile(**cohort)
        else:
            report = rows.reconcile(**cohort)
            assert report["status"] == "PASS_HISTORICAL_SOURCE_ROW_RECONCILIATION"
        assert csv.field_size_limit() == 64
    finally:
        csv.field_size_limit(previous)


def _replace_shared_node(cohort, update):
    """Repin full source and combined node transports without altering original provider tables."""
    kg, combined = cohort["kg_inputs"], cohort["combined_inputs"]
    nodes = [node for _, node in rows.table(kg / "source-nodes.tsv")]
    shared = next(node for node in nodes if len(json.loads(node["providers_json"])) == 2)
    update(shared)
    ref = _table(kg / "source-nodes.tsv", nodes)
    _table(combined / "originals/kg_nodes.tsv", nodes)
    manifest = json.loads((kg / "manifest.json").read_text())
    manifest["files"]["source-nodes.tsv"] = ref["sha256"]
    cohort["kg_manifest_sha256"] = _json(kg / "manifest.json", manifest)["sha256"]
    combined_nodes = [node for _, node in rows.table(combined / "source-nodes.tsv")]
    updated = [combined_nodes[0]] + [
        {
            **node,
            "assembly_original_table": "originals/kg_nodes.tsv",
            "assembly_original_position": str(position),
            "assembly_original_sha256": ref["sha256"],
        }
        for position, node in enumerate(nodes, 1)
    ]
    combined_ref = _table(combined / "source-nodes.tsv", updated)
    manifest = json.loads((combined / "manifest.json").read_text())
    manifest["products"]["source-nodes.tsv"] = combined_ref
    cohort["combined_manifest_sha256"] = _json(combined / "manifest.json", manifest)["sha256"]
    return shared


def test_independent_provider_array_order_preserves_exact_case_pairs(cohort):
    """Faithful case-order reversal leaves source-table and current-graph order unchanged."""

    def reverse_case_order(node):
        """Keep provider and case ID paired while retaining both independent source arrays."""
        for field in ("providers_json", "original_case_ids_json"):
            node[field] = rows.compact(list(reversed(json.loads(node[field]))))

    shared = _replace_shared_node(cohort, reverse_case_order)
    manifest_path = cohort["kg_inputs"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    case_path = Path(manifest["inputs"]["cases"]["path"])
    cases = json.loads(case_path.read_text())
    selected = [case for case in cases if case.get("source_case_id") == shared["source_id"]]
    others = [case for case in cases if case.get("source_case_id") != shared["source_id"]]
    manifest["inputs"]["cases"] = _json(case_path, others + list(reversed(selected)))
    cohort["kg_manifest_sha256"] = _json(manifest_path, manifest)["sha256"]
    rows.reconcile(**cohort)
    emitted = json.loads((cohort["output"] / "full-node-ledger.json").read_text())
    actual = next(row["node"] for row in emitted if row["node"]["source_id"] == shared["source_id"])
    assert actual == shared
    assert json.loads(actual["providers_json"]) == ["metatraits_gtdb", "metatraits"]
    assert [item["provider"] for item in json.loads(actual["original_node_rows_json"])] == [
        "metatraits",
        "metatraits_gtdb",
    ]
    assert [item["provider"] for item in json.loads(actual["current_graph_node_rows_json"])] == [
        "metatraits",
        "metatraits_gtdb",
    ]


@pytest.mark.parametrize("field", ["original_node_rows_json", "current_graph_node_rows_json"])
@pytest.mark.parametrize("change", ["missing", "duplicate", "substitute"])
def test_provider_array_multiplicity_remains_closed(cohort, field, change):
    """Permitting independent order never permits a missing, duplicated or substituted provider."""

    def alter(node):
        """Change one provider array without changing its authoritative case pairs."""
        entries = json.loads(node[field])
        if change == "missing":
            entries.pop()
        elif change == "duplicate":
            entries.append(dict(entries[0]))
        else:
            entries[0]["provider"] = "microbedecoder"
        node[field] = rows.compact(entries)

    _replace_shared_node(cohort, alter)
    with pytest.raises(ValueError, match="provider"):
        rows.reconcile(**cohort)
    assert not (cohort["output"] / "row-reconciliation.json").exists()


def test_case_id_cannot_be_repaired_by_reordering_independent_provider_arrays(cohort):
    """The paired providers/case IDs must still equal the immutable original case ledger."""

    def reverse_only_case_ids(node):
        """Create a coherent transport with the wrong provider-to-case pairing."""
        node["original_case_ids_json"] = rows.compact(list(reversed(json.loads(node["original_case_ids_json"]))))

    _replace_shared_node(cohort, reverse_only_case_ids)
    with pytest.raises(ValueError, match="ordered original provider/case pair differs"):
        rows.reconcile(**cohort)


@pytest.mark.parametrize("field", ["providers_json", "original_case_ids_json"])
@pytest.mark.parametrize("shape", ["object", "nonstring_item"])
def test_provider_case_arrays_have_explicit_string_list_schema(cohort, field, shape):
    """Object keys cannot impersonate ordered arrays during Counter or zip iteration."""

    def alter(node):
        """Keep the original keys while replacing the required JSON array shape."""
        values = json.loads(node[field])
        if shape == "object":
            payload = {key: "ignored value" for key in values}
        else:
            payload = [1, *values[1:]]
        node[field] = rows.compact(payload)

    _replace_shared_node(cohort, alter)
    with pytest.raises(ValueError, match=field + " must be a list of strings"):
        rows.reconcile(**cohort)
    assert not (cohort["output"] / "row-reconciliation.json").exists()


@pytest.mark.parametrize("change", ["missing", "duplicate"])
def test_pinned_case_ledger_complete_unique_membership(cohort, change):
    """Even a coherently repinned case input must retain every unique original case."""
    path = cohort["kg_inputs"] / "manifest.json"
    manifest = json.loads(path.read_text())
    case_path = Path(manifest["inputs"]["cases"]["path"])
    cases = json.loads(case_path.read_text())
    selected = next(case for case in cases if case["source"] == "mediadive")
    if change == "missing":
        cases.remove(selected)
    else:
        cases.append(dict(selected))
    manifest["inputs"]["cases"] = _json(case_path, cases)
    cohort["kg_manifest_sha256"] = _json(path, manifest)["sha256"]
    with pytest.raises(ValueError, match="original case"):
        rows.reconcile(**cohort)
    assert not (cohort["output"] / "row-reconciliation.json").exists()
