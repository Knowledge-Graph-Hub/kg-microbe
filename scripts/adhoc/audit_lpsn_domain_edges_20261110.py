"""
Run bounded offline native LPSN edge canaries for #1843 using preserved real records.

Default is a read-only plan. Explicit execution copies a five-row GSS selection
and its complete cached API closure, then calls both production run() methods.
No source completion or full taxonomy-enrichment claim is made.
"""

import argparse
import csv
import hashlib
import inspect
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from kg_microbe.transform_utils.lpsn.lpsn import LPSNTransform
from kg_microbe.transform_utils.lpsn_api.lpsn_api import LPSNAPITransform

ROOT = Path(__file__).resolve().parents[2]
ROOTS = {"18880", "10674", "10543", "5244", "517058"}
MAX_CACHE_RECORDS = 30


class UnexpectedNetwork(BaseException):
    """Abort the canary even inside broad native per-record exception handlers."""


def reject_network(*args, **kwargs):
    """Prevent API, web, authentication and direct socket requests in this offline canary."""
    raise UnexpectedNetwork("Offline LPSN canary attempted a network operation")


class CacheOnlyClient:
    """Require every requested API record to be served from its preserved local bytes."""

    search = staticmethod(reject_network)
    retrieve = staticmethod(reject_network)


class DisabledTaxonomyMatches:
    """Scope this native-edge canary away from unrelated NCBI/GTDB label matching."""

    def curies_by_label(self, label):
        """Provide no inferred NCBI name matches; this is disclosed in the receipt."""
        return []

    def curies_by_rank_name(self, rank, name):
        """Provide no inferred GTDB matches; existing focused tests cover that contract."""
        return []


def identity(path):
    """Hash selected files without loading an entire graph or raw CSV into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.absolute()), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def read_rows(path):
    """Read only the bounded canary's emitted TSVs with the native TSV dialect."""
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def source_selection(gss, cache):
    """Preserve complete GSS cells and require the entire finite native linked cache closure."""
    with gss.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = [row for row in reader if row["record_no"] in ROOTS]
    if len(rows) != len(ROOTS) or {row["record_no"] for row in rows} != ROOTS:
        raise ValueError("Real GSS canary cohort missing or duplicated")
    queue, records, inputs = sorted(ROOTS), {}, {str(gss): identity(gss)}
    while queue:
        record_no = queue.pop(0)
        if record_no in records:
            continue
        if len(records) >= MAX_CACHE_RECORDS:
            raise ValueError("Canary cache closure exceeded its finite bound")
        path = cache / f"{record_no}.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("Canary requires bounded, present, regular native cache records")
        before = identity(path)
        value = json.loads(path.read_text())
        if type(value.get("id")) not in (str, int) or str(value["id"]) != record_no:
            raise ValueError("Native cache record identity mismatch")
        if identity(path) != before:
            raise ValueError("Native cache record changed while reading")
        inputs[str(path)] = before
        records[record_no] = value
        for key in ("lpsn_parent_id", "basonym_id"):
            target = str(value.get(key) or "").strip()
            if target.isdigit() and target != record_no:
                queue.append(target)
    return fields, rows, records, inputs


