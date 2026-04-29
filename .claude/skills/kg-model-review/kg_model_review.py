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
from datetime import date, datetime
from pathlib import Path


def _save_review_artifact(content: str, scope: str, ext: str = "txt") -> Path:
    """Save review output to <skill_dir>/reviews/<YYYYMMDD_HHMMSS>_<scope>.<ext>."""
    out_dir = Path(__file__).parent / "reviews"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w.-]+", "_", scope).strip("_") or "review"
    path = out_dir / f"{ts}_{safe}.{ext}"
    path.write_text(content, encoding="utf-8")
    return path

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

# ── Biolink Model (authoritative) ─────────────────────────────────────────────
# Source of truth: the `bmt` (Biolink Model Toolkit) package, which loads the
# published biolink-model YAML schema. Previously these were hand-maintained
# lists that drifted from the model. We still layer a small KG-Microbe
# extension whitelist on top for (a) KG-Microbe-specific classes that aren't
# in upstream biolink, (b) deprecated classes we intentionally still emit
# (e.g. biolink:ChemicalSubstance for CHEBI normalization), and (c) non-biolink
# OWL/RDFS structural predicates used by the ontologies transform.

# Categories we emit that are NOT covered by `bmt.get_all_classes`.
# Most "unusual" biolink classes (TaxonomicRank, OntologyClass,
# MacromolecularMachineMixin, GenomicEntity, ActivityAndBehavior) ARE defined
# in biolink — they just aren't `named thing` descendants — so `get_all_classes`
# below captures them without a whitelist entry. A few classes were removed
# upstream but still flow through via OAK/ontology import closures.
KGMICROBE_EXTENSION_CATEGORIES = {
    "biolink:GrowthMedium",           # KG-Microbe native extension
    "biolink:SequenceFeature",        # removed upstream; OAK output (NCBITaxon, GO)
    "biolink:EnvironmentalMaterial",  # removed upstream; OAK output (ENVO)
}

# Predicates we emit that are NOT biolink slots — structural/OWL predicates.
STRUCTURAL_PREDICATES = {
    "rdfs:subPropertyOf",
    "owl:inverseOf",
    "rdf:type",
}

# KG-Microbe-only predicates absent from upstream biolink (intentional emits).
KGMICROBE_EXTENSION_PREDICATES = {
    "biolink:positively_regulates",  # emitted by some transforms; not in current biolink
    "biolink:negatively_regulates",
}


def _load_biolink_sets():
    """Load authoritative biolink category + predicate sets from bmt.

    Returns (categories, predicates, biolink_version). If bmt is unavailable,
    returns (None, None, None) and the caller falls back to a minimal
    hardcoded set.
    """
    try:
        import bmt
        t = bmt.Toolkit()
        # Union of (a) concrete classes via get_all_classes — includes things
        # like TaxonomicRank, OntologyClass, SequenceFeature that aren't
        # `named thing` descendants, and (b) descendants(named thing) for
        # completeness. get_all_classes alone can miss some mixin-derived
        # classes depending on bmt version.
        cats = set(t.get_all_classes(formatted=True))
        cats |= set(t.get_descendants("named thing", formatted=True, reflexive=True))
        # get_all_slots is broader than descendants(related_to) — covers
        # has_attribute, xxx_match, etc. that aren't in the related_to tree.
        preds = set(t.get_all_slots(formatted=True))
        return cats, preds, t.get_model_version()
    except Exception:
        return None, None, None


_BIOLINK_CATS, _BIOLINK_PREDS, BIOLINK_VERSION = _load_biolink_sets()

if _BIOLINK_CATS is not None:
    VALID_CATEGORIES = _BIOLINK_CATS | KGMICROBE_EXTENSION_CATEGORIES
    VALID_PREDICATES = _BIOLINK_PREDS | STRUCTURAL_PREDICATES | KGMICROBE_EXTENSION_PREDICATES
else:
    # Minimal fallback — bmt missing; the skill still runs but with a small
    # curated set. This path should be rare (bmt is in project deps).
    VALID_CATEGORIES = {"biolink:NamedThing", "biolink:OrganismTaxon", "biolink:ChemicalEntity",
                        "biolink:Attribute", "biolink:BiologicalProcess"} | KGMICROBE_EXTENSION_CATEGORIES
    VALID_PREDICATES = {"biolink:related_to", "biolink:has_phenotype", "biolink:capable_of",
                        "biolink:produces", "biolink:subclass_of",
                        "biolink:same_as"} | STRUCTURAL_PREDICATES | KGMICROBE_EXTENSION_PREDICATES

