#!/usr/bin/env python3
"""
KG-Microbe Knowledge Modeling Review

Checks alignment of transform outputs and merged KG with:
  - KGX specification (required columns, CURIE format)
  - Biolink Model (valid categories, valid predicates)
  - METPO (class and predicate CURIEs)
  - CURIE prefix registration
"""

import argparse
import csv
import gzip
import io
import json
import re
import sys
import tarfile
import yaml
from collections import defaultdict
from datetime import date
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent.parent  # .claude/skills/kg-model-review → repo root
TRANSFORMS_DIR = REPO_ROOT / "data" / "transformed"
MERGED_DIR = REPO_ROOT / "data" / "merged"
CUSTOM_CURIES_FILE = REPO_ROOT / "kg_microbe" / "transform_utils" / "custom_curies.yaml"
ONTOLOGIES_DIR = TRANSFORMS_DIR / "ontologies"

# ── KGX spec ─────────────────────────────────────────────────────────────────
NODES_REQUIRED = {"id", "category", "name"}
EDGES_REQUIRED = {"subject", "predicate", "object", "relation"}

CURIE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-.]*:.+")

# ── Valid Biolink categories ──────────────────────────────────────────────────
VALID_CATEGORIES = {
    "biolink:OrganismTaxon",
    "biolink:ChemicalEntity",
    "biolink:ChemicalSubstance",  # KG-Microbe convention: normalization target for CHEBI-mapped chemicals (see constants.CHEBI_CATEGORY)
    "biolink:SmallMolecule",
    "biolink:MolecularMixture",
    "biolink:ComplexMolecularMixture",
    "biolink:Food",
    "biolink:MacromolecularMachineMixin",
    "biolink:Protein",
    "biolink:Gene",
    "biolink:MolecularActivity",
    "biolink:BiologicalProcess",
    "biolink:CellularComponent",
    "biolink:PhenotypicQuality",
    "biolink:Attribute",
    "biolink:NamedThing",
    "biolink:GrossAnatomicalStructure",
    "biolink:AnatomicalEntity",
    "biolink:EnvironmentalProcess",
    "biolink:PathologicalProcess",
    "biolink:Disease",
    "biolink:GrowthMedium",
    "biolink:Polypeptide",
    "biolink:NucleicAcidEntity",
    "biolink:GenomicEntity",
    "biolink:ChemicalRole",
    "biolink:InformationContentEntity",
    "biolink:Pathway",
    "biolink:PhysiologicalProcess",
    "biolink:MacromolecularComplex",
    "biolink:ChemicalMixture",
    "biolink:ProcessedMaterial",
    "biolink:Procedure",           # used for assay/test nodes
    "biolink:EnvironmentalFeature", # used for isolation source nodes
    "biolink:GeneFamily",          # used by COG transform
    "biolink:OntologyClass",       # used by COG transform
    "biolink:ActivityAndBehavior", # valid Biolink class; appears in madin_etal OAK mappings
    "biolink:EnvironmentalMaterial", # valid Biolink class; from OAK mappings
    "biolink:Macromolecule",       # deprecated → MacromolecularComplex, but still emitted by OAK
    # Additional valid Biolink classes surfaced by the ontologies transform (OAK output)
    "biolink:PhenotypicFeature",
    "biolink:Cell",
    "biolink:SequenceFeature",
    "biolink:Genome",          # NCBITaxon genomes; large use in merged KG
    "biolink:TaxonomicRank",   # NCBITaxon rank terms
}

DEPRECATED_CATEGORIES = {
    # NOTE: biolink:ChemicalSubstance is deprecated upstream but is the KG-Microbe
    # normalization target for CHEBI chemicals. Intentionally NOT flagged here.
    "biolink:MacromolecularMachineMixin": "biolink:Protein or biolink:Gene",
    "biolink:Macromolecule": "biolink:MacromolecularComplex",
    "biolink:ActivityAndBehavior": "biolink:BiologicalProcess or biolink:MolecularActivity",
}