def verify_edges(gss_edges, api_edges, records):
    """Independently reconstruct native API triples and compare all emitted occurrences."""
    gss_triples = {(r["subject"], r["predicate"], r["object"]) for r in gss_edges}
    expected, overlapping = [], set()
    for record_no, record in records.items():
        taxon = f"lpsn:{record_no}"
        for key, predicate in (("lpsn_parent_id", "biolink:subclass_of"), ("basonym_id", "biolink:same_as")):
            target = str(record.get(key) or "").strip()
            if target.isdigit() and target != record_no:
                triple = (taxon, predicate, f"lpsn:{target}")
                if triple in gss_triples:
                    overlapping.add(triple)
                else:
                    expected.append(triple)
        if record_no not in ROOTS:
            continue  # Native linked-record traversal emits hierarchy, not root enrichment fields.
        for key, prefix in (("publication_doi", "doi:"), ("ijsem_list_doi", "doi:"), ("publication_pmid", "PMID:")):
            value = str(record.get(key) or "").strip()
            if value:
                expected.append((prefix + value, "biolink:mentions", taxon))
        accessions = {
            str(item.get("identifier") or "").strip()
            for item in record.get("molecules") or []
            if str(item.get("database") or "").strip().lower().startswith("insdc-nucleotide")
        }
        expected.extend(("INSDC:" + accession, "biolink:in_taxon", taxon) for accession in accessions if accession)
    actual = Counter((r["subject"], r["predicate"], r["object"]) for r in api_edges)
    if actual != Counter(expected) or set(actual) & gss_triples or not overlapping:
        raise ValueError("Native API edge reconstruction or actual GSS overlap mismatch")
    relations = {
        "biolink:mentions": "IAO:0000142",
        "biolink:in_taxon": "RO:0002162",
        "biolink:subclass_of": "rdfs:subClassOf",
        "biolink:same_as": "skos:exactMatch",
    }
    for row in gss_edges + api_edges:
        if (
            row["relation"] != relations[row["predicate"]]
            or row["knowledge_level"] != "knowledge_assertion"
            or row["agent_type"] != "manual_agent"
            or row["primary_knowledge_source"] != "infores:lpsn"
        ):
            raise ValueError("Native edge predicate/relation/provenance mismatch")
    # Fixed source-native controls distinguish the old name, basionym and higher parent.
    required_gss = {
        ("kgmicrobe.strain:JCM-33998", "biolink:in_taxon", "lpsn:18880"),
        ("kgmicrobe.strain:KCTC-25006", "biolink:in_taxon", "lpsn:18880"),
        ("lpsn:5244", "biolink:same_as", "lpsn:10674"),
    }
    expected_gss = required_gss | {
        ("kgmicrobe.strain:LMG-31064", "biolink:in_taxon", "lpsn:10674"),
        ("kgmicrobe.strain:LMG-31064", "biolink:in_taxon", "lpsn:5244"),
        ("lpsn:18880", "biolink:subclass_of", "lpsn:10543"),
        ("lpsn:10674", "biolink:subclass_of", "lpsn:10543"),
        ("lpsn:5244", "biolink:subclass_of", "lpsn:517058"),
    }
    if Counter((r["subject"], r["predicate"], r["object"]) for r in gss_edges) != Counter(expected_gss):
        raise ValueError("Real GSS type-deposit, hierarchy or historical-name control changed")
    if ("lpsn:10674", "biolink:same_as", "lpsn:5244") not in actual:
        raise ValueError("Distinct native API basionym direction was suppressed")
    if ("lpsn:10543", "biolink:subclass_of", "lpsn:728") not in actual:
        raise ValueError("API-only family parent was lost")
    return sorted(overlapping)


