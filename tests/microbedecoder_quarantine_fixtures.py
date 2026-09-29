"""Explicit tiny source/policy fixtures, never a production admission bypass."""

import base64
import csv
import gzip
import hashlib
import json
from dataclasses import fields
from pathlib import Path

from kg_microbe.transform_utils.constants import (
    CLOSE_MATCH_PREDICATE,
    CLOSE_MATCH_RELATION,
    KNOWLEDGE_ASSERTION,
    MANUAL_AGENT,
    MICROBEDECODER_KNOWLEDGE_SOURCE,
)
from kg_microbe.transform_utils.microbedecoder.crosswalk_quarantine import (
    CrosswalkDecision,
    crosswalk_raw_record_sha256,
)
from kg_microbe.transform_utils.microbedecoder.utils import crosswalk_curie, split_multivalue_comma_only


def _edge(
    subject, target, provider, predicate="biolink:subclass_of", relation="rdfs:subClassOf", level="knowledge_assertion"
):
    return {
        "subject": subject,
        "object": target,
        "primary_knowledge_source": provider,
        "predicate": predicate,
        "relation": relation,
        "knowledge_level": level,
        "agent_type": "automated_agent" if level == "prediction" else "manual_agent",
    }


def _node(identifier, provider, name="Synthetic species"):
    return {
        "id": identifier,
        "name": name,
        "category": "biolink:OrganismTaxon",
        "provided_by": provider,
        "deprecated": "false",
        "synonym": "",
    }


def _native(target, genus, phylum):
    ids = [target, genus, phylum, "NCBITaxon:1"]
    return {
        "input": target,
        "resolved": target,
        "aliases": [],
        "genus": genus,
        "phylum": phylum,
        "nodes": [_node(identifier, "infores:ncbitaxon") for identifier in ids],
        "edges": [_edge(subject, obj, "infores:ncbitaxon") for subject, obj in zip(ids[:-1], ids[1:], strict=True)],
    }


def _fixture_witness(rule, row):
    subject, raw = rule["subject"], rule["raw_lpsn_id"]
    accepted_id = subject.split(":")[1]
    gss = {
        "record_no": accepted_id,
        "status": "correct name",
        "record_lnk": "",
        "genus_name": "Synthetic",
        "sp_epithet": "species",
        "subsp_epithet": "",
    }
    chain = (
        [gss]
        if raw == accepted_id
        else [{**gss, "record_no": raw, "status": "synonym", "record_lnk": accepted_id}, gss]
    )
    expected = _native("NCBITaxon:900001", "NCBITaxon:900002", "NCBITaxon:900003")
    target = _native(
        rule["object"] if rule["source_column"] == "NCBI_Taxonomy_ID" else "NCBITaxon:1352",
        "NCBITaxon:910002",
        "NCBITaxon:910003",
    )
    target["nodes"][0]["name"] = "Synthetic incompatible target"
    bid = row["BacDive_ID"]
    strain = "kgmicrobe.strain:bacdive_" + bid
    context = {
        "accepted_subject": subject,
        "gss_chain": chain,
        "lpsn_expectation": {
            "via": subject,
            "parent_edges": [],
            "lpsn_nodes": [_node(subject, "infores:lpsn")],
            "crosswalk": _edge(
                subject, expected["input"], "infores:lpsn", "biolink:close_match", "skos:closeMatch", "prediction"
            ),
            "native": expected,
        },
        "bacdive_support": {
            "record": {
                "array_item": 1,
                "General": {
                    "BacDive-ID": int(bid),
                    "NCBI tax id": {"NCBI tax id": 900001, "Matching level": "species"},
                },
                "Name and taxonomic classification": {"type strain": "yes", "LPSN": {"species": "Synthetic species"}},
            },
            "strain_node": _node(strain, "infores:bacdive"),
            "lpsn_edges": [_edge(strain, subject, "infores:bacdive", level="observation")],
            "ncbi_edges": [_edge(strain, expected["input"], "infores:bacdive", level="observation")],
            "native_explicit_taxa": [expected],
        },
    }
    gold = None
    if rule["source_column"] == "GOLD_Organism_ID":
        gold = {
            "raw_node": {
                "id": rule["object"],
                "name": "Synthetic other species",
                "category": "biolink:IndividualOrganism",
                "provided_by": "infores:gold",
                "xref": target["input"],
            },
            "raw_edge": _edge(
                rule["object"], target["input"], "infores:gold", "biolink:in_taxon", "gold:organism_v2.ncbi_taxonomy_id"
            ),
            "native_node": _node(rule["object"], "infores:gold"),
            "native_edges": [_edge(rule["object"], target["input"], "infores:gold")],
            "fold_target": None,
        }
    return {
        **{key: rule[key] for key in ("source_record", "source_column", "source_token", "object", "subject")},
        "classification": "authority_contradiction",
        "evidence_uri": "https://example.org/immutable-fixture-evidence",
        "policy": "two_authority_cross_genus_and_phylum_v1",
        "raw_record_sha256": rule["raw_record_sha256"],
        "source_ordinal": int(rule["source_record"].rsplit("=", 1)[1]),
        "context": context,
        "target": target,
        "gold": gold,
        "bacdive_name_authority": {
            "authority_id": "lpsn_gss",
            "raw_bacdive_lpsn_species": "Synthetic species",
            "all_exact_name_record_nos": [accepted_id],
            "accepted_chains": [[gss]],
        },
        "original_emitted_edge": {
            **_edge(subject, rule["object"], "infores:microbedecoder", "biolink:close_match", "skos:closeMatch"),
            "source_record": rule["source_record"],
        },
    }


