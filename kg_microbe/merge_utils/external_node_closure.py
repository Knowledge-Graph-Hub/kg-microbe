"""
Evidence-backed closure for referenced external nodes missing from source declarations.

Only anonymous endpoints are considered. Retired identifiers use explicit
authority replacements; unsupported obsolete assertions follow the ontology
transform's exclusion policy and are retained verbatim in a disposition TSV.
No name matching, accession-prefix substitution, or taxonomy inference occurs.
"""

import csv
import hashlib
import json
import sqlite3
import tarfile
from array import array
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from lxml import etree

from kg_microbe.transform_utils.constants import (
    BIOLOGICAL_PROCESS_CATEGORY,
    CATEGORY_COLUMN,
    CELLULAR_COMPONENT_CATEGORY,
    DESCRIPTION_COLUMN,
    ID_COLUMN,
    MOLECULAR_ACTIVITY_CATEGORY,
    NAME_COLUMN,
    NCBI_CATEGORY,
    OBJECT_COLUMN,
    PROVIDED_BY_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.atomic_io import atomic_write
from kg_microbe.utils.external_identifiers import load_taxid_merges, resolve_replacement
from kg_microbe.utils.ontology_resolution import chebi_category
from kg_microbe.utils.provenance import knowledge_source_tokens, serialize_knowledge_sources
from kg_microbe.utils.tsv_io import tsv_dict_writer

_SUPPORTED = ("NCBITaxon:", "GO:", "CHEBI:", "MICRO:", "OBI:", "gold:")
_RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
_LABEL = "{http://www.w3.org/2000/01/rdf-schema#}label"
_REPORT_HEADER = [
    "original_id",
    "canonical_id",
    "disposition",
    "authority",
    "authority_sha256",
    "original_edge_json",
    "original_node_json",
]
# Finite, reviewed source identities. A cache filename is not an information
# resource identifier (in particular, there is no invented infores:taxdump).
_AUTHORITY_SOURCES = {
    "taxdump.tar.gz": "infores:ncbitaxon",
    "go.db": "infores:go",
    "chebi.db": "infores:chebi",
    "micro.owl": "infores:micro",
    "metpo.owl": "infores:metpo",
    "gold/GOLD_nodes.tsv": "infores:gold",
}


def _rows(path, quoting=csv.QUOTE_MINIMAL):
    """Stream a KGX TSV or ordered source bundle with header-aware quoted-field handling."""
    if isinstance(path, (list, tuple)):
        for member in path:
            yield from _rows(member, quoting=quoting)
        return
    with Path(path).open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle, delimiter="\t", quoting=quoting)


def _digest(path):
    """Fingerprint actual local authority bytes without buffering the file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _taxdump_records(path, wanted):
    """Read exact scientific labels and prokaryote membership from NCBI's parent tree."""
    parents = array("I", [0])
    records = {}
    with tarfile.open(path) as archive:
        for raw in archive.extractfile("nodes.dmp"):
            fields = [part.strip() for part in raw.decode("utf-8").split("|")]
            taxid, parent = int(fields[0]), int(fields[1])
            if taxid >= len(parents):
                parents.extend(array("I", [0]) * (taxid + 1 - len(parents)))
            parents[taxid] = parent
            if fields[0] in wanted:
                records[fields[0]] = {"rank": fields[2]}
        for raw in archive.extractfile("names.dmp"):
            fields = [part.strip() for part in raw.decode("utf-8").split("|")]
            if fields[0] in records and fields[3] == "scientific name":
                records[fields[0]]["name"] = fields[1]
    for taxid, record in records.items():
        current, seen = int(taxid), set()
        while True:
            if current <= 0 or current >= len(parents) or not parents[current]:
                raise ValueError(f"{path}: incomplete NCBI lineage at {taxid}: missing node {current}")
            if current in (1, 2, 2157):
                break
            if current in seen:
                raise ValueError(f"{path}: cyclic NCBI lineage at {taxid}")
            seen.add(current)
            current = parents[current]
        record["prokaryote"] = current in (2, 2157)
    return records