def main():
    """Plan or execute exactly one independent, preserved native-edge canary pair."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gss", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    args.gss, args.cache, args.output = args.gss.absolute(), args.cache.absolute(), args.output.absolute()
    allowed = ROOT / "data/edge-quality-20261110"
    if not args.output.resolve().is_relative_to(allowed.resolve()) or args.output.is_symlink() or args.output.exists():
        raise ValueError("Canary output must be a fresh owned evidence subdirectory")
    fields, rows, records, inputs = source_selection(args.gss, args.cache)
    code = [Path(__file__).resolve(), *(Path(inspect.getfile(cls)) for cls in (LPSNTransform, LPSNAPITransform))]
    code.extend(
        ROOT / relative
        for relative in (
            "kg_microbe/transform_utils/lpsn_api/native_inputs.py",
            "kg_microbe/transform_utils/constants.py",
            "kg_microbe/transform_utils/transform.py",
        )
    )
    if any(not path.resolve().is_relative_to(ROOT) for path in code):
        raise ValueError("Canary imported a producer outside the owned checkout")
    inputs.update({str(path): identity(path) for path in code})
    if not args.execute:
        print(
            json.dumps({"execute": False, "roots": sorted(ROOTS), "cached_records": sorted(records), "inputs": inputs})
        )
        return
    args.output.mkdir(parents=True, exist_ok=False)
    raw, transformed = args.output / "raw", args.output / "transformed"
    local_cache = raw / "lpsn/api_cache"
    local_cache.mkdir(parents=True)
    selected_csv = raw / "lpsn_gss.csv"
    with selected_csv.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    for record_no in records:
        source = args.cache / f"{record_no}.json"
        target = local_cache / source.name
        with target.open("xb") as handle:
            handle.write(source.read_bytes())
        if identity(target)["sha256"] != inputs[str(source)]["sha256"]:
            raise ValueError("Native cache copy changed")
    with (args.output / "selection.json").open("x") as handle:
        json.dump(
            {"original_inputs": inputs, "gss_complete_rows": rows, "selected_csv": identity(selected_csv)},
            handle,
            indent=2,
        )
    lookup = DisabledTaxonomyMatches()
    gss = LPSNTransform(input_dir=raw, output_dir=transformed, ncbi_impl=lookup, gtdb_index=lookup)
    api = LPSNAPITransform(input_dir=raw, output_dir=transformed, client=CacheOnlyClient(), page_fetch=reject_network)
    with patch("requests.sessions.Session.request", reject_network), patch("socket.socket.connect", reject_network):
        gss.run(show_status=False)
        gss.verify_consumed_inputs()
        api.run(show_status=False)
        api.verify_consumed_inputs()
    if (
        api._stats["fetched"]
        or api._stats["errors"]
        or api._stats["api_misses"]
        or api._stats["from_cache"] != len(records)
    ):
        raise ValueError("Canary did not consume only the complete preserved native cache closure")
    gss_edges, api_edges = read_rows(gss.output_edge_file), read_rows(api.output_edge_file)
    overlap = verify_edges(gss_edges, api_edges, records)
    for path, before in inputs.items():
        if identity(Path(path)) != before:
            raise ValueError("Original source or producer code changed during canary")
    for record_no in records:
        if (
            identity(local_cache / f"{record_no}.json")["sha256"]
            != inputs[str(args.cache / f"{record_no}.json")]["sha256"]
        ):
            raise ValueError("Selected native cache changed during canary")
    outputs = {str(path.relative_to(args.output)): identity(path) for path in sorted(transformed.rglob("*.tsv"))}
    receipt = {
        "status": "pass_bounded_native_lpsn_edges",
        "source_completed": False,
        "full_admission": False,
        "network_calls": 0,
        "gss_rows": len(rows),
        "cached_api_records": len(records),
        "gss_nodes": len(read_rows(gss.output_node_file)),
        "gss_edges": len(gss_edges),
        "api_nodes": len(read_rows(api.output_node_file)),
        "api_edges": len(api_edges),
        "suppressed_actual_gss_triples": overlap,
        "remaining_cross_source_triples": 0,
        "api_stats": api._stats,
        "native_contract": api.producer_native_inputs,
        "consumed_inputs": api.consumed_input_snapshots,
        "outputs": outputs,
        "original_inputs": inputs,
        "limitations": [
            "Five exact native GSS rows, not a full source rebuild.",
            "NCBI/GTDB enrichment explicitly disabled through existing injected lookup interfaces.",
            "Native run() methods and input guards exercised; dispatcher/finalization not claimed.",
        ],
    }
    with (args.output / "receipt.json").open("x") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({key: receipt[key] for key in ("status", "gss_nodes", "gss_edges", "api_nodes", "api_edges")}))


if __name__ == "__main__":
    main()