# Deprecated categories — INFO-level flag to encourage migration where
# practical. KG-Microbe transforms now emit the replacements directly;
# `replace_deprecated_categories` normalizes any stragglers.
DEPRECATED_CATEGORIES = {
    "biolink:ChemicalSubstance": "biolink:ChemicalEntity",
    "biolink:Macromolecule": "biolink:MacromolecularComplex",
    "biolink:MacromolecularMachineMixin": "biolink:Protein or biolink:Gene",
    "biolink:ActivityAndBehavior": "biolink:BiologicalProcess or biolink:MolecularActivity",
}

# METPO:2000xxx predicates are domain-specific refinements of biolink predicates
# (e.g. METPO:2000003 "builds acid from" is more specific than biolink:produces).
try:
    from kg_microbe.utils.metpo_predicates import METPO_TO_BIOLINK_PREDICATE
    VALID_PREDICATES |= set(METPO_TO_BIOLINK_PREDICATE.keys())
except ImportError:
    pass

# Predicate → (allowed_subject_categories, allowed_object_categories) constraint.
# Each set lists biolink category CURIEs; an edge's subject/object is compliant if
# its declared category is either in the set or (via bmt) a descendant of any
# member. Violations surface as WARNING under the new "DomainRange" check bucket.
# The map covers: (a) every biolink predicate KG-Microbe emits with a non-trivial
# domain or range narrower than NamedThing, and (b) every METPO:2000xxx predicate
# KG-Microbe emits — METPO domain/range is not machine-readable yet, so these are
# hand-curated from metpo.json labels. Keys are intentionally narrow; predicates
# absent here are skipped (no false positives from permissive biolink defaults).
PREDICATE_DOMAIN_RANGE = {
    # ── Biolink ─────────────────────────────────────────────────────────────
    "biolink:consumes":       ({"biolink:OrganismTaxon", "biolink:BiologicalEntity"}, {"biolink:ChemicalEntity"}),
    "biolink:produces":       ({"biolink:OrganismTaxon", "biolink:BiologicalEntity"}, {"biolink:ChemicalEntity"}),
    "biolink:located_in":     ({"biolink:BiologicalEntity", "biolink:Protein", "biolink:Gene"}, {"biolink:NamedThing"}),
    "biolink:has_phenotype":  ({"biolink:BiologicalEntity", "biolink:OrganismTaxon"},  {"biolink:PhenotypicFeature", "biolink:Attribute", "biolink:OntologyClass"}),
    "biolink:capable_of":     ({"biolink:OrganismTaxon", "biolink:BiologicalEntity"}, {"biolink:BiologicalProcess", "biolink:MolecularActivity", "biolink:OntologyClass"}),
    "biolink:has_chemical_role": ({"biolink:ChemicalEntity"}, {"biolink:ChemicalRole", "biolink:OntologyClass"}),
    "biolink:associated_with_resistance_to":  ({"biolink:OrganismTaxon", "biolink:BiologicalEntity"}, {"biolink:ChemicalEntity"}),
    "biolink:associated_with_sensitivity_to": ({"biolink:OrganismTaxon", "biolink:BiologicalEntity"}, {"biolink:ChemicalEntity"}),
    "biolink:enables":        ({"biolink:Protein", "biolink:Gene", "biolink:MacromolecularComplex"}, {"biolink:MolecularActivity", "biolink:BiologicalProcess", "biolink:OntologyClass"}),
    "biolink:enabled_by":     ({"biolink:MolecularActivity", "biolink:BiologicalProcess", "biolink:OntologyClass"}, {"biolink:Protein", "biolink:Gene", "biolink:MacromolecularComplex"}),
    # ── METPO:2000xxx (organism → chemical / pathway / medium) ──────────────
    "METPO:2000002": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # assimilates
    "METPO:2000003": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # builds acid from
    "METPO:2000004": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # builds base from
    "METPO:2000005": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # builds gas from
    "METPO:2000006": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # uses as carbon source
    "METPO:2000007": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity", "biolink:EnvironmentalMaterial"}),  # degrades — covers crude oil and other ENVO materials
    "METPO:2000009": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # uses as electron donor
    "METPO:2000010": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # uses as energy source
    "METPO:2000011": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # ferments
    "METPO:2000013": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # hydrolyzes
    "METPO:2000014": ({"biolink:OrganismTaxon"}, {"biolink:ChemicalEntity"}),  # uses as nitrogen source
    "METPO:2000103": ({"biolink:OrganismTaxon"}, {"biolink:BiologicalProcess", "biolink:MolecularActivity", "biolink:OntologyClass"}),  # capable of
    "METPO:2000517": ({"biolink:OrganismTaxon"}, {"biolink:GrowthMedium"}),  # grows in
    "METPO:2000518": ({"biolink:OrganismTaxon"}, {"biolink:GrowthMedium"}),  # does not grow in
}

