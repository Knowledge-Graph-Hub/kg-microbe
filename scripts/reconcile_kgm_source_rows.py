"""
Reconcile immutable historical KG source rows without approving scientific identities.

This helper reads existing products only. A successful report proves the bounded
historical row handoff, not current-runtime admission or a future MIM release.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from pathlib import Path

from kg_microbe.utils.stable_source_candidate import _head

SOURCES = ("mediadive", "metatraits", "metatraits_gtdb", "microbedecoder")
EXPECTED = {
    "mediadive": {"cases": 415, "occurrences": 5332},
    "metatraits": {"cases": 82, "occurrences": 120},
    "metatraits_gtdb": {"cases": 42, "occurrences": 63},
    "microbedecoder": {"cases": 10, "occurrences": 225},
}
COUNTS = {
    "kg_source_ids": 507,
    "provider_cases": 549,
    "kg_occurrences": 5740,
    "shared_metatraits_gtdb_ids": 42,
}
OCC_FIELDS = (
    "source_id",
    "provider",
    "kind",
    "original_input",
    "original_input_sha256",
    "physical_position",
    "source_locator",
    "source_record_json",
    "context_json",
)


def require(condition, message):
    """Reject a changed or unsupported input without repairing its evidence."""
    if not condition:
        raise ValueError(message)


def compact(value):
    """Preserve typed JSON values in a deterministic, surrogate-safe representation."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def row_hash(row):
    """Hash every named field without discarding blank or qualifier columns."""
    return hashlib.sha256(compact(row).encode()).hexdigest()