def _ontology_record(connection, identifier):
    """Fetch only exact subject annotations from the local untrimmed SemSQL authority."""
    values = {}
    query = "SELECT predicate, object, value FROM statements WHERE subject=?"
    for predicate, obj, value in connection.execute(query, (identifier,)):
        if predicate in ("rdfs:label", "owl:deprecated", "IAO:0100001", "oboInOwl:hasOBONamespace"):
            values.setdefault(predicate, set()).add(obj or value or "")
    return values


class _AssertedSubclassAdapter:
    """Expose only asserted SemSQL subclass ancestry to the shared ChEBI policy."""

    def __init__(self, connection):
        """Use the already opened read-only local authority connection."""
        self.connection = connection

    def ancestors(self, term_id, predicates):
        """Follow is-a edges, excluding chemical-role links and other relations."""
        if predicates != ["rdfs:subClassOf"]:
            raise ValueError("External ChEBI classification requires asserted subclass ancestry")
        query = """
            WITH RECURSIVE ancestor(id) AS (
                SELECT object FROM statements
                WHERE subject=? AND predicate='rdfs:subClassOf' AND object IS NOT NULL
                UNION
                SELECT statement.object FROM statements AS statement
                JOIN ancestor ON statement.subject=ancestor.id
                WHERE statement.predicate='rdfs:subClassOf' AND statement.object IS NOT NULL
            )
            SELECT id FROM ancestor
        """
        return (row[0] for row in self.connection.execute(query, (term_id,)))


def _ontology_decisions(raw_dir, prefix, targets, decisions, authorities):
    """Resolve only unique explicit replacement chains; mark obsolete unsupported references."""
    path = raw_dir / f"{prefix.lower()}.db"
    if not path.is_file():
        return
    authorities[path.name] = _digest(path)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        for original in targets:
            current, seen = original, set()
            while True:
                if current in seen:
                    raise ValueError(f"{path}: cyclic replacement for {original}")
                seen.add(current)
                record = _ontology_record(connection, current)
                deprecated = "true" in record.get("owl:deprecated", set())
                replacement = record.get("IAO:0100001", set())
                if deprecated and len(replacement) == 1:
                    current = next(iter(replacement))
                    if not current.startswith(f"{prefix}:"):
                        raise ValueError(f"{path}: cross-namespace replacement {original} -> {current}")
                    continue
                if deprecated:
                    decisions[original] = {
                        "canonical_id": "",
                        "disposition": "excluded_obsolete_without_unique_replacement",
                        "authority": path.name,
                        "name": next(iter(sorted(record.get("rdfs:label", set()))), ""),
                    }
                    break
                labels = record.get("rdfs:label", set())
                if len(labels) == 1:
                    namespace = record.get("oboInOwl:hasOBONamespace", set())
                    aspects = {
                        "molecular_function": MOLECULAR_ACTIVITY_CATEGORY,
                        "biological_process": BIOLOGICAL_PROCESS_CATEGORY,
                        "cellular_component": CELLULAR_COMPONENT_CATEGORY,
                    }
                    category = next(
                        (aspects[value] for value in sorted(namespace) if value in aspects), "biolink:OntologyClass"
                    )
                    if prefix == "CHEBI":
                        category = chebi_category(current, _AssertedSubclassAdapter(connection))
                    decisions[original] = {
                        "canonical_id": current,
                        "disposition": "retired_id_replaced" if current != original else "authority_declaration",
                        "authority": path.name,
                        "name": next(iter(labels)),
                        "category": category,
                    }
                break