# ── Standard known CURIE prefixes ─────────────────────────────────────────────
STANDARD_PREFIXES = {
    "NCBITaxon", "CHEBI", "GO", "EC", "RO", "METPO", "biolink",
    "FOODON", "UBERON", "HP", "MONDO", "ENVO", "infores", "semapv",
    "kgmicrobe.activity", "kgmicrobe.trait", "kgmicrobe.compound",
    "kgmicrobe.assay", "kgmicrobe.pathway", "kgmicrobe.carbon_substrate",
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
    """Yield dicts from a TSV member inside a .tar.gz archive.

    Accepts member_name either at the archive root or nested under a single
    top-level directory (e.g. `20260422_nometatraits/merged-kg_nodes.tsv`).
    """
    count = 0
    with tarfile.open(tar_path, "r:gz") as tf:
        member = None
        try:
            member = tf.getmember(member_name)
        except KeyError:
            for m in tf.getmembers():
                if m.name.endswith("/" + member_name) or m.name == member_name:
                    member = m
                    break
        if member is None:
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


# Cache of bmt-expanded allowed-category sets per predicate, so every edge
# lookup is a plain set membership test.
_DR_EXPANDED_CACHE: dict = {}


def _expand_allowed(cats: set) -> set:
    """Return `cats` unioned with all bmt descendants of each member.

    Falls back to the literal set when bmt is unavailable.
    """
    key = frozenset(cats)
    if key in _DR_EXPANDED_CACHE:
        return _DR_EXPANDED_CACHE[key]
    expanded = set(cats)
    try:
        import bmt
        t = bmt.Toolkit()
        for cat in cats:
            slug = cat.replace("biolink:", "")
            # bmt expects human-readable names; convert CamelCase → "space-separated"
            # only if needed — get_descendants accepts both CURIE and snake forms.
            try:
                descendants = t.get_descendants(slug, formatted=True, reflexive=True)
                expanded |= set(descendants)
            except Exception:
                # Unknown CURIE (e.g. KG-Microbe extension like biolink:GrowthMedium)
                continue
    except Exception:
        pass
    _DR_EXPANDED_CACHE[key] = expanded
    return expanded


def check_domain_range(node_rows: list, edge_rows: list, verbose: bool) -> list:
    """Check that each edge's subject/object categories match the predicate's domain/range.

    Violations are grouped by (predicate, side, observed-category); only
    predicates present in ``PREDICATE_DOMAIN_RANGE`` are checked.
    """
    findings: list = []
    if not edge_rows:
        return findings

    id_to_cats: dict = {}
    for r in node_rows:
        nid = r.get("id", "")
        raw = r.get("category") or ""
        cats = tuple(c.strip() for c in raw.split("|") if c.strip())
        if nid and cats:
            id_to_cats[nid] = cats

    # group violations: (predicate, side, observed_cat) -> [example subject→object strings]
    violations: dict = defaultdict(list)
    checked_edges = 0
    constrained_preds = set(PREDICATE_DOMAIN_RANGE.keys())
    for e in edge_rows:
        pred = (e.get("predicate") or "").strip()
        if pred not in constrained_preds:
            continue
        checked_edges += 1
        domain_allowed, range_allowed = PREDICATE_DOMAIN_RANGE[pred]
        domain_ok = _expand_allowed(domain_allowed)
        range_ok = _expand_allowed(range_allowed)

        subj = e.get("subject", "")
        obj = e.get("object", "")
        subj_cats = id_to_cats.get(subj)
        obj_cats = id_to_cats.get(obj)

        # An edge is compliant if ANY of the node's categories is in the allowed
        # set (categories are pipe-delimited; we expand each side via bmt
        # descendants in _expand_allowed). Report against the primary (first)
        # category for grouping purposes.
        if subj_cats and not any(c in domain_ok for c in subj_cats):
            violations[(pred, "subject", subj_cats[0])].append(f"{subj} → {obj}")
        if obj_cats and not any(c in range_ok for c in obj_cats):
            violations[(pred, "object", obj_cats[0])].append(f"{subj} → {obj}")

    if not checked_edges:
        return findings  # nothing constrained in this batch

    if violations:
        total_bad = sum(len(v) for v in violations.values())
        ranked = sorted(violations.items(), key=lambda kv: -len(kv[1]))
        examples = []
        for (pred, side, cat), exs in ranked[:5]:
            examples.append(f"{pred} ({side}={cat}): {len(exs)} edges, e.g. {exs[0]}")
        findings.append(
            Finding(
                "WARNING",
                "DomainRange",
                f"{total_bad} edges violate predicate domain/range across {len(violations)} distinct constraints",
                examples if verbose else [],
            )
        )
    else:
        findings.append(
            Finding("INFO", "DomainRange", f"Domain/range OK across {checked_edges:,} constrained edges")
        )
    return findings


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

    deprecated_cats = {c: n for c, n in cat_counts.items() if c in DEPRECATED_CATEGORIES}
    # Deprecated categories are surfaced separately; don't double-flag them as "unknown".
    unknown_cats = {c: n for c, n in cat_counts.items()
                    if c not in VALID_CATEGORIES and c not in DEPRECATED_CATEGORIES}
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
                     verbose: bool, strict_kgx: bool = False) -> dict:
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
        result["edges"].extend(check_domain_range(nodes_rows, edges_rows, verbose))
        if strict_kgx:
            # Strict validation runs against a loose TSV — extract if needed
            for kind, member in (("nodes", "merged-kg_nodes.tsv"), ("edges", "merged-kg_edges.tsv")):
                extracted = transform_dir / member
                if not extracted.exists():
                    with tarfile.open(tar_path, "r:gz") as tf:
                        tf.extract(member, transform_dir)
                result[kind].extend(run_kgx_strict(extracted, kind, max_rows))
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
            result["edges"].extend(check_domain_range(all_node_rows, all_edge_rows, verbose))
            return _tally(result)
        # Empty directory (transform not run) — skip silently
        result["nodes"] = [Finding("INFO", "KGX", "No output files found (transform not run or no data)")]
        result["edges"] = []
        return result

    node_rows = list(iter_tsv(nodes_path, max_rows)) if nodes_path.exists() else []
    edge_rows = list(iter_tsv(edges_path, max_rows)) if edges_path.exists() else []
    result["nodes"] = (
        check_nodes_rows(node_rows, max_rows, registered_prefixes, metpo_curies, verbose)
        if node_rows else [Finding("ERROR", "KGX", f"nodes.tsv not found: {nodes_path}")]
    )
    result["edges"] = (
        check_edges_rows(edge_rows, max_rows, registered_prefixes, metpo_curies, verbose)
        if edge_rows else [Finding("ERROR", "KGX", f"edges.tsv not found: {edges_path}")]
    )
    result["edges"].extend(check_domain_range(node_rows, edge_rows, verbose))
    if strict_kgx:
        if nodes_path.exists():
            result["nodes"].extend(run_kgx_strict(nodes_path, "nodes", max_rows))
        if edges_path.exists():
            result["edges"].extend(run_kgx_strict(edges_path, "edges", max_rows))
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