def document(text):
    """Refuse duplicate JSON object members and nonfinite numbers."""

    def pairs(items):
        """Retain a single value for each uniquely declared key."""
        result = {}
        for key, value in items:
            require(key not in result, f"duplicate JSON member: {key}")
            result[key] = value
        return result

    def invalid(value):
        """Reject JSON extensions for nonfinite numbers."""
        raise ValueError(f"nonfinite JSON value: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def selected_path(path):
    """Reject parent traversal before obtaining an unaliased absolute locator."""
    path = Path(path)
    require(".." not in path.parts, f"parent traversal in selected path: {path}")
    path = Path(os.path.abspath(path))
    require(not any(part.is_symlink() for part in (path, *path.parents)), f"symlink selected path: {path}")
    require(path == path.resolve(strict=False), f"noncanonical selected path: {path}")
    return path


def physical_file(path):
    """Require a real regular input and reject symlinks in its complete locator."""
    path = selected_path(path)
    for part in (path, *path.parents):
        require(not part.is_symlink(), f"symlink input: {part}")
    require(stat.S_ISREG(path.stat().st_mode), f"not a regular input: {path}")
    return path


def identity(path):
    """Bind replacement/content metadata while permitting read-only atime updates."""
    value = path.stat() if isinstance(path, Path) else path
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def fingerprint(path):
    """Stream a complete input and bind its physical identity across the read."""
    path = physical_file(path)
    before = identity(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        require(identity(os.fstat(handle.fileno())) == before, f"input replaced before read: {path}")
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        require(identity(os.fstat(handle.fileno())) == before, f"input changed during read: {path}")
    require(identity(path) == before, f"input replaced during read: {path}")
    return {"sha256": digest.hexdigest(), "bytes": size}


class Inputs:
    """Bind all consumed files and require a second complete byte read at completion."""

    def __init__(self):
        """Start an empty immutable-input inventory."""
        self.before = {}
        self.identities = {}

    def add(self, path, expected=None):
        """Capture a path once and compare every declared digest and byte count."""
        path = physical_file(path)
        key = str(path)
        if key not in self.before:
            self.before[key] = fingerprint(path)
            self.identities[key] = identity(path)
        actual = self.before[key]
        if isinstance(expected, str):
            expected = {"sha256": expected}
        for field in ("sha256", "bytes"):
            if expected is not None and field in expected:
                require(actual[field] == expected[field], f"input {field} differs: {path}")
        require(identity(path) == self.identities[key], f"input identity changed: {path}")
        return path

    def json(self, path, expected=None):
        """Read a bound JSON document without executing an input helper."""
        path = self.add(path, expected)
        return document(path.read_text(encoding="utf-8"))

    def finish(self):
        """Verify all bytes and physical identities again before a success receipt."""
        after = {}
        for key, before_identity in self.identities.items():
            require(identity(physical_file(key)) == before_identity, f"input identity changed: {key}")
            after[key] = fingerprint(key)
            require(after[key] == self.before[key], f"input changed: {key}")
        return after


def table(path, *, graph=False, delimiter="\t", errors="strict"):
    """Stream a width-checked table with its explicit historical quoting dialect."""
    with Path(path).open(encoding="utf-8", errors=errors, newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, quoting=csv.QUOTE_NONE if graph else csv.QUOTE_MINIMAL)
        fields = next(reader, None)
        require(fields and all(fields) and len(fields) == len(set(fields)), f"invalid header: {path}")
        for position, cells in enumerate(reader, 1):
            require(len(cells) == len(fields), f"row width differs: {path}:{position}")
            yield position, dict(zip(fields, cells, strict=True))


def same_json(left, right, message):
    """Compare complete typed payloads without treating integer and boolean as equal."""
    require(compact(left) == compact(right), message)


def projection(original, combined, label, digest):
    """Prove every original cell, multiplicity and position in the combined table."""
    projected = []
    for position, row in combined:
        if row.get("assembly_original_table") == f"originals/{label}.tsv":
            require(row.get("assembly_original_sha256") == digest, "combined original hash differs")
            index = len(projected) + 1
            require(row.get("assembly_original_position") == str(index), "combined original position differs")
            require(index <= len(original), "extra combined KG row")
            expected = original[index - 1][1]
            require(all(row.get(key) == value for key, value in expected.items()), "combined projection differs")
            projected.append((position, row))
        elif label == "kg_occurrences" and row.get("provider") in SOURCES:
            raise ValueError("KG occurrence escaped its original table marker")
        elif label == "kg_nodes" and row.get("source_id") in {r[1]["source_id"] for r in original}:
            raise ValueError("KG node escaped its original table marker")
    require(len(projected) == len(original), "combined projection omits KG rows")
    return projected


def provider_nodes(inputs, manifest, nodes):
    """Reconcile each original provider case and retain provider-specific full rows."""
    providers = {source: {} for source in SOURCES}
    references = manifest["inputs"]
    case_reference = references["cases"]
    cases = inputs.json(case_reference["path"], case_reference)
    require(len({case["case_id"] for case in cases}) == len(cases), "duplicate original case ID")
    cases_by_id = defaultdict(list)
    for case in cases:
        if case["source"] == "culturemech":
            continue
        require(case["source"] in SOURCES, "unknown original case provider")
        require(case["source_case_id"] == case["original_kg_entry"]["source_id"], "original case source ID differs")
        cases_by_id[case["source_case_id"]].append(case)
    require(set(cases_by_id) == {row["source_id"] for _, row in nodes}, "original case source coverage differs")
    originals = {}
    for name in ("mediadive_nodes", "other_nodes", "microbedecoder_nodes"):
        ref = references[name]
        originals[name] = dict(table(inputs.add(ref["path"], ref)))
    require(len({row["source_id"] for _, row in nodes}) == len(nodes), "duplicate KG source ID")
    used = Counter()
    for _, node in nodes:
        original = document(node["original_node_rows_json"])
        scopes = document(node["providers_json"])
        require(
            isinstance(scopes, list) and all(isinstance(item, str) for item in scopes),
            "providers_json must be a list of strings",
        )
        require(len(scopes) == len(set(scopes)), "duplicate provider case")
        original_scopes = [item["provider"] for item in original]
        require(len(original_scopes) == len(set(original_scopes)), "duplicate original node provider")
        require(Counter(scopes) == Counter(original_scopes), "node provider multiplicity differs")
        case_ids = document(node["original_case_ids_json"])
        require(
            isinstance(case_ids, list) and all(isinstance(item, str) for item in case_ids),
            "original_case_ids_json must be a list of strings",
        )
        require(len(case_ids) == len(scopes), "case count differs")
        require(
            list(zip(scopes, case_ids, strict=True))
            == [(case["source"], case["case_id"]) for case in cases_by_id[node["source_id"]]],
            "ordered original provider/case pair differs",
        )
        for item in original:
            source, name, position = item["provider"], item["input"], item["position"]
            require(source in providers and name in originals, "unknown source provider")
            row = originals[name].get(position)
            same_json(row, item["row"], "original provider row differs")
            identifier = row.get("source_id", row.get("placeholder_curie"))
            require(identifier == node["source_id"], "provider source ID differs")
            require(identifier not in providers[source], "duplicate provider/source ID")
            providers[source][identifier] = row
            used[name, position] += 1
    expected = Counter((name, position) for name, rows in originals.items() for position in rows)
    require(used == expected, "original provider table coverage differs")
    return providers


def graph_inventory(inputs, root, historical, providers, nodes, occurrences):
    """Stream all eight complete graphs and retain only selected full-row incidences."""
    markers, members, selected, current_nodes = {}, {}, defaultdict(list), defaultdict(dict)
    for source in SOURCES:
        relative = f"data/transformed/{source}/source_finalization.json"
        marker = inputs.json(root / relative, historical["files"]["snapshots/" + relative])
        require(marker["source"] == source and marker["tsv_quoting"] == "none", "finalization source/dialect differs")
        markers[source] = marker
        selected_ids = set(providers[source])
        for kind in ("nodes", "edges"):
            relative = f"data/transformed/{source}/{kind}.tsv"
            path = inputs.add(root / relative, marker["members"][kind + ".tsv"])
            count = 0
            columns = None
            all_compounds = set()
            for position, row in table(path, graph=True):
                count += 1
                if columns is None:
                    columns = list(row)
                if kind == "nodes":
                    require("id" in row, "graph node ID missing")
                    identifier = row["id"]
                    if identifier.startswith("kgmicrobe.compound:"):
                        all_compounds.add(identifier)
                    if identifier in selected_ids:
                        require(identifier not in current_nodes[source], "duplicate selected graph node")
                        current_nodes[source][identifier] = (position, row)
                else:
                    require({"subject", "predicate", "object"} <= row.keys(), "graph edge columns missing")
                    if source == "mediadive":
                        if row.get("source_assertion_id") in occurrences or (
                            row["object"] in selected_ids and row["predicate"] == "biolink:has_part"
                        ):
                            selected[source].append((position, row))
                    else:
                        for identifier in sorted({row["subject"], row["object"]} & selected_ids):
                            selected[source].append((position, row, identifier))
            require(count == marker["summaries"]["rows"][kind], "finalization graph row count differs")
            require(columns is not None, "empty historical graph")
            members[relative] = {**inputs.before[str(path)], "row_count": count, "columns": columns}
            if kind == "nodes":
                require(set(current_nodes[source]) == selected_ids, "selected graph node coverage differs")
                if source in ("metatraits", "metatraits_gtdb"):
                    require(all_compounds == selected_ids, "complete compound node inventory differs")
    for _, node in nodes:
        entries = document(node["current_graph_node_rows_json"])
        current_scopes = [entry["provider"] for entry in entries]
        require(len(current_scopes) == len(set(current_scopes)), "duplicate current node provider")
        require(
            Counter(current_scopes) == Counter(document(node["providers_json"])),
            "current node provider coverage differs",
        )
        for entry in entries:
            source = entry["provider"]
            position, row = current_nodes[source][node["source_id"]]
            same_json(row, entry["row"], "full current graph node differs")
            require(position == entry["position"], "graph node position differs")
            path = root / f"data/transformed/{source}/nodes.tsv"
            require(entry["input"]["path"] == str(path), "graph node input locator differs")
            inputs.add(path, entry["input"])
    return markers, members, selected


def mediadive_rows(inputs, manifest, marker, providers, graph):
    """Reconstruct every selected raw recipe observation and its exact graph assertion."""
    refs = manifest["inputs"]
    for name, consumed in (
        ("solutions", "mediadive_solutions"),
        ("compounds", "mediadive_compounds"),
        ("generation_manifest", "mediadive_generation_manifest"),
        ("generation_pointer", "mediadive_generation_pointer"),
    ):
        require(
            refs[name]["sha256"] == marker["consumed_inputs"][consumed]["sha256"],
            "MediaDive acquisition binding differs",
        )
        inputs.add(refs[name]["path"], refs[name])
    solutions = inputs.json(refs["solutions"]["path"], refs["solutions"])
    compounds = inputs.json(refs["compounds"]["path"], refs["compounds"])
    for identifier, node in providers.items():
        key = node["raw_compound_id"]
        require(identifier == "mediadive.ingredient:" + key, "compound ID differs")
        require(
            node["raw_record_found"] == "True" and node["raw_source_sha256"] == refs["compounds"]["sha256"],
            "compound authority differs",
        )
        same_json(document(node["raw_record_json"]), compounds[key], "compound raw row differs")
    incoming = defaultdict(list)
    for sid, solution in solutions.items():
        require(
            str(solution["id"]) == sid and isinstance(solution.get("recipe", []), list),
            "solution identity/recipe differs",
        )
        for position, item in enumerate(solution.get("recipe", []), 1):
            if item.get("compound_id") is None and item.get("solution_id") is not None:
                incoming[str(item["solution_id"])].append(
                    {"source_assertion_id": f"mediadive.solution:{sid}#recipe/{position}", "source_record": item}
                )
    expected = {}
    for sid, solution in solutions.items():
        for position, item in enumerate(solution.get("recipe", []), 1):
            identifier = "mediadive.ingredient:" + str(item.get("compound_id"))
            if item.get("compound_id") is None or identifier not in providers:
                continue
            locator = f"mediadive.solution:{sid}#recipe/{position}"
            expected[locator] = (
                identifier,
                position,
                item,
                {
                    "solution_key": sid,
                    "solution_record": solution,
                    "direct_incoming_solution_references": incoming[sid],
                    "scope": (
                        "Every direct raw compound assertion in the admitted solutions; "
                        "incoming references are context, not extra material counts"
                    ),
                },
            )
    graph_by_locator = defaultdict(list)
    for position, row in graph:
        graph_by_locator[row["source_assertion_id"]].append((position, row))
    require(set(expected) == set(graph_by_locator), "MediaDive raw/graph locator coverage differs")
    for locator, rows in graph_by_locator.items():
        require(len(rows) == 1, "duplicate MediaDive graph assertion")
        _, row = rows[0]
        identifier, _, raw, _ = expected[locator]
        require(
            row["subject"] == locator.split("#")[0]
            and row["object"] == identifier
            and row["predicate"] == "biolink:has_part",
            "MediaDive graph relation differs",
        )
        same_json(document(row["source_record"]), raw, "MediaDive full raw source payload differs")
    return expected, graph_by_locator


def microbedecoder_rows(inputs, manifest, marker, providers, root):
    """Verify complete unresolved compounds, original CSV records and all held claims."""
    refs = manifest["inputs"]
    raw = inputs.json(refs["microbedecoder_raw"]["path"], refs["microbedecoder_raw"])
    holds = inputs.json(refs["microbedecoder_holds"]["path"], refs["microbedecoder_holds"])
    proof = inputs.json(refs["microbedecoder_proof"]["path"], refs["microbedecoder_proof"])
    database = marker["consumed_inputs"]["crosswalk_raw"]
    require(
        proof["raw_path"] == database["path"] == str(root / "data/raw/database.csv"), "raw database locator differs"
    )
    require(proof["raw_sha256"] == database["sha256"], "raw database pin differs")
    path = inputs.add(database["path"], database)
    found = set()
    for position, row in table(path, delimiter=",", errors="surrogateescape"):
        if str(position) in raw:
            bound = raw[str(position)]
            same_json(row, bound["raw_row"], "original complete CSV record differs")
            literal = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            digest = hashlib.sha256(literal.encode("utf-8", errors="surrogateescape")).hexdigest()
            require(bound["raw_record_sha256"] == digest, "original CSV record hash differs")
            require(
                bound["source_record"] == f"sha256:{database['sha256']}#record={position}",
                "raw record identity differs",
            )
            found.add(str(position))
    require(found == set(raw), "raw CSV record coverage differs")
    hold_by_key = {}
    for hold in holds:
        key = (hold["source_record"], hold["source_column"], hold["source_literal"])
        require(key not in hold_by_key, "duplicate material hold key")
        require(
            hold["identity_status"] == "unresolved" and hold["identity_approved"] == "false",
            "unreviewed identity promotion",
        )
        ordinal = key[0].rsplit("=", 1)[1]
        require(
            hold in raw[ordinal]["bound_dispositions"]
            and hold["raw_record_sha256"] == raw[ordinal]["raw_record_sha256"],
            "raw record hold differs",
        )
        hold_by_key[key] = hold
    require(
        Counter(compact(h) for r in raw.values() for h in r["bound_dispositions"])
        == Counter(compact(h) for h in holds),
        "complete raw disposition coverage differs",
    )
    require(
        len(raw) == proof["raw_selected_records"] and len(holds) == proof["material_disposition_rows"],
        "raw/hold proof count differs",
    )
    require(proof["graph_sha256"] == marker["members"]["edges.tsv"]["sha256"], "MicrobeDecoder graph proof differs")
    return raw, hold_by_key


def reconcile_occurrences(inputs, root, manifest, providers, occurrences, combined, markers, selected):
    """Join every original occurrence to one full graph row with conserved multiplicity."""
    refs = manifest["inputs"]
    media, media_graph = mediadive_rows(
        inputs, manifest, markers["mediadive"], providers["mediadive"], selected["mediadive"]
    )
    raw, holds = microbedecoder_rows(inputs, manifest, markers["microbedecoder"], providers["microbedecoder"], root)
    subset_ref = refs["microbedecoder_edges"]
    subset = dict(table(inputs.add(subset_ref["path"], subset_ref)))
    graph_queues = defaultdict(deque)
    for source in SOURCES[1:]:
        for position, row, identifier in selected[source]:
            graph_queues[source, identifier, compact(row)].append(position)
    used_media, used_holds, used_subset = set(), set(), set()
    predicates = defaultdict(Counter)
    ledger = []
    for (ordinal, occurrence), (global_row, combined_row) in zip(occurrences, combined, strict=True):
        source, identifier = occurrence["provider"], occurrence["source_id"]
        require(source in SOURCES and identifier in providers[source], "unknown source occurrence")
        full = document(occurrence["source_record_json"])
        context = document(occurrence["context_json"])
        position = int(occurrence["physical_position"])
        require(str(position) == occurrence["physical_position"] and position > 0, "invalid original position")
        locator = occurrence["source_locator"]
        if source == "mediadive":
            require(
                occurrence["kind"] == "raw_solution_recipe" and locator not in used_media,
                "duplicate/wrong MediaDive occurrence",
            )
            require(locator in media, "unbound MediaDive raw occurrence")
            wanted_id, wanted_position, wanted_raw, wanted_context = media[locator]
            require(identifier == wanted_id and position == wanted_position, "MediaDive original coordinate differs")
            same_json(full, wanted_raw, "MediaDive recipe row differs")
            same_json(context, wanted_context, "MediaDive full solution context differs")
            graph_position, graph_row = media_graph[locator][0]
            original = refs["solutions"]
            used_media.add(locator)
        else:
            queue = graph_queues[source, identifier, compact(full)]
            require(queue, "missing/extra full graph row incidence")
            graph_position = queue.popleft()
            graph_row = full
            if source in ("metatraits", "metatraits_gtdb"):
                require(occurrence["kind"] == "incident_graph_edge", "wrong incident graph kind")
                require(
                    position == graph_position and locator == f"rows/{graph_position}",
                    "incident graph coordinate differs",
                )
                same_json(
                    context,
                    {
                        "source_node_row": providers[source][identifier],
                        "incident_roles": [key for key in ("subject", "object") if full[key] == identifier],
                    },
                    "incident roles/full source node differ",
                )
                original = refs[source + "_edges"]
                predicates[source, identifier][full["predicate"]] += 1
            else:
                require(occurrence["kind"] == "material_graph_observation", "wrong material observation kind")
                require(position not in used_subset and position in subset, "subset ordinal duplicated/missing")
                same_json(full, subset[position], "full MicrobeDecoder subset row differs")
                key = (full["source_record"], full["source_column"], full["value"])
                require(key in holds and key not in used_holds, "material hold coverage differs")
                require(locator == "::".join(key), "material source locator differs")
                hold = holds[key]
                for field, hold_field in {
                    "subject": "subject",
                    "object": "object_curie",
                    "predicate": "predicate",
                    "relation": "relation",
                    "source_citation": "source_citation",
                    "primary_knowledge_source": "primary_knowledge_source",
                    "knowledge_level": "knowledge_level",
                    "agent_type": "agent_type",
                    "value_encoding": "value_encoding",
                }.items():
                    require(full[field] == hold[hold_field], "material graph qualifier differs")
                same_json(
                    context,
                    {"raw_record": raw[key[0].rsplit("=", 1)[1]], "original_material_disposition": hold},
                    "full material context differs",
                )
                original = subset_ref
                used_subset.add(position)
                used_holds.add(key)
        require(
            occurrence["original_input"] == original["path"]
            and occurrence["original_input_sha256"] == original["sha256"],
            "original input binding differs",
        )
        inputs.add(original["path"], original)
        graph_relative = f"data/transformed/{source}/edges.tsv"
        ledger.append(
            {
                "provider": source,
                "source_id": identifier,
                "kg_occurrence_row": ordinal,
                "kg_occurrence_row_sha256": row_hash(occurrence),
                "occurrence": occurrence,
                "combined_global_row": global_row,
                "combined_row_sha256": row_hash(combined_row),
                "combined_row": combined_row,
                "graph_member": graph_relative,
                "graph_sha256": markers[source]["members"]["edges.tsv"]["sha256"],
                "graph_row": graph_position,
                "graph_row_sha256": row_hash(graph_row),
                "graph_full_row": graph_row,
            }
        )
    require(
        used_media == set(media) and used_holds == set(holds) and used_subset == set(subset),
        "original occurrence coverage incomplete",
    )
    require(all(not queue for queue in graph_queues.values()), "unaccounted full graph row incidence")
    for source in ("metatraits", "metatraits_gtdb"):
        for identifier, node in providers[source].items():
            require(sum(predicates[source, identifier].values()) == int(node["occurrences"]), "incident count differs")
            same_json(
                dict(predicates[source, identifier]),
                document(node["predicate_counts"]),
                "incident predicate counts differ",
            )
    return ledger


def write_json(path, value):
    """Create one new machine-readable artifact without replacing prior evidence."""
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        handle.write("\n")


@contextmanager
def large_csv_fields():
    """Permit complete source payloads only while restoring the caller's CSV limit."""
    previous = csv.field_size_limit()
    try:
        csv.field_size_limit(100_000_000)
        yield
    finally:
        csv.field_size_limit(previous)


@large_csv_fields()
def reconcile(
    *,
    source_root,
    historical_receipt,
    historical_sha256,
    kg_inputs,
    kg_manifest_sha256,
    combined_inputs,
    combined_manifest_sha256,
    output,
):
    """Prove the fixed historical source cohort and write a new bounded evidence set."""
    inputs = Inputs()
    root = selected_path(source_root)
    historical = inputs.json(historical_receipt, historical_sha256)
    require(str(root) == historical["upstream_root"], "selected KGM root differs")
    revision = _head(root)
    require(revision == historical["upstream_revision"], "historical KGM revision differs")
    kg_inputs, combined_inputs, output = (
        selected_path(kg_inputs),
        selected_path(combined_inputs),
        selected_path(output),
    )
    require(not output.exists(), "output already exists")
    require(not any(parent.is_symlink() for parent in output.parents), "aliased output directory")
    for input_root in (root, kg_inputs, combined_inputs, selected_path(historical_receipt).parent):
        require(not output.is_relative_to(input_root), "output would mutate a source input directory")
    manifest = inputs.json(kg_inputs / "manifest.json", kg_manifest_sha256)
    combined_manifest = inputs.json(combined_inputs / "manifest.json", combined_manifest_sha256)
    for name, digest in manifest["files"].items():
        require(Path(name).name == name, "unsafe KG product member")
        inputs.add(kg_inputs / name, digest)
    original_tables, combined_tables, projections = {}, {}, {}
    for kind in ("nodes", "occurrences"):
        name = f"source-{kind}.tsv"
        original_tables[kind] = list(table(inputs.add(kg_inputs / name, manifest["files"][name])))
        combined_tables[kind] = list(table(inputs.add(combined_inputs / name, combined_manifest["products"][name])))
        label = "kg_" + kind
        frozen = combined_inputs / f"originals/{label}.tsv"
        inputs.add(frozen, manifest["files"][name])
        projections[kind] = projection(original_tables[kind], combined_tables[kind], label, manifest["files"][name])
    nodes, occurrences = original_tables["nodes"], original_tables["occurrences"]
    require(all(tuple(row) == OCC_FIELDS for _, row in occurrences), "original occurrence schema differs")
    providers = provider_nodes(inputs, manifest, nodes)
    observed_counts = {
        "kg_source_ids": len(nodes),
        "provider_cases": sum(map(len, providers.values())),
        "kg_occurrences": len(occurrences),
        "shared_metatraits_gtdb_ids": len(set(providers["metatraits"]) & set(providers["metatraits_gtdb"])),
    }
    require(observed_counts == COUNTS, "historical source cohort differs")
    require(set(providers["metatraits_gtdb"]) <= set(providers["metatraits"]), "GTDB shared IDs differ")
    provider_counts = {
        source: {
            "cases": len(providers[source]),
            "occurrences": sum(row["provider"] == source for _, row in occurrences),
        }
        for source in SOURCES
    }
    require(provider_counts == EXPECTED, "historical provider counts differ")
    media_locators = {row["source_locator"] for _, row in occurrences if row["provider"] == "mediadive"}
    unmapped_relative = "data/transformed/microbedecoder/unmapped_labels.tsv"
    unmapped = list(table(inputs.add(root / unmapped_relative, historical["files"]["snapshots/" + unmapped_relative])))
    inventory = historical["complete_microbedecoder_compound_subset"]
    require(
        inventory["native_helper_prefix"] == "compound" and inventory["native_helper_min_occurrences"] == 0,
        "compound selection policy differs",
    )
    require(len(unmapped) == inventory["input_rows"], "complete unmapped denominator differs")
    compounds = [row for _, row in unmapped if row["placeholder_curie"].startswith("kgmicrobe.compound:")]
    require(
        len(compounds) == inventory["compound_rows"] == len(providers["microbedecoder"]),
        "complete compound subset differs",
    )
    require(len({row["placeholder_curie"] for row in compounds}) == len(compounds), "duplicate unmapped compound")
    require(
        sum(int(row["occurrences"]) < 10 for row in compounds) == inventory["rare_rows_under10"],
        "rare compound subset differs",
    )
    for row in compounds:
        selected_row = providers["microbedecoder"].get(row["placeholder_curie"], {})
        require(
            all(selected_row.get(key) == value for key, value in row.items()), "complete compound source tuple differs"
        )
    markers, members, selected = graph_inventory(inputs, root, historical, providers, nodes, media_locators)
    ledger = reconcile_occurrences(
        inputs, root, manifest, providers, occurrences, projections["occurrences"], markers, selected
    )
    after = inputs.finish()
    require(_head(root) == revision, "historical KGM revision moved")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "full-row-ledger.json", ledger)
    node_ledger = [
        {"kg_node_row": position, "node": node, "combined_global_row": combined_position, "combined_row": combined_row}
        for (position, node), (combined_position, combined_row) in zip(nodes, projections["nodes"], strict=True)
    ]
    write_json(output / "full-node-ledger.json", node_ledger)
    fields = [
        "provider",
        "source_id",
        "kg_occurrence_row",
        "combined_global_row",
        "graph_member",
        "graph_row",
        "kg_occurrence_row_sha256",
        "combined_row_sha256",
        "graph_row_sha256",
        "full_row_json",
    ]
    with (output / "full-row-ledger.tsv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in ledger:
            writer.writerow({**{field: row[field] for field in fields[:-1]}, "full_row_json": compact(row)})
    outputs = {
        name: {
            **fingerprint(output / name),
            "row_count": len(node_ledger) if name == "full-node-ledger.json" else len(ledger),
        }
        for name in ("full-row-ledger.json", "full-row-ledger.tsv", "full-node-ledger.json")
    }
    report = {
        "schema_version": 1,
        "status": "PASS_HISTORICAL_SOURCE_ROW_RECONCILIATION",
        "historical_manifest_sha256": historical_sha256,
        "kgm_root": str(root),
        "kgm_revision": revision,
        "kg_manifest_sha256": kg_manifest_sha256,
        "combined_manifest_sha256": combined_manifest_sha256,
        "selected_sources": list(SOURCES),
        "graph_members": members,
        "counts": observed_counts,
        "provider_counts": provider_counts,
        "all_native_kg_rows_accounted": True,
        "exact_combined_projection": True,
        "all_inputs_unchanged": True,
        "inputs_before": inputs.before,
        "inputs_after": after,
        "outputs": outputs,
        "production_admission": False,
        "scientific_approval": False,
        "scope": (
            "Historical source bytes, complete selected rows and multiplicity; "
            "no current-runtime admission, identity promotion, final MIM certification or release approval."
        ),
    }
    write_json(output / "row-reconciliation.json", report)
    return report


def main():
    """Expose only immutable selectors and an exclusive new evidence directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "source-root",
        "historical-receipt",
        "historical-sha256",
        "kg-inputs",
        "kg-manifest-sha256",
        "combined-inputs",
        "combined-manifest-sha256",
        "output",
    ):
        parser.add_argument("--" + name, required=True)
    args = vars(parser.parse_args())
    for name in ("historical_sha256", "kg_manifest_sha256", "combined_manifest_sha256"):
        require(re.fullmatch(r"[0-9a-f]{64}", args[name]), f"invalid hash selector: {name}")
    report = reconcile(**args)
    print(json.dumps({"status": report["status"], "output": str(Path(args["output"]).absolute())}))


if __name__ == "__main__":
    main()