def _local_declarations(raw_dir, targets, decisions, authorities):
    """Recover exact locally present MICRO/GOLD declarations, not a prefix-wide stub policy."""
    # This is the reviewed BacDive assay root, not a MICRO prefix-wide typing
    # rule: MICRO also contains chemicals, qualities and other nonprocedures.
    micro = targets & {"MICRO:0000903"}
    path = raw_dir / "micro.owl"
    if micro and path.is_file():
        authorities[path.name] = _digest(path)
        for _, element in etree.iterparse(
            str(path),
            events=("end",),
            tag="{http://www.w3.org/2002/07/owl#}Class",
            resolve_entities=True,
            no_network=True,
        ):
            iri = element.get(_RDF_ABOUT, "")
            curie = iri.rsplit("/", 1)[-1].replace("MICRO_", "MICRO:")
            if curie in micro:
                label = element.findtext(_LABEL)
                if label:
                    decisions[curie] = {
                        "canonical_id": curie,
                        "name": label,
                        "category": "biolink:Procedure",
                        "disposition": "authority_declaration",
                        "authority": path.name,
                    }
            element.clear()
    # The local METPO release explicitly supplies this foreign class's label
    # in its growth-medium definition. Do not generalize this one reviewed
    # assertion into an arbitrary OBI prefix category/name fallback.
    path = raw_dir / "metpo.owl"
    if "OBI:0000079" in targets and path.is_file():
        text = path.read_text(encoding="utf-8")
        if "OBI:0000079 &apos;culture medium&apos;" in text or "OBI:0000079 'culture medium'" in text:
            authorities[path.name] = _digest(path)
            decisions["OBI:0000079"] = {
                "canonical_id": "OBI:0000079",
                "name": "culture medium",
                "category": "biolink:ChemicalMixture",
                "disposition": "authority_declaration",
                "authority": path.name,
            }
    gold = {curie for curie in targets if curie.startswith("gold:")}
    path = raw_dir / "gold" / "GOLD_nodes.tsv"
    if gold and path.is_file():
        authorities["gold/GOLD_nodes.tsv"] = _digest(path)
        # Restore only a named organism whose exact taxon is demonstrably
        # bacterial/archaeal. Other GOLD trims (samples, studies, eukaryotes)
        # remain in force.
        candidates = {
            row[ID_COLUMN]: row
            for row in _rows(path)
            if row[ID_COLUMN] in gold
            and row.get(NAME_COLUMN)
            and row.get(CATEGORY_COLUMN) == "biolink:IndividualOrganism"
        }
        taxids = {
            row.get("xref", "").removeprefix("NCBITaxon:")
            for row in candidates.values()
            if row.get("xref", "").startswith("NCBITaxon:")
        }
        taxdump = raw_dir / "taxdump.tar.gz"
        records = _taxdump_records(taxdump, taxids) if taxids and taxdump.is_file() else {}
        if records:
            authorities[taxdump.name] = _digest(taxdump)
        for curie, row in candidates.items():
            taxid = row.get("xref", "").removeprefix("NCBITaxon:")
            if records.get(taxid, {}).get("prokaryote"):
                decisions[curie] = {
                    "canonical_id": curie,
                    "name": row[NAME_COLUMN],
                    "category": NCBI_CATEGORY,
                    "disposition": "authority_declaration",
                    "authority": "gold/GOLD_nodes.tsv",
                }


def resolve_external_references(nodes_path, edges_path, raw_dir, report_path):
    """
    Normalize anonymous external references using exact local proof and retain full evidence.

    Return disposition counts. Files are replaced atomically only after all
    authority reads and output writes succeed; failures propagate to prevent
    publishing an apparently successful, partially repaired archive. The
    compatibility caller supplies unpublished staging files. The production
    pipeline invokes the bundle API during source finalization, not merge.
    """
    return resolve_external_reference_bundle([nodes_path], [edges_path], raw_dir, report_path)


