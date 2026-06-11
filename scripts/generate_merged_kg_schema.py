#!/usr/bin/env python
"""
Generate a LinkML schema for a KG-Microbe merged KG (KGX node/edge TSVs).

Streams the merged ``*_nodes.tsv`` and ``*_edges.tsv`` once each to collect the
controlled-vocabulary columns (node ``category``; edge ``predicate``,
``knowledge_level``, ``agent_type``) and emits a schema with ``Node``, ``Edge``
and a ``KnowledgeGraph`` container, plus enums populated from the observed
values. Columns with open/heterogeneous values (``primary_knowledge_source``,
``relation``, ``unit``, free-text fields) are typed as strings rather than
enums.

Usage::

    python scripts/generate_merged_kg_schema.py \
        --merged-dir data/merged/20260610 \
        --output schema/kg_microbe_merged.yaml
"""

import argparse
import csv
import glob
import sys
from collections import Counter
from pathlib import Path

import yaml

# CURIE prefix -> expansion for prefixes seen in node IDs / categories / predicates.
PREFIXES = {
    "linkml": "https://w3id.org/linkml/",
    "biolink": "https://w3id.org/biolink/vocab/",
    "METPO": "https://w3id.org/metpo/",
    "NCBITaxon": "http://purl.obolibrary.org/obo/NCBITaxon_",
    "CHEBI": "http://purl.obolibrary.org/obo/CHEBI_",
    "GO": "http://purl.obolibrary.org/obo/GO_",
    "ENVO": "http://purl.obolibrary.org/obo/ENVO_",
    "UBERON": "http://purl.obolibrary.org/obo/UBERON_",
    "PATO": "http://purl.obolibrary.org/obo/PATO_",
    "FOODON": "http://purl.obolibrary.org/obo/FOODON_",
    "NCIT": "http://purl.obolibrary.org/obo/NCIT_",
    "PO": "http://purl.obolibrary.org/obo/PO_",
    "RO": "http://purl.obolibrary.org/obo/RO_",
    "IAO": "http://purl.obolibrary.org/obo/IAO_",
    "TAXRANK": "http://purl.obolibrary.org/obo/TAXRANK_",
    "MICRO": "http://purl.obolibrary.org/obo/MICRO_",
    "UPA": "http://purl.obolibrary.org/obo/UPa_",
    "OBO": "http://purl.obolibrary.org/obo/",
    "EC": "https://bioregistry.io/ec:",
    "RHEA": "http://rdf.rhea-db.org/",
    "GTDB": "https://gtdb.ecogenomic.org/tree?r=",
    "GenBank": "https://www.ncbi.nlm.nih.gov/nuccore/",
    "mesh": "http://id.nlm.nih.gov/mesh/",
    "mediadive.medium": "https://mediadive.dsmz.de/medium/",
    "mediadive.solution": "https://mediadive.dsmz.de/solution/",
    "mediadive.ingredient": "https://mediadive.dsmz.de/ingredient/",
    "kgmicrobe.strain": "https://example.org/kgmicrobe/strain/",
    "kgmicrobe.assay": "https://example.org/kgmicrobe/assay/",
    "kgmicrobe.pathway": "https://example.org/kgmicrobe/pathway/",
    "kgmicrobe.compound": "https://example.org/kgmicrobe/compound/",
    "kgmicrobe.species": "https://example.org/kgmicrobe/species/",
    "bacdive.isolation_source": "https://example.org/kgmicrobe/bacdive.isolation_source/",
}


def _single(path: Path) -> Path:
    hits = glob.glob(str(path))
    if not hits:
        sys.exit(f"no file matching {path}")
    return Path(sorted(hits)[0])