_KGX_MULTIVALUED_NODE_FIELDS = {"category", "synonym", "xref", "provided_by"}
_KGX_MULTIVALUED_EDGE_FIELDS = {"category", "publications", "provided_by"}


def _prepare_kgx_row(row: dict, multi_fields: set) -> dict:
    """Convert pipe-separated string fields to lists as kgx.Validator expects."""
    out = dict(row)
    for k in multi_fields:
        v = out.get(k)
        if isinstance(v, str) and v:
            out[k] = [x.strip() for x in v.split("|") if x.strip()]
    return out


def run_kgx_strict(path: Path, kind: str, max_rows: int) -> list:
    """Run authoritative KGX validation against a TSV using kgx.validator.

    Uses kgx's `Validator` on per-row dicts (analyse_node / analyse_edge).
    Returns aggregated Finding list. Only invoked under --strict-kgx because
    it's slower and requires the kgx package.
    """
    findings = []
    try:
        from kgx.validator import Validator  # lazy import
    except ImportError:
        findings.append(Finding("INFO", "KGX-strict",
                                "--strict-kgx requested but `kgx` package not installed"))
        return findings
    v = Validator()
    v.clear_errors()
    multi_fields = _KGX_MULTIVALUED_NODE_FIELDS if kind == "nodes" else _KGX_MULTIVALUED_EDGE_FIELDS
    sample_count = 0
    for row in iter_tsv(path, max_rows):
        prepared = _prepare_kgx_row(row, multi_fields)
        if kind == "nodes":
            v.analyse_node(prepared.get("id", ""), prepared)
        else:
            v.analyse_edge(prepared.get("subject", ""),
                           prepared.get("object", ""),
                           None, prepared)
        sample_count += 1

    # kgx Validator.get_errors() returns nested dict:
    #   {severity: {error_type: {message: [offending_ids]}}}
    err_tree = v.get_errors() or {}
    any_found = False
    for severity, types in err_tree.items():
        for err_type, msgs in (types or {}).items():
            # Aggregate across all messages under this (severity, error_type)
            total = sum(len(ids) for ids in msgs.values())
            if total == 0:
                continue
            any_found = True
            # Pick up to 3 example (message, id) pairs for context
            examples = []
            for msg, ids in msgs.items():
                for ident in ids[:2]:
                    examples.append(f"{msg} [{ident}]")
                    if len(examples) >= 3:
                        break
                if len(examples) >= 3:
                    break
            findings.append(Finding(
                "WARNING" if severity == "WARNING" else "ERROR",
                "KGX-strict",
                f"{total} {err_type} ({kind})",
                examples,
            ))
    if not any_found:
        findings.append(Finding("INFO", "KGX-strict",
                                f"kgx.Validator clean ({sample_count:,} {kind} rows)"))
    return findings