def resolve_external_reference_bundle(
    node_paths,
    edge_paths,
    raw_dir,
    report_path,
    *,
    discover_references=False,
    include_go=True,
    strict=False,
    quoting=csv.QUOTE_MINIMAL,
    known_declarations=frozenset(),
    consumed_authorities=None,
):
    """
    Resolve one staged source bundle, preserving file membership and every original assertion.

    The single-pair compatibility API retains its existing anonymous-node
    behavior. Source finalization additionally discovers referenced external
    IDs not declared locally: KGX must no longer invent those nodes before
    authority normalization can see them. GO is handled by its all-ID source
    authority normalizer when ``include_go`` is false. No adapters are created
    in pool workers; callers invoke this after producer workers have completed.
    """
    node_paths, edge_paths = [Path(path) for path in node_paths], [Path(path) for path in edge_paths]
    raw_dir, report_path = Path(raw_dir), Path(report_path)
    if not node_paths or not edge_paths:
        raise ValueError("External reference finalization requires node and edge files")
    supported = _SUPPORTED if include_go else tuple(prefix for prefix in _SUPPORTED if prefix != "GO:")
    original_nodes, original_node_rows, declared = {}, {}, set()
    for row in _rows(node_paths, quoting=quoting):
        identifier = row[ID_COLUMN]
        declared.add(identifier)
        if (
            identifier.startswith(supported)
            and identifier not in known_declarations
            and not row.get(NAME_COLUMN)
            and row.get(CATEGORY_COLUMN) in ("", "biolink:NamedThing")
        ):
            original_nodes.setdefault(identifier, row)
            original_node_rows.setdefault(identifier, []).append(row)
    if discover_references:
        for row in _rows(edge_paths, quoting=quoting):
            for column in (SUBJECT_COLUMN, OBJECT_COLUMN):
                identifier = row[column]
                if (
                    identifier.startswith(supported)
                    and identifier not in declared
                    and identifier not in known_declarations
                ):
                    original_nodes.setdefault(identifier, {ID_COLUMN: identifier})
    targets = set(original_nodes)
    if not targets:
        with atomic_write(report_path, encoding="utf-8", newline="") as output:
            tsv_dict_writer(output, fieldnames=_REPORT_HEADER).writeheader()
        return {}
    decisions, authorities = {}, {}
    ncbi = {curie for curie in targets if curie.startswith("NCBITaxon:")}
    taxdump = raw_dir / "taxdump.tar.gz"
    if strict and ncbi and not taxdump.is_file():
        raise FileNotFoundError(f"Required NCBI authority is missing: {taxdump}")
    if ncbi and taxdump.is_file():
        authorities[taxdump.name] = _digest(taxdump)
        merges = load_taxid_merges(raw_dir)
        requested = {resolve_replacement(curie.removeprefix("NCBITaxon:"), merges) for curie in ncbi}
        records = _taxdump_records(taxdump, requested)
        for original in ncbi:
            taxid = resolve_replacement(original.removeprefix("NCBITaxon:"), merges)
            record = records.get(taxid, {})
            if not record.get("name"):
                continue
            canonical = f"NCBITaxon:{taxid}"
            disposition = "retired_id_replaced" if canonical != original else "authority_declaration"
            if not record["prokaryote"]:
                canonical, disposition = "", "excluded_outside_prokaryote_trim"
            decisions[original] = {
                "canonical_id": canonical,
                "name": record["name"],
                "category": NCBI_CATEGORY,
                "disposition": disposition,
                "authority": taxdump.name,
            }
    for prefix in ("GO", "CHEBI"):
        selected = {curie for curie in targets if curie.startswith(f"{prefix}:")}
        if selected:
            if strict and not (raw_dir / f"{prefix.lower()}.db").is_file():
                raise FileNotFoundError(f"Required {prefix} authority is missing from {raw_dir}")
            _ontology_decisions(raw_dir, prefix, selected, decisions, authorities)
    if strict:
        required_local = []
        if "MICRO:0000903" in targets:
            required_local.append(raw_dir / "micro.owl")
        if "OBI:0000079" in targets:
            required_local.append(raw_dir / "metpo.owl")
        if any(identifier.startswith("gold:") for identifier in targets):
            required_local.append(raw_dir / "gold" / "GOLD_nodes.tsv")
            required_local.append(raw_dir / "taxdump.tar.gz")
        for path in required_local:
            if not path.is_file():
                raise FileNotFoundError(f"Required local reference authority is missing: {path}")
    _local_declarations(raw_dir, targets, decisions, authorities)
    if consumed_authorities is not None:
        consumed_authorities.update(raw_dir / name for name in authorities)
    for identifier in targets - decisions.keys():
        decisions[identifier] = {
            "canonical_id": identifier,
            "disposition": "unresolved_no_exact_local_authority",
            "authority": "",
        }
    replacements = {old: value["canonical_id"] for old, value in decisions.items() if value["canonical_id"] != old}
    canonical_ids = {value["canonical_id"] for value in decisions.values()} - {""}
    existing = {
        row[ID_COLUMN]
        for row in _rows(node_paths, quoting=quoting)
        if row[ID_COLUMN] in canonical_ids and row.get(NAME_COLUMN)
    }
    # Anonymous donors may converge on a declaration already in the graph.
    # Preserve their provenance and descriptive context without copying stale
    # scalar metadata (e.g. a retired node's deprecated flag) onto that node.
    # The disposition report retains every donor's exact original fields.
    enrichment = {}
    for original, decision in decisions.items():
        if not decision.get("name") or not decision["canonical_id"]:
            continue
        details = enrichment.setdefault(decision["canonical_id"], {"providers": set(), "descriptions": set()})
        for original_row in original_node_rows.get(original, [original_nodes[original]]):
            details["providers"].update(knowledge_source_tokens(original_row.get(PROVIDED_BY_COLUMN)))
            description = original_row.get(DESCRIPTION_COLUMN)
            if description:
                details["descriptions"].add(description)
        details["providers"].add(_AUTHORITY_SOURCES[decision["authority"]])
    counts = Counter(value["disposition"] for value in decisions.values())
    # Nested atomic contexts stage all outputs before any replacement. Merge
    # publication is a separate outer boundary; no claim of multi-file rename
    # atomicity is made if the filesystem itself fails during final renames.
    with ExitStack() as stack:
        report_output = stack.enter_context(atomic_write(report_path, encoding="utf-8", newline=""))
        report_writer = tsv_dict_writer(report_output, fieldnames=_REPORT_HEADER)
        report_writer.writeheader()

        def normalized_node(row, node_header):
            """Normalize a single declaration; preserve its source file unless it converges."""
            original = row[ID_COLUMN]
            decision = decisions.get(original)
            if decision:
                canonical = decision["canonical_id"]
                if not canonical:
                    return None
                if canonical in existing:
                    # A donor and a named declaration can share one ID across
                    # source files. Only discard the anonymous donor, never
                    # the named row which receives its provenance below.
                    if original != canonical or not row.get(NAME_COLUMN):
                        return None
                elif decision.get("name"):
                    row = {column: "" for column in node_header}
                    row[ID_COLUMN] = canonical
                    row[NAME_COLUMN] = decision["name"]
                    row[CATEGORY_COLUMN] = decision["category"]
                    if DESCRIPTION_COLUMN in row:
                        row[DESCRIPTION_COLUMN] = (
                            f"Referenced external node declared from {decision['authority']}; "
                            f"{decision['disposition']}."
                        )
                    existing.add(canonical)
            details = enrichment.get(row[ID_COLUMN])
            if details:
                row[PROVIDED_BY_COLUMN] = serialize_knowledge_sources(
                    row.get(PROVIDED_BY_COLUMN), sorted(details["providers"])
                )
                if DESCRIPTION_COLUMN in row:
                    descriptions = [row[DESCRIPTION_COLUMN]] if row[DESCRIPTION_COLUMN] else []
                    descriptions.extend(value for value in sorted(details["descriptions"]) if value not in descriptions)
                    row[DESCRIPTION_COLUMN] = " ".join(descriptions)
            return row

        node_writers = []
        for nodes_path in node_paths:
            with nodes_path.open(encoding="utf-8", newline="") as source:
                node_header = next(csv.reader(source, delimiter="\t"))
            node_output = stack.enter_context(atomic_write(nodes_path, encoding="utf-8", newline=""))
            node_writer = tsv_dict_writer(
                node_output,
                fieldnames=node_header,
                quoting=quoting,
                quotechar=None if quoting == csv.QUOTE_NONE else '"',
            )
            node_writer.writeheader()
            node_writers.append((node_writer, node_header))
            for row in _rows(nodes_path, quoting=quoting):
                normalized = normalized_node(row, node_header)
                if normalized is not None:
                    node_writer.writerow(normalized)
        # References missing from the producer's node files have no original
        # node row to rewrite. Declare only authority-supported identities in
        # the first supplied node file, which is already a configured input.
        node_writer, node_header = node_writers[0]
        for identifier in sorted(targets - declared):
            if not decisions[identifier].get("name"):
                continue
            row = {column: "" for column in node_header}
            row[ID_COLUMN] = identifier
            normalized = normalized_node(row, node_header)
            if normalized is not None:
                node_writer.writerow(normalized)
        reported = set()
        for edges_path in edge_paths:
            with edges_path.open(encoding="utf-8", newline="") as source:
                edge_header = next(csv.reader(source, delimiter="\t"))
            edge_header = list(dict.fromkeys([*edge_header, "original_subject", "original_object"]))
            edge_output = stack.enter_context(atomic_write(edges_path, encoding="utf-8", newline=""))
            edge_writer = tsv_dict_writer(
                edge_output,
                fieldnames=edge_header,
                quoting=quoting,
                quotechar=None if quoting == csv.QUOTE_NONE else '"',
            )
            edge_writer.writeheader()
            _write_resolved_edges(
                edges_path,
                edge_writer,
                edge_header,
                report_writer,
                decisions,
                authorities,
                original_node_rows,
                replacements,
                reported,
                quoting,
            )
        for original in sorted(decisions.keys() - reported):
            decision = decisions[original]
            for node_row in original_node_rows.get(original, [None]):
                report_writer.writerow(
                    {
                        "original_id": original,
                        "canonical_id": decision["canonical_id"],
                        "disposition": decision["disposition"],
                        "authority": decision["authority"],
                        "authority_sha256": authorities.get(decision["authority"], ""),
                        "original_edge_json": "",
                        "original_node_json": json.dumps(node_row, sort_keys=True) if node_row is not None else "",
                    }
                )
    return dict(counts)