# ── Valid Biolink predicates ──────────────────────────────────────────────────
VALID_PREDICATES = {
    "biolink:has_phenotype",
    "biolink:capable_of",
    "biolink:produces",
    "biolink:consumes",
    "biolink:located_in",
    "biolink:location_of",
    "biolink:has_part",
    "biolink:subclass_of",
    "biolink:related_to",
    "biolink:associated_with",
    "biolink:enabled_by",
    "biolink:enables",
    "biolink:has_chemical_role",
    "biolink:has_input",
    "biolink:has_output",
    "biolink:occurs_in",
    "biolink:associated_with_resistance_to",
    "biolink:associated_with_sensitivity_to",
    "biolink:related_to_at_instance_level",
    "biolink:contains_process",
    "biolink:same_as",
    "biolink:close_match",
    "biolink:broad_match",
    "biolink:narrow_match",
    "biolink:exact_match",
    "biolink:overlaps",
    "biolink:part_of",
    "biolink:has_attribute",
    "biolink:actively_involved_in",
    "biolink:participates_in",
    "biolink:interacts_with",
    "biolink:regulates",
    "biolink:positively_regulates",
    "biolink:negatively_regulates",
    "biolink:expressed_in",
    # Non-biolink OWL/RDFS structural predicates used by the ontologies
    # transform for meta-axioms (property hierarchies, inverses, type
    # assertions). These are legitimately non-biolink; they round-trip back
    # to OWL semantics downstream.
    "rdfs:subPropertyOf",
    "owl:inverseOf",
    "rdf:type",
}

# METPO:2000xxx predicates are domain-specific refinements of biolink predicates
# (e.g. METPO:2000003 "builds acid from" is more specific than biolink:produces).
# Treat any predicate listed in METPO_TO_BIOLINK_PREDICATE as valid — the mapping
# itself is the registration.
try:
    from kg_microbe.utils.metpo_predicates import METPO_TO_BIOLINK_PREDICATE
    VALID_PREDICATES |= set(METPO_TO_BIOLINK_PREDICATE.keys())
except ImportError:
    pass

# ── Standard known CURIE prefixes ─────────────────────────────────────────────
STANDARD_PREFIXES = {
    "NCBITaxon", "CHEBI", "GO", "EC", "RO", "METPO", "biolink",
    "FOODON", "UBERON", "HP", "MONDO", "ENVO", "infores", "semapv",
    "kgmicrobe.activity", "kgmicrobe.trait", "kgmicrobe.compound",
    "UniProtKB", "PR", "SO", "RHEA", "OBI", "IAO", "BFO",
    "PATO", "CL", "NCIT", "DOID", "MESH", "OMIM", "orphanet",
    "OMP", "MOP", "KEGG", "COG", "GTDB", "skos", "owl", "rdf",
    "rdfs", "xsd", "oboInOwl", "dcterms", "schema",
    # lowercase aliases used by madin_etal NER fallback
    "envo", "foodon", "pato", "po",
    # madin_etal provisional node prefixes (fallback when no ontology term found)
    "pathways", "carbon_substrates",
    # bacdive / mediadive domain-specific prefixes
    "bacdive.isolation_source",
    # mediadive prefixes
    "mediadive.medium", "mediadive.ingredient", "mediadive.solution", "mediadive.medium-type",
    "CAS-RN", "cas", "PubChem", "pubchem.compound", "PUBCHEM.COMPOUND",
    # bacdive / metatraits provisional organism prefixes
    "kgmicrobe.strain", "kgmicrobe.species", "kgmicrobe.genus",
    # bacdive assay prefix
    "assay",
    # COG functional categories
    "COG_CAT", "COG_GROUP",
    # foodon lowercase (from madin_etal)
    "foodon",
    # OBO imports reachable through NCBITaxon / MONDO / CHEBI OWL closure
    "AGRO", "BSPO", "BTO", "CARO", "CEPH", "CHR", "DRON", "ECOCORE",
    "FAO", "FLOPO", "GAZ", "GENEPIO", "HGNC", "MF", "MFOMD", "MOD",
    "NBO", "NCBIGene", "OBO", "OGMS", "OIO", "PCO", "UO",
    "UPA",  # UniPathway
    "UPHENO", "WD_Entity",
    "PO",        # Plant Ontology (OBO; reachable via ENVO/FOODON closure)
    "TAXRANK",   # Taxonomic Rank vocabulary (OBO; from NCBITaxon)
    "GenBank",   # GenBank sequence accessions (from NCBITaxon xrefs)
    "chemrof",   # chemical role framework (CHEBI-adjacent)
    "debio",     # domain entity for biology (Rhea-adjacent)
    "kgmicrobe", # KG-Microbe native prefix (bare form; dotted variants also registered)
    # Namespaces carried through by OAK
    "dc", "dcterms", "doap", "foaf", "pav",
    # URL-style ids that occasionally leak through
    "http", "https", "urn", "orcid",
}