def main():
    parser = argparse.ArgumentParser(description="KG-Microbe knowledge modeling review")
    parser.add_argument("--transform", help="Review specific transform (default: all)")
    parser.add_argument("--merged", action="store_true", help="Review merged KG instead of transforms")
    parser.add_argument("--format", choices=["text", "md", "json"], default="text")
    parser.add_argument("--verbose", action="store_true", help="Show example violations")
    parser.add_argument("--max-rows", type=int, default=100_000,
                        help="Max rows to sample per file (0=all)")
    parser.add_argument("--strict-kgx", action="store_true",
                        help="Additionally run kgx.validator.Validator (authoritative KGX spec check)")
    parser.add_argument("--no-save", action="store_true",
                        help="Skip writing a timestamped artifact under <skill>/reviews/")
    args = parser.parse_args()

    max_rows = args.max_rows  # 0 means unlimited (iter_tsv handles 0 as no limit)

    if args.merged and max_rows == 0:
        print(
            "  Error: --max-rows 0 with --merged would materialize the full nodes+edges "
            "tarball in memory and is likely to OOM on real releases. "
            "Specify a finite --max-rows (e.g. 1000000) for merged review.",
            file=sys.stderr,
        )
        sys.exit(2)

    registered_prefixes = load_registered_prefixes()
    metpo_curies = load_metpo_curies()

    if BIOLINK_VERSION:
        print(f"  Biolink Model {BIOLINK_VERSION} loaded "
              f"({len(_BIOLINK_CATS)} categories, {len(_BIOLINK_PREDS)} predicates) "
              f"+ {len(KGMICROBE_EXTENSION_CATEGORIES)} KG-Microbe extensions",
              file=sys.stderr)
    else:
        print("  Warning: bmt unavailable — using fallback biolink set", file=sys.stderr)

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
        result = review_transform(name, path, max_rows, registered_prefixes, metpo_curies,
                                  args.verbose, strict_kgx=args.strict_kgx)
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
        rendered = json.dumps(output, indent=2)
        ext = "json"
    elif args.format == "md":
        rendered = format_text(results, format_md=True)
        ext = "md"
    else:
        rendered = format_text(results, format_md=False)
        ext = "txt"
    print(rendered)

    if not args.no_save:
        if args.merged:
            scope = "merged"
        elif args.transform:
            scope = args.transform
        else:
            scope = "all-transforms"
        saved = _save_review_artifact(rendered, scope, ext=ext)
        print(f"  Saved review to {saved}", file=sys.stderr)


if __name__ == "__main__":
    main()