def _write_resolved_edges(
    edges_path,
    edge_writer,
    edge_header,
    report_writer,
    decisions,
    authorities,
    original_node_rows,
    replacements,
    reported,
    quoting,
):
    """Apply already validated bundle decisions without pooling source assertions."""
    seen_affected = set()
    for row in _rows(edges_path, quoting=quoting):
        changed = [value for value in (row[SUBJECT_COLUMN], row[OBJECT_COLUMN]) if value in decisions]
        original_row = dict(row)
        for original in dict.fromkeys(changed):
            decision = decisions[original]
            for node_row in original_node_rows.get(original, [None]):
                report_writer.writerow(
                    {
                        "original_id": original,
                        "canonical_id": decision["canonical_id"],
                        "disposition": decision["disposition"],
                        "authority": decision["authority"],
                        "authority_sha256": authorities.get(decision["authority"], ""),
                        "original_edge_json": json.dumps(original_row, sort_keys=True),
                        "original_node_json": json.dumps(node_row, sort_keys=True) if node_row is not None else "",
                    }
                )
            reported.add(original)
        excluded = False
        for column in (SUBJECT_COLUMN, OBJECT_COLUMN):
            original = row[column]
            if original in replacements:
                canonical = replacements[original]
                if not canonical:
                    excluded = True
                    break
                row[f"original_{column}"] = row.get(f"original_{column}") or original
                row[column] = canonical
        if excluded:
            continue
        if changed:
            key = tuple(row.get(column, "") for column in edge_header)
            if key in seen_affected:
                continue
            seen_affected.add(key)
        edge_writer.writerow(row)