def write_fixture_quarantine_policy(raw_path, directory, *, selected=(), accepted=None, canonical_names=False):
    """
    Pin a synthetic CSV, optionally quarantining selected (ordinal, column) uses.

    Callers inject the returned ordinary policy path through the constructor
    or its public path attribute. A later source change requires a deliberate
    new fixture policy; run() never generates or bypasses a policy itself.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = Path(raw_path)
    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    with raw_path.open(encoding="utf-8", errors="surrogateescape", newline="") as stream:
        records = list(csv.DictReader(stream))
    accepted = accepted or {}
    decisions, witnesses = [], {}
    for ordinal, column in selected:
        row = records[ordinal - 1]
        prefix = {"NCBI_Taxonomy_ID": "NCBITaxon:", "GOLD_Organism_ID": "gold:"}[column]
        token = split_multivalue_comma_only(row[column])[0]
        identifier = f"record_{ordinal}_{column}"
        decision = {
            "rule_id": identifier,
            "source_record": f"sha256:{digest}#record={ordinal}",
            "raw_record_sha256": crosswalk_raw_record_sha256(row),
            "raw_lpsn_id": row["LPSN_ID"],
            "subject": "lpsn:" + accepted.get(row["LPSN_ID"], row["LPSN_ID"]),
            "source_column": column,
            "source_cell_base64": base64.b64encode(row[column].encode("utf-8", errors="surrogateescape")).decode(),
            "source_token": token,
            "object": crosswalk_curie(token, prefix),
            "predicate": CLOSE_MATCH_PREDICATE,
            "relation": CLOSE_MATCH_RELATION,
            "primary_knowledge_source": MICROBEDECODER_KNOWLEDGE_SOURCE,
            "knowledge_level": KNOWLEDGE_ASSERTION,
            "agent_type": MANUAL_AGENT,
            "disposition": "quarantine_authority_contradiction",
            "witness_id": identifier,
            "rationale": "Synthetic independently declared conflict; not biological curation.",
        }
        decisions.append(decision)
        witnesses[identifier] = _fixture_witness(decision, row)
    decisions_path = directory / ("microbedecoder_crosswalk_quarantine.tsv" if canonical_names else "decisions.tsv")
    with decisions_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[field.name for field in fields(CrosswalkDecision)],
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(decisions)
    evidence_path = directory / (
        "microbedecoder_crosswalk_quarantine_evidence.json.gz" if canonical_names else "evidence.json"
    )
    evidence = {
        "version": 1,
        "source_sha256": digest,
        "authorities": {
            name: {
                "path_or_uri": "https://example.org/authority/" + name,
                "sha256": digest if name == "raw" else "a" * 64,
            }
            for name in (
                "raw",
                "lpsn_gss",
                "lpsn_nodes",
                "lpsn_edges",
                "ncbi_nodes",
                "ncbi_edges",
                "taxdump",
                "bacdive_raw",
                "bacdive_nodes",
                "bacdive_edges",
                "gold_raw_nodes",
                "gold_raw_edges",
                "gold_nodes",
                "gold_edges",
                "gold_folds",
                "candidate_edges",
            )
        }
        if selected
        else {},
        "witnesses": witnesses,
        "objects": {},
        "taxdump_member_hashes": {"nodes.dmp": "b" * 64, "merged.dmp": "c" * 64},
        "taxonomy_rank_witnesses": {
            "NCBITaxon:" + taxid: {
                "authority_id": "taxdump",
                "member": "nodes.dmp",
                "line_ordinal": ordinal + 1,
                "rank": rank,
                "raw_line_base64": base64.b64encode(f"{taxid}\t|\t1\t|\t{rank}\t|\n".encode()).decode(),
            }
            for ordinal, (taxid, rank) in enumerate(
                (("900002", "genus"), ("900003", "phylum"), ("910002", "genus"), ("910003", "phylum"))
            )
        },
        "retired_taxid_witnesses": {},
    }
    decoded = (json.dumps(evidence, sort_keys=True) + "\n").encode("utf-8")
    evidence_path.write_bytes(gzip.compress(decoded, mtime=0) if canonical_names else decoded)
    policy = {
        "version": 1,
        "source_sha256": digest,
        "source_records": len(records),
        "decisions_file": decisions_path.name,
        "decisions_sha256": hashlib.sha256(decisions_path.read_bytes()).hexdigest(),
        "decisions_rows": len(decisions),
        "evidence_file": evidence_path.name,
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    if canonical_names:
        policy.update(
            evidence_uncompressed_sha256=hashlib.sha256(decoded).hexdigest(), evidence_uncompressed_bytes=len(decoded)
        )
    policy_path = directory / ("microbedecoder_crosswalk_quarantine.json" if canonical_names else "policy.json")
    policy_path.write_text(json.dumps(policy, sort_keys=True) + "\n", encoding="utf-8")
    return policy_path


def bind_fixture_quarantine_policy(transform, raw_path, *, selected=(), accepted=None):
    """Deliberately update one test transform to a separately pinned fixture policy."""
    policy = write_fixture_quarantine_policy(
        raw_path, transform.output_dir / "fixture-crosswalk-policy", selected=selected, accepted=accepted
    )
    transform.crosswalk_quarantine_policy = policy
    return policy