def scan(merged_dir: str):
    """Return (node_counts, distinct dicts) from one streaming pass per file."""
    d = Path(merged_dir)
    nodes_f = _single(d / "*_nodes.tsv")
    edges_f = _single(d / "*_edges.tsv")

    csv.field_size_limit(10_000_000)
    categories, node_prefixes = Counter(), Counter()
    n_nodes = 0
    with nodes_f.open() as fh:
        r = csv.reader(fh, delimiter="\t")
        header = next(r)
        ci, idi = header.index("category"), header.index("id")
        for row in r:
            n_nodes += 1
            if len(row) <= max(ci, idi):
                continue
            for cat in row[ci].split("|"):
                if cat:
                    categories[cat] += 1
            if ":" in row[idi]:
                node_prefixes[row[idi].split(":", 1)[0]] += 1

    predicates, klevel, atype = Counter(), Counter(), Counter()
    n_edges = 0
    with edges_f.open() as fh:
        r = csv.reader(fh, delimiter="\t")
        header = next(r)
        pi = header.index("predicate")
        kli = header.index("knowledge_level")
        ati = header.index("agent_type")
        for row in r:
            n_edges += 1
            if len(row) <= max(pi, kli, ati):
                continue
            predicates[row[pi]] += 1
            # ignore '|'-joined merge-dedup artifacts for the enum
            if row[kli] and "|" not in row[kli]:
                klevel[row[kli]] += 1
            if row[ati] and "|" not in row[ati]:
                atype[row[ati]] += 1

    return dict(
        n_nodes=n_nodes,
        n_edges=n_edges,
        nodes_file=nodes_f.name,
        edges_file=edges_f.name,
        categories=categories,
        node_prefixes=node_prefixes,
        predicates=predicates,
        knowledge_level=klevel,
        agent_type=atype,
    )


def _pv(values_counter):
    """Permissible values keyed by CURIE/string, count in description, meaning if CURIE."""
    out = {}
    for val, count in sorted(values_counter.items(), key=lambda kv: -kv[1]):
        if not val:
            continue
        body = {"description": f"{count} occurrences in this build"}
        if ":" in val and " " not in val:  # looks like a CURIE
            body["meaning"] = val
        out[val] = body
    return out