# ── Findings ──────────────────────────────────────────────────────────────────
class Finding:
    """A single review finding."""

    def __init__(self, severity: str, check: str, message: str, examples: list = None):
        self.severity = severity  # ERROR / WARNING / INFO
        self.check = check        # KGX / Biolink / METPO / Prefix
        self.message = message
        self.examples = examples or []

    def __str__(self):
        icon = {"ERROR": "❌", "WARNING": "⚠️ ", "INFO": "ℹ️ "}.get(self.severity, "  ")
        s = f"    [{self.check:<8}] {icon} {self.severity}: {self.message}"
        for ex in self.examples[:3]:
            s += f"\n              e.g. {ex!r}"
        return s


# ── Helpers ───────────────────────────────────────────────────────────────────
def load_registered_prefixes() -> set:
    """Load all registered prefixes from custom_curies.yaml."""
    prefixes = set(STANDARD_PREFIXES)
    if CUSTOM_CURIES_FILE.exists():
        with open(CUSTOM_CURIES_FILE) as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            for section in data.values():
                if isinstance(section, dict):
                    for key in section:
                        # KGM slugs map to KGM: prefix
                        prefixes.add("KGM")
                        break
    return prefixes


def load_metpo_curies() -> set:
    """Load all METPO CURIEs from ontologies transform output.

    The ontologies transform emits per-ontology files (e.g. ``metpo_nodes.tsv``),
    not a single ``nodes.tsv``. Prefer the dedicated METPO file when present and
    fall back to any ``*_nodes.tsv`` that contains METPO ids.
    """
    curies = set()
    if not ONTOLOGIES_DIR.exists():
        return curies

    metpo_file = ONTOLOGIES_DIR / "metpo_nodes.tsv"
    candidates = [metpo_file] if metpo_file.exists() else sorted(ONTOLOGIES_DIR.glob("*_nodes.tsv"))

    for path in candidates:
        with open(path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                nid = row.get("id", "")
                if nid.startswith("METPO:"):
                    curies.add(nid)
    return curies


def iter_tsv(path: Path, max_rows: int):
    """Yield dicts from a TSV (plain or gzipped), up to max_rows data rows."""
    opener = gzip.open if path.suffix == ".gz" else open
    mode = "rt" if path.suffix == ".gz" else "r"
    count = 0
    with opener(path, mode, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            yield row
            count += 1
            if max_rows and count >= max_rows:
                break


def iter_tsv_from_tar(tar_path: Path, member_name: str, max_rows: int):
    """Yield dicts from a TSV member inside a .tar.gz archive."""
    count = 0
    with tarfile.open(tar_path, "r:gz") as tf:
        try:
            member = tf.getmember(member_name)
        except KeyError:
            return
        f = tf.extractfile(member)
        if f is None:
            return
        text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
        reader = csv.DictReader(text, delimiter="\t")
        for row in reader:
            yield row
            count += 1
            if max_rows and count >= max_rows:
                break


def get_prefix(curie: str) -> str:
    return curie.split(":")[0] if ":" in curie else ""


# ── Per-file checks ───────────────────────────────────────────────────────────
def check_nodes_rows(rows: list, max_rows: int, registered_prefixes: set,
                     metpo_curies: set, verbose: bool) -> list:
    """Check a pre-loaded list of node rows."""
    findings = []
    if not rows:
        findings.append(Finding("WARNING", "KGX", "nodes file is empty"))
        return findings

    cols = set(rows[0].keys())
    total = len(rows)

    # KGX: required columns
    missing_cols = NODES_REQUIRED - cols
    if missing_cols:
        findings.append(Finding("ERROR", "KGX", f"Missing required columns: {missing_cols}"))
    else:
        findings.append(Finding("INFO", "KGX", f"Required columns present ({total:,} rows sampled)"))

    # KGX: CURIE format for id
    bad_ids = [r["id"] for r in rows if not CURIE_RE.match(r.get("id", ""))]
    if bad_ids:
        findings.append(Finding("ERROR", "KGX", f"{len(bad_ids)} non-CURIE id values",
                                bad_ids[:5] if verbose else []))

    # KGX: duplicate ids
    ids = [r.get("id", "") for r in rows]
    dupes = len(ids) - len(set(ids))
    if dupes:
        findings.append(Finding("WARNING", "KGX", f"{dupes} duplicate id values in sample"))
    else:
        findings.append(Finding("INFO", "KGX", "No duplicate IDs in sample"))

    # Biolink: category values
    cat_counts: dict = defaultdict(int)
    empty_cats = 0
    for r in rows:
        cat = r.get("category", "").strip()
        if not cat:
            empty_cats += 1
        else:
            # Handle pipe-separated lists
            for c in cat.split("|"):
                cat_counts[c.strip()] += 1

    if empty_cats:
        findings.append(Finding("WARNING", "Biolink", f"{empty_cats} rows with empty category"))

    unknown_cats = {c: n for c, n in cat_counts.items() if c not in VALID_CATEGORIES}
    deprecated_cats = {c: n for c, n in cat_counts.items() if c in DEPRECATED_CATEGORIES}
    if unknown_cats:
        examples = [f"{c} ({n}x)" for c, n in sorted(unknown_cats.items(), key=lambda x: -x[1])[:5]]
        findings.append(Finding("WARNING", "Biolink", f"{len(unknown_cats)} unknown/unrecognized categories",
                                examples if verbose else []))
    if deprecated_cats:
        dep_msgs = [f"{c} → consider {DEPRECATED_CATEGORIES[c]} ({n}x)"
                    for c, n in deprecated_cats.items()]
        findings.append(Finding("INFO", "Biolink", f"{len(deprecated_cats)} deprecated categories in use",
                                dep_msgs if verbose else []))
    if not unknown_cats and not deprecated_cats:
        findings.append(Finding("INFO", "Biolink", "All categories recognized"))

    # Prefix: id prefixes
    prefixes_used = {get_prefix(r.get("id", "")) for r in rows if r.get("id")}
    unknown_prefixes = prefixes_used - registered_prefixes
    if unknown_prefixes:
        findings.append(Finding("WARNING", "Prefix",
                                f"Unregistered prefixes in id: {sorted(unknown_prefixes)}"))
    else:
        findings.append(Finding("INFO", "Prefix", "All id prefixes registered"))

    return findings


def check_nodes(path: Path, max_rows: int, registered_prefixes: set,
                metpo_curies: set, verbose: bool) -> list:
    """Check nodes from a file path."""
    findings = []
    if not path.exists():
        findings.append(Finding("ERROR", "KGX", f"nodes.tsv not found: {path}"))
        return findings
    rows = list(iter_tsv(path, max_rows))
    return check_nodes_rows(rows, max_rows, registered_prefixes, metpo_curies, verbose)


def check_edges_rows(rows: list, max_rows: int, registered_prefixes: set,
                     metpo_curies: set, verbose: bool) -> list:
    """Check a pre-loaded list of edge rows."""
    findings = []
    if not rows:
        findings.append(Finding("WARNING", "KGX", "edges file is empty"))
        return findings

    cols = set(rows[0].keys())
    total = len(rows)

    # KGX: required columns
    missing_cols = EDGES_REQUIRED - cols
    if missing_cols:
        findings.append(Finding("ERROR", "KGX", f"Missing required columns: {missing_cols}"))
    else:
        findings.append(Finding("INFO", "KGX", f"Required columns present ({total:,} rows sampled)"))

    # KGX: CURIE format for subject/object
    bad_subj = [r["subject"] for r in rows if not CURIE_RE.match(r.get("subject", ""))]
    bad_obj = [r["object"] for r in rows if not CURIE_RE.match(r.get("object", ""))]
    if bad_subj:
        findings.append(Finding("ERROR", "KGX", f"{len(bad_subj)} non-CURIE subject values",
                                bad_subj[:5] if verbose else []))
    if bad_obj:
        findings.append(Finding("ERROR", "KGX", f"{len(bad_obj)} non-CURIE object values",
                                bad_obj[:5] if verbose else []))

    # Biolink: predicate values
    pred_counts: dict = defaultdict(int)
    for r in rows:
        pred_counts[r.get("predicate", "").strip()] += 1

    unknown_preds = {p: n for p, n in pred_counts.items()
                     if p and p not in VALID_PREDICATES}
    if unknown_preds:
        examples = [f"{p} ({n}x)" for p, n in sorted(unknown_preds.items(), key=lambda x: -x[1])[:5]]
        findings.append(Finding("WARNING", "Biolink",
                                f"{len(unknown_preds)} unrecognized predicate values",
                                examples if verbose else []))
    else:
        findings.append(Finding("INFO", "Biolink", "All predicates recognized"))

    # METPO: relation column should not repeat biolink predicate
    biolink_in_relation = [r for r in rows
                           if r.get("relation", "").startswith("biolink:")]
    if biolink_in_relation:
        examples = [f"{r['relation']}" for r in biolink_in_relation[:5]]
        findings.append(Finding("WARNING", "METPO",
                                f"{len(biolink_in_relation)} edges use biolink: prefix in relation column "
                                "(should be RO or METPO term)",
                                examples if verbose else []))
    else:
        findings.append(Finding("INFO", "METPO", "relation column uses non-biolink CURIEs"))

    # METPO: object CURIEs starting with METPO: should exist in ontology
    if metpo_curies:
        bad_metpo = [r["object"] for r in rows
                     if r.get("object", "").startswith("METPO:")
                     and r["object"] not in metpo_curies]
        if bad_metpo:
            findings.append(Finding("WARNING", "METPO",
                                    f"{len(bad_metpo)} METPO object CURIEs not found in ontologies output",
                                    bad_metpo[:5] if verbose else []))
        else:
            metpo_objects = sum(1 for r in rows if r.get("object", "").startswith("METPO:"))
            if metpo_objects:
                findings.append(Finding("INFO", "METPO",
                                        f"All {metpo_objects} METPO object CURIEs validated"))

    # Prefix: subject/object/relation prefixes
    all_curies = (
        [r.get("subject", "") for r in rows]
        + [r.get("object", "") for r in rows]
        + [r.get("relation", "") for r in rows]
    )
    prefixes_used = {get_prefix(c) for c in all_curies if c and ":" in c}
    unknown_prefixes = prefixes_used - registered_prefixes
    if unknown_prefixes:
        findings.append(Finding("WARNING", "Prefix",
                                f"Unregistered prefixes in edges: {sorted(unknown_prefixes)}"))
    else:
        findings.append(Finding("INFO", "Prefix", "All edge prefixes registered"))

    return findings


def check_edges(path: Path, max_rows: int, registered_prefixes: set,
                metpo_curies: set, verbose: bool) -> list:
    """Check edges from a file path."""
    findings = []
    if not path.exists():
        findings.append(Finding("ERROR", "KGX", f"edges.tsv not found: {path}"))
        return findings
    rows = list(iter_tsv(path, max_rows))
    return check_edges_rows(rows, max_rows, registered_prefixes, metpo_curies, verbose)


# ── Main review ───────────────────────────────────────────────────────────────
def _tally(result: dict) -> dict:
    """Count errors and warnings in result findings."""
    for f in result["nodes"] + result["edges"]:
        if f.severity == "ERROR":
            result["errors"] += 1
        elif f.severity == "WARNING":
            result["warnings"] += 1
    return result


def review_transform(name: str, transform_dir: Path, max_rows: int,
                     registered_prefixes: set, metpo_curies: set,
                     verbose: bool) -> dict:
    """Review a single transform's nodes.tsv and edges.tsv."""
    result = {"name": name, "nodes": [], "edges": [], "errors": 0, "warnings": 0}

    # Special case: merged KG stored as merged-kg.tar.gz in data/merged/, with
    # merged-kg_{nodes,edges}.tsv at the archive root (per _rewrite_tarball in
    # kg_microbe/merge_utils/merge_kg.py, which uses arcname=f.name).
    tar_path = transform_dir / "merged-kg.tar.gz"
    if name == "merged" and tar_path.exists():
        nodes_rows = list(iter_tsv_from_tar(tar_path, "merged-kg_nodes.tsv", max_rows))
        edges_rows = list(iter_tsv_from_tar(tar_path, "merged-kg_edges.tsv", max_rows))
        result["nodes"] = check_nodes_rows(nodes_rows, max_rows, registered_prefixes, metpo_curies, verbose)
        result["edges"] = check_edges_rows(edges_rows, max_rows, registered_prefixes, metpo_curies, verbose)
        return _tally(result)

    nodes_path = transform_dir / "nodes.tsv"
    edges_path = transform_dir / "edges.tsv"

    # Also check for gzipped variants
    if not nodes_path.exists():
        nodes_path = transform_dir / "nodes.tsv.gz"
    if not edges_path.exists():
        edges_path = transform_dir / "edges.tsv.gz"

    # Handle ontologies transform: per-ontology files (*_nodes.tsv / *_edges.tsv).
    # Cross-file id overlap is expected here — each ontology's KGX output
    # includes imports/axiom-references from other ontologies (e.g. HP
    # references MONDO classes). These duplicates are resolved at merge
    # time, so for duplicate-id checking we dedupe by id across files.
    if not nodes_path.exists():
        per_ont_nodes = sorted(transform_dir.glob("*_nodes.tsv"))
        per_ont_edges = sorted(transform_dir.glob("*_edges.tsv"))
        if per_ont_nodes or per_ont_edges:
            all_node_rows, all_edge_rows = [], []
            seen_ids = set()
            for p in per_ont_nodes:
                for r in iter_tsv(p, max_rows):
                    nid = r.get("id", "")
                    if nid in seen_ids:
                        continue
                    seen_ids.add(nid)
                    all_node_rows.append(r)
            for p in per_ont_edges:
                all_edge_rows.extend(iter_tsv(p, max_rows))
            result["nodes"] = check_nodes_rows(all_node_rows, max_rows, registered_prefixes, metpo_curies, verbose)
            result["edges"] = check_edges_rows(all_edge_rows, max_rows, registered_prefixes, metpo_curies, verbose)
            return _tally(result)
        # Empty directory (transform not run) — skip silently
        result["nodes"] = [Finding("INFO", "KGX", "No output files found (transform not run or no data)")]
        result["edges"] = []
        return result

    result["nodes"] = check_nodes(nodes_path, max_rows, registered_prefixes, metpo_curies, verbose)
    result["edges"] = check_edges(edges_path, max_rows, registered_prefixes, metpo_curies, verbose)
    return _tally(result)


def format_text(results: list, format_md: bool = False) -> str:
    lines = []
    sep = "---" if not format_md else "---"
    header = "# KG-Microbe Knowledge Modeling Review" if format_md else "=== KG-Microbe Knowledge Modeling Review ==="
    lines.append(header)
    lines.append(f"Date: {date.today()}")
    lines.append("")

    total_errors = total_warnings = 0

    for r in results:
        name = r["name"]
        lines.append(f"{'## ' if format_md else ''}Transform: {name}")
        lines.append(f"  nodes.tsv")
        for f in r["nodes"]:
            lines.append(str(f))
        lines.append(f"  edges.tsv")
        for f in r["edges"]:
            lines.append(str(f))
        lines.append("")
        total_errors += r["errors"]
        total_warnings += r["warnings"]

    lines.append(sep)
    lines.append(f"{'## ' if format_md else ''}Summary")
    lines.append(f"  Transforms reviewed: {len(results)}")
    lines.append(f"  Total ERRORs:        {total_errors}")
    lines.append(f"  Total WARNINGs:      {total_warnings}")
    if total_errors == 0 and total_warnings == 0:
        lines.append("  ✅ All checks passed")
    elif total_errors == 0:
        lines.append("  ⚠️  Warnings found — review before release")
    else:
        lines.append("  ❌ Errors found — fix before merge/release")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="KG-Microbe knowledge modeling review")
    parser.add_argument("--transform", help="Review specific transform (default: all)")
    parser.add_argument("--merged", action="store_true", help="Review merged KG instead of transforms")
    parser.add_argument("--format", choices=["text", "md", "json"], default="text")
    parser.add_argument("--verbose", action="store_true", help="Show example violations")
    parser.add_argument("--max-rows", type=int, default=100_000,
                        help="Max rows to sample per file (0=all)")
    args = parser.parse_args()

    max_rows = args.max_rows  # 0 means unlimited (iter_tsv handles 0 as no limit)

    registered_prefixes = load_registered_prefixes()
    metpo_curies = load_metpo_curies()

    if metpo_curies:
        print(f"  Loaded {len(metpo_curies)} METPO CURIEs from ontologies output", file=sys.stderr)
    else:
        print("  Warning: No METPO CURIEs loaded (run ontologies transform first)", file=sys.stderr)

    results = []

    if args.merged:
        targets = [("merged", MERGED_DIR)]
    elif args.transform:
        targets = [(args.transform, TRANSFORMS_DIR / args.transform)]
    else:
        targets = sorted(
            [(d.name, d) for d in TRANSFORMS_DIR.iterdir() if d.is_dir()],
            key=lambda x: x[0],
        )

    for name, path in targets:
        print(f"  Reviewing {name}...", file=sys.stderr)
        result = review_transform(name, path, max_rows, registered_prefixes, metpo_curies, args.verbose)
        results.append(result)

    if args.format == "json":
        # Serialize findings
        output = []
        for r in results:
            output.append({
                "transform": r["name"],
                "errors": r["errors"],
                "warnings": r["warnings"],
                "nodes": [{"severity": f.severity, "check": f.check, "message": f.message}
                          for f in r["nodes"]],
                "edges": [{"severity": f.severity, "check": f.check, "message": f.message}
                          for f in r["edges"]],
            })
        print(json.dumps(output, indent=2))
    elif args.format == "md":
        print(format_text(results, format_md=True))
    else:
        print(format_text(results, format_md=False))


if __name__ == "__main__":
    main()