def build_schema(info, merged_dir):
    """Assemble the LinkML schema dict (classes, enums, prefixes) from scan info."""
    used = {"linkml", "biolink", "METPO"}
    used |= set(info["node_prefixes"])
    used |= {c.split(":")[0] for c in info["categories"] if ":" in c}
    used |= {p.split(":")[0] for p in info["predicates"] if ":" in p}
    prefixes = {"KGMicrobeMergedKG": "https://w3id.org/kg-microbe/merged-kg/"}
    for p in sorted(used):
        if p in PREFIXES:
            prefixes[p] = PREFIXES[p]

    schema = {
        "name": "KGMicrobeMergedKG",
        "title": "KG-Microbe Merged Knowledge Graph (KGX)",
        "id": "https://w3id.org/kg-microbe/merged-kg",
        "description": (
            "LinkML schema for the KG-Microbe merged knowledge graph in KGX TSV format "
            f"({merged_dir}: {info['nodes_file']} + {info['edges_file']}). Generated by "
            "scripts/generate_merged_kg_schema.py from the build's distinct column values: "
            f"{info['n_nodes']:,} nodes and {info['n_edges']:,} edges. This build includes the "
            "metatraits and metatraits_gtdb transforms, whose has_phenotype and METPO:* edges "
            "account for most of the edge volume. List-valued node columns (category, xref, "
            "provided_by, synonym, same_as) are '|'-delimited in the TSV. "
            "primary_knowledge_source, relation and unit are left as strings: in this build "
            "primary_knowledge_source mixes infores: CURIEs, Python-list strain-provenance "
            "literals and raw filenames; unit carries some mojibake; and a few edges contributed "
            "by more than one source carry '|'-joined knowledge_level/agent_type values "
            "(excluded from the enums)."
        ),
        "prefixes": dict(sorted(prefixes.items())),
        "default_prefix": "KGMicrobeMergedKG",
        "default_range": "string",
        "imports": ["linkml:types"],
        "classes": {
            "KnowledgeGraph": {
                "tree_root": True,
                "description": "Container for the merged KG node and edge sets.",
                "attributes": {
                    "nodes": {"range": "Node", "multivalued": True, "inlined_as_list": True},
                    "edges": {"range": "Edge", "multivalued": True, "inlined_as_list": True},
                },
            },
            "Node": {
                "description": "A KGX node (one row of *_nodes.tsv).",
                "attributes": {
                    "id": {"identifier": True, "range": "uriorcurie", "description": "Node CURIE."},
                    "category": {
                        "range": "NodeCategoryEnum",
                        "multivalued": True,
                        "description": "Biolink/METPO category; '|'-delimited in the TSV.",
                    },
                    "name": {"description": "Human-readable label."},
                    "description": {"description": "Free-text description."},
                    "xref": {
                        "multivalued": True,
                        "range": "uriorcurie",
                        "description": "Cross-references ('|'-delimited).",
                    },
                    "provided_by": {
                        "multivalued": True,
                        "description": "Source(s) that provided the node ('|'-delimited).",
                    },
                    "synonym": {"multivalued": True, "description": "Synonyms ('|'-delimited)."},
                    "deprecated": {
                        "range": "boolean",
                        "description": "Deprecation flag (mostly empty; a few UPA rows carry malformed URI values).",
                    },
                    "same_as": {
                        "multivalued": True,
                        "range": "uriorcurie",
                        "description": "Equivalent identifiers ('|'-delimited).",
                    },
                },
            },
            "Edge": {
                "description": "A KGX edge (one row of *_edges.tsv).",
                "attributes": {
                    "subject": {"range": "Node", "required": True, "description": "Subject node."},
                    "predicate": {
                        "range": "PredicateEnum",
                        "required": True,
                        "description": "Biolink/METPO predicate.",
                    },
                    "object": {"range": "Node", "required": True, "description": "Object node."},
                    "relation": {
                        "range": "uriorcurie",
                        "description": "Relation CURIE (RO/biolink); ~100 distinct in this build.",
                    },
                    "primary_knowledge_source": {
                        "description": (
                            "Provenance: an infores: CURIE, a Python-list strain-provenance "
                            "literal, or a raw source filename."
                        ),
                    },
                    "knowledge_level": {
                        "range": "KnowledgeLevelEnum",
                        "description": "Biolink knowledge level.",
                    },
                    "agent_type": {"range": "AgentTypeEnum", "description": "Biolink agent type."},
                    "has_percentage": {
                        "range": "float",
                        "description": "Consensus percentage (metatraits edges).",
                    },
                    "unit": {
                        "description": "Unit string for value (metatraits/bacdive measurement edges)."
                    },
                    "value": {"description": "Measured value (numeric or text)."},
                },
            },
        },
        "enums": {
            "NodeCategoryEnum": {
                "description": "Biolink/METPO categories observed in the node set.",
                "permissible_values": _pv(info["categories"]),
            },
            "PredicateEnum": {
                "description": "Biolink/METPO predicates observed in the edge set.",
                "permissible_values": _pv(info["predicates"]),
            },
            "KnowledgeLevelEnum": {
                "description": "Biolink knowledge levels observed in the edge set.",
                "permissible_values": _pv(info["knowledge_level"]),
            },
            "AgentTypeEnum": {
                "description": "Biolink agent types observed in the edge set.",
                "permissible_values": _pv(info["agent_type"]),
            },
        },
    }
    return schema


def main():
    """Scan the merged KG and write the LinkML schema."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merged-dir", default="data/merged/20260610")
    ap.add_argument("--output", default="schema/kg_microbe_merged.yaml")
    args = ap.parse_args()

    info = scan(args.merged_dir)
    print(
        f"scanned {info['n_nodes']:,} nodes / {info['n_edges']:,} edges -> "
        f"{len(info['categories'])} categories, {len(info['predicates'])} predicates"
    )
    schema = build_schema(info, args.merged_dir)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as fh:
        yaml.safe_dump(schema, fh, sort_keys=False, allow_unicode=True, width=100)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
