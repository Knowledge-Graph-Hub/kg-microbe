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
    "kgmicrobe.ingredient",  # mediadive: un-mapped ingredient placeholders
    "MICRO",                 # Microbiology Ontology (mediadive ingredients)
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
    # Cross-references appearing in mapping TSVs (isolation_source_to_ontology
    # uses these when nothing in the OBO Foundry tier fits): MeSH for medical
    # subject headings, NCIT for clinical/biomedical, SNOMED for clinical,
    # PRIDE for proteomics studies, ExO for exposure ontology, VariO for
    # variation ontology.
    "mesh", "MESH", "PRIDE", "ExO", "VariO", "SNOMED", "BTO", "AGRO", "FAO",
    "OBI", "AEO", "GENEPIO", "PCO", "UO",
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


# ── Mapping-file review ───────────────────────────────────────────────────────
# Curation artifacts under `mappings/` and `kg_microbe/transform_utils/*/mappings/`
# drive transform-side lookups and are also published upstream to MIM /
# CultureBotAI / CultureBotHT. They are reviewed with their own validators
# because they are not KGX nodes/edges files.

MAPPINGS_DIR_REPO = REPO_ROOT / "mappings"
MAPPINGS_DIR_METATRAITS = REPO_ROOT / "kg_microbe" / "transform_utils" / "metatraits" / "mappings"

# Canonical mapping schema shared across the metatraits curation TSVs
# (chemical, enzyme, metpo_alias, pathway, phenotype). Every row in a Group A
# file MUST have these columns; missing columns are an ERROR.
CANONICAL_MAPPING_COLS = {
    "subject_label",
    "subject_label_normalized",
    "object_id",
    "object_label",
    "object_source",
    "predicate_id",
    "confidence",
    "mapping_justification",
    "curator",
    "source_dataset",
    "notes",
    "verified_date",
}

# Files known to follow CANONICAL_MAPPING_COLS (Group A).
# Maps filename → directory ('metatraits' or 'repo'). The metatraits group
# lives under kg_microbe/transform_utils/metatraits/mappings/; the repo group
# lives at the top-level mappings/.
GROUP_A_CANONICAL = {
    "chemical_mappings.tsv": "metatraits",
    "enzyme_mappings.tsv": "metatraits",
    "metpo_alias_mappings.tsv": "metatraits",
    "pathway_mappings.tsv": "metatraits",
    "phenotype_mappings.tsv": "metatraits",
    "isolation_source_to_ontology.tsv": "repo",
}

# Off-schema files with bespoke columns (Group B). Each gets its own validator.
GROUP_B_BESPOKE = {
    "enzyme_name_to_go.tsv": {"enzyme_name", "go_id", "go_label", "ec_number", "notes"},
    "special_chemical_mappings.tsv": {
        "trait_pattern", "chemical_name", "ontology_id",
        "ontology_name", "predicate", "category", "notes",
    },
}

# Allowed values for canonical confidence column.
CANONICAL_CONFIDENCE_VALUES = {"high", "medium", "low"}

# Allowed predicate prefixes in canonical mapping_justification / predicate_id.
ALLOWED_JUSTIFICATION_PREFIX = ("semapv:",)
ALLOWED_PREDICATE_ID_PREFIX = ("skos:",)


def _read_tsv_rows(path: Path, comment_prefix: str = None) -> tuple:
    """Return (header, rows) from a TSV. Skips lines beginning with comment_prefix.

    Used for both plain TSVs and SSSOM (which has `# curie_map:` YAML header).
    """
    if not path.exists():
        return None, []
    rows: list = []
    header: list = None
    opener = gzip.open if path.suffix == ".gz" else open
    mode = "rt" if path.suffix == ".gz" else "r"
    with opener(path, mode, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter="\t")
        for row in reader:
            if not row:
                continue
            if comment_prefix and row[0].startswith(comment_prefix):
                continue
            if header is None:
                header = row
                continue
            rows.append(dict(zip(header, row)))
    return header, rows


def _read_sssom_metadata(path: Path) -> dict:
    """Parse the YAML metadata block from an SSSOM TSV (lines starting with `#`)."""
    if not path.exists():
        return {}
    yaml_lines: list = []
    opener = gzip.open if path.suffix == ".gz" else open
    mode = "rt" if path.suffix == ".gz" else "r"
    with opener(path, mode, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("#"):
                break
            # Strip exactly the SSSOM "# " prefix (or just "#") so YAML indentation
            # is preserved. lstrip() would collapse the indented map entries under
            # `curie_map:` into a flat list, breaking the parse.
            if line.startswith("# "):
                yaml_lines.append(line[2:])
            else:
                yaml_lines.append(line[1:])
    if not yaml_lines:
        return {}
    try:
        return yaml.safe_load("".join(yaml_lines)) or {}
    except yaml.YAMLError:
        return {}


def check_canonical_mapping_file(path: Path, registered_prefixes: set,
                                 metpo_curies: set, ontology_ids: set,
                                 verbose: bool) -> tuple:
    """Validate a Group A canonical mapping TSV. Returns (findings, rows)."""
    findings: list = []
    header, rows = _read_tsv_rows(path)
    if header is None:
        findings.append(Finding("ERROR", "Mapping", f"file not found: {path}"))
        return findings, []
    if not rows:
        findings.append(Finding("WARNING", "Mapping", f"{path.name} is empty"))
        return findings, []

    # Schema: required columns
    missing = CANONICAL_MAPPING_COLS - set(header)
    if missing:
        findings.append(Finding("ERROR", "Mapping",
                                f"{path.name} missing canonical columns: {sorted(missing)}"))
    else:
        findings.append(Finding("INFO", "Mapping",
                                f"{path.name} canonical schema present ({len(rows)} rows)"))

    # Per-row checks
    bad_curies: list = []
    bad_pred: list = []
    bad_justification: list = []
    bad_confidence: list = []
    deprecated_targets: list = []
    unregistered_prefixes: dict = defaultdict(int)
    missing_metpo: list = []
    missing_ontology_ref: list = []
    blank_required: list = []

    for r in rows:
        subj = (r.get("subject_label") or "").strip()
        oid = (r.get("object_id") or "").strip()
        pred = (r.get("predicate_id") or "").strip()
        just = (r.get("mapping_justification") or "").strip()
        conf = (r.get("confidence") or "").strip().lower()

        # subject_label is always required.
        if not subj:
            blank_required.append(f"{path.name}: blank subject_label")
            continue

        # Rows with blank object_id are intentionally-unmapped curation
        # candidates (e.g. isolation_source residuals awaiting term mints).
        # Skip the per-row mapping checks for them — the unmapped state is
        # legal as long as object_id, object_label, predicate_id, etc. are
        # ALL blank (no half-populated rows).
        if not oid:
            for col in ("object_label", "object_source", "predicate_id",
                        "confidence", "mapping_justification"):
                if (r.get(col) or "").strip():
                    blank_required.append(
                        f"{path.name}: row for subject={subj!r} has blank object_id "
                        f"but non-blank {col}"
                    )
                    break
            continue

        # Mapped rows must have predicate_id + mapping_justification populated.
        for col in ("predicate_id", "mapping_justification"):
            if not (r.get(col) or "").strip():
                blank_required.append(
                    f"{path.name}: blank {col} for subject={subj!r} (object_id={oid})"
                )
                break

        if oid and not CURIE_RE.match(oid):
            bad_curies.append(f"{subj} → {oid}")
        if oid:
            prefix = get_prefix(oid)
            if prefix and prefix not in registered_prefixes:
                unregistered_prefixes[prefix] += 1
            # Deprecated biolink targets
            if oid in DEPRECATED_CATEGORIES:
                deprecated_targets.append(f"{subj} → {oid}")
            # METPO refs must exist
            if oid.startswith("METPO:") and metpo_curies and oid not in metpo_curies:
                missing_metpo.append(f"{subj} → {oid}")
            # Ontology-id resolvability against ontologies/nodes.tsv
            if ontology_ids and oid not in ontology_ids and not oid.startswith("kgmicrobe."):
                # only flag CHEBI/GO/EC/RO/UBERON/ENVO/HP/MONDO/PATO/PR/CL/FOODON/NCBITaxon
                if get_prefix(oid) in {"CHEBI", "GO", "EC", "RO", "UBERON", "ENVO",
                                       "HP", "MONDO", "PATO", "PR", "CL", "FOODON",
                                       "NCBITaxon", "OMP"}:
                    missing_ontology_ref.append(f"{subj} → {oid}")
        if pred and not pred.startswith(ALLOWED_PREDICATE_ID_PREFIX):
            bad_pred.append(f"{subj}: predicate_id={pred!r}")
        if just and not just.startswith(ALLOWED_JUSTIFICATION_PREFIX):
            bad_justification.append(f"{subj}: mapping_justification={just!r}")
        if conf and conf not in CANONICAL_CONFIDENCE_VALUES:
            bad_confidence.append(f"{subj}: confidence={conf!r}")

    if blank_required:
        findings.append(Finding("ERROR", "Mapping",
                                f"{path.name}: {len(blank_required)} rows with blank required field",
                                blank_required[:5] if verbose else []))
    if bad_curies:
        findings.append(Finding("ERROR", "Mapping",
                                f"{path.name}: {len(bad_curies)} non-CURIE object_id values",
                                bad_curies[:5] if verbose else []))
    if bad_pred:
        findings.append(Finding("WARNING", "Mapping",
                                f"{path.name}: {len(bad_pred)} predicate_id not in skos: namespace",
                                bad_pred[:5] if verbose else []))
    if bad_justification:
        findings.append(Finding("WARNING", "Mapping",
                                f"{path.name}: {len(bad_justification)} mapping_justification not in semapv:",
                                bad_justification[:5] if verbose else []))
    if bad_confidence:
        findings.append(Finding("WARNING", "Mapping",
                                f"{path.name}: {len(bad_confidence)} unknown confidence values",
                                bad_confidence[:5] if verbose else []))
    if deprecated_targets:
        findings.append(Finding("INFO", "Mapping",
                                f"{path.name}: {len(deprecated_targets)} rows target deprecated biolink classes",
                                deprecated_targets[:5] if verbose else []))
    if unregistered_prefixes:
        findings.append(Finding("WARNING", "Prefix",
                                f"{path.name}: unregistered object_id prefixes: "
                                f"{dict(unregistered_prefixes)}"))
    if missing_metpo:
        findings.append(Finding("WARNING", "METPO",
                                f"{path.name}: {len(missing_metpo)} METPO refs not in ontology output",
                                missing_metpo[:5] if verbose else []))
    if missing_ontology_ref:
        findings.append(Finding("WARNING", "Mapping",
                                f"{path.name}: {len(missing_ontology_ref)} object_ids not resolvable "
                                "in ontologies output (may indicate stale or upstream-only IDs)",
                                missing_ontology_ref[:5] if verbose else []))

    return findings, rows


def check_bespoke_mapping_file(path: Path, expected_cols: set, verbose: bool) -> tuple:
    """Group B: validate that bespoke-schema files have expected columns + plausible IDs."""
    findings: list = []
    header, rows = _read_tsv_rows(path)
    if header is None:
        findings.append(Finding("ERROR", "Mapping", f"file not found: {path}"))
        return findings, []
    if not rows:
        findings.append(Finding("WARNING", "Mapping", f"{path.name} is empty"))
        return findings, []
    missing = expected_cols - set(header)
    if missing:
        findings.append(Finding("ERROR", "Mapping",
                                f"{path.name} missing expected columns: {sorted(missing)}"))
    else:
        findings.append(Finding("INFO", "Mapping",
                                f"{path.name} bespoke schema present ({len(rows)} rows)"))

    # Common sense: any *_id column should look like a CURIE
    bad: list = []
    for r in rows:
        for col in ("go_id", "ontology_id"):
            v = (r.get(col) or "").strip()
            if v and not CURIE_RE.match(v):
                bad.append(f"{path.name}: {col}={v!r}")
    if bad:
        findings.append(Finding("ERROR", "Mapping",
                                f"{path.name}: {len(bad)} non-CURIE id values",
                                bad[:5] if verbose else []))

    return findings, rows


def check_unmapped_queue(path: Path, verbose: bool) -> tuple:
    """Validate the `mediadive_unmapped_ingredients_to_curate.tsv` queue."""
    findings: list = []
    header, rows = _read_tsv_rows(path)
    if header is None:
        findings.append(Finding("ERROR", "Mapping", f"file not found: {path}"))
        return findings, []
    expected = {"id", "preferred_term", "mapping_status", "occurrences"}
    missing = expected - set(header or [])
    if missing:
        findings.append(Finding("ERROR", "Mapping",
                                f"{path.name} missing expected columns: {sorted(missing)}"))
        return findings, rows
    statuses: dict = defaultdict(int)
    for r in rows:
        statuses[(r.get("mapping_status") or "").strip() or "BLANK"] += 1
    findings.append(Finding("INFO", "Mapping",
                            f"{path.name}: {len(rows)} rows; status counts: {dict(statuses)}"))
    return findings, rows


def check_culturebotai_reviewed(path: Path, verbose: bool) -> tuple:
    """Validate culturebotai_reviewed_ingredients.tsv (Group C audit)."""
    findings: list = []
    header, rows = _read_tsv_rows(path)
    if header is None:
        findings.append(Finding("INFO", "Mapping", f"{path.name} not present"))
        return findings, []
    expected = {"ingredient_name", "occurrence_count", "chebi_id", "mapping_status"}
    missing = expected - set(header or [])
    if missing:
        findings.append(Finding("WARNING", "Mapping",
                                f"{path.name} missing expected columns: {sorted(missing)}"))
    statuses: dict = defaultdict(int)
    bad_chebi: list = []
    for r in rows:
        statuses[(r.get("mapping_status") or "").strip() or "BLANK"] += 1
        cid = (r.get("chebi_id") or "").strip()
        if cid and not CURIE_RE.match(cid):
            bad_chebi.append(f"{r.get('ingredient_name')}: chebi_id={cid!r}")
    findings.append(Finding("INFO", "Mapping",
                            f"{path.name}: {len(rows)} rows; status counts: {dict(statuses)}"))
    if bad_chebi:
        findings.append(Finding("WARNING", "Mapping",
                                f"{path.name}: {len(bad_chebi)} non-CURIE chebi_id values",
                                bad_chebi[:5] if verbose else []))
    return findings, rows


def check_sssom_file(path: Path, registered_prefixes: set, verbose: bool) -> tuple:
    """Validate an SSSOM TSV: metadata block + per-row predicate/object format."""
    findings: list = []
    if not path.exists():
        findings.append(Finding("INFO", "Mapping", f"{path.name} not present"))
        return findings, []

    meta = _read_sssom_metadata(path)
    if not meta:
        findings.append(Finding("WARNING", "SSSOM",
                                f"{path.name}: missing or unparseable YAML metadata block"))
    else:
        # Required SSSOM fields per spec.
        required_meta = {"curie_map", "mapping_set_id"}
        missing_meta = required_meta - set(meta.keys())
        if missing_meta:
            findings.append(Finding("WARNING", "SSSOM",
                                    f"{path.name}: metadata missing required keys: "
                                    f"{sorted(missing_meta)}"))
        else:
            findings.append(Finding("INFO", "SSSOM",
                                    f"{path.name}: metadata block valid ({len(meta)} keys)"))

    header, rows = _read_tsv_rows(path, comment_prefix="#")
    if not rows:
        findings.append(Finding("WARNING", "SSSOM", f"{path.name}: no data rows"))
        return findings, []

    required_cols = {"subject_id", "subject_label", "predicate_id", "object_id",
                     "mapping_justification"}
    missing_cols = required_cols - set(header or [])
    if missing_cols:
        findings.append(Finding("ERROR", "SSSOM",
                                f"{path.name}: missing required columns {sorted(missing_cols)}"))
        return findings, rows

    bad_pred: list = []
    bad_obj: list = []
    bad_subj: list = []
    bad_just: list = []
    for r in rows:
        sid = (r.get("subject_id") or "").strip()
        oid = (r.get("object_id") or "").strip()
        pid = (r.get("predicate_id") or "").strip()
        jst = (r.get("mapping_justification") or "").strip()
        if sid and not CURIE_RE.match(sid):
            bad_subj.append(sid)
        if oid and not CURIE_RE.match(oid):
            bad_obj.append(oid)
        if pid and not pid.startswith(("skos:", "owl:", "rdfs:")):
            bad_pred.append(pid)
        if jst and not jst.startswith("semapv:"):
            bad_just.append(jst)

    if bad_subj:
        findings.append(Finding("ERROR", "SSSOM",
                                f"{path.name}: {len(bad_subj)} non-CURIE subject_id",
                                bad_subj[:5] if verbose else []))
    if bad_obj:
        findings.append(Finding("ERROR", "SSSOM",
                                f"{path.name}: {len(bad_obj)} non-CURIE object_id",
                                bad_obj[:5] if verbose else []))
    if bad_pred:
        findings.append(Finding("WARNING", "SSSOM",
                                f"{path.name}: {len(bad_pred)} predicate_id outside skos/owl/rdfs",
                                bad_pred[:5] if verbose else []))
    if bad_just:
        findings.append(Finding("WARNING", "SSSOM",
                                f"{path.name}: {len(bad_just)} mapping_justification outside semapv:",
                                bad_just[:5] if verbose else []))

    findings.append(Finding("INFO", "SSSOM",
                            f"{path.name}: {len(rows)} rows validated"))
    return findings, rows


def load_ontology_ids(max_rows: int = 0) -> set:
    """Load all node IDs from data/transformed/ontologies/*.tsv for cross-file checks."""
    ids: set = set()
    if not ONTOLOGIES_DIR.exists():
        return ids
    for path in ONTOLOGIES_DIR.glob("*_nodes.tsv"):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for r in reader:
                    nid = (r.get("id") or "").strip()
                    if nid:
                        ids.add(nid)
        except Exception:
            continue
    return ids


def cross_file_consistency(canonical_rows_by_file: dict, verbose: bool) -> list:
    """Same subject_label across canonical files mapping to different object_ids."""
    findings: list = []
    label_to_targets: dict = defaultdict(set)
    label_to_files: dict = defaultdict(set)
    for fname, rows in canonical_rows_by_file.items():
        for r in rows:
            label = (r.get("subject_label") or "").strip().lower()
            obj = (r.get("object_id") or "").strip()
            if label and obj:
                label_to_targets[label].add(obj)
                label_to_files[label].add(fname)

    conflicts: list = []
    for label, targets in label_to_targets.items():
        if len(targets) > 1:
            conflicts.append((label, sorted(targets), sorted(label_to_files[label])))

    if conflicts:
        examples = [f"{label!r} → {targets} in {files}"
                    for label, targets, files in conflicts[:5]]
        findings.append(Finding("WARNING", "Mapping",
                                f"{len(conflicts)} subject_labels mapped to >1 object_id "
                                "across canonical files",
                                examples if verbose else []))
    else:
        findings.append(Finding("INFO", "Mapping",
                                "No cross-file subject_label → object_id conflicts"))
    return findings


def review_mappings(verbose: bool, registered_prefixes: set, metpo_curies: set) -> dict:
    """Run all mapping-file validators and return a unified result dict.

    Result shape mirrors review_transform but uses 'mappings' as the section key:
    {
      "name": "mappings",
      "nodes": [Finding...],   # canonical + bespoke + queue + sssom
      "edges": [Finding...],   # cross-file consistency + curation report
      "errors": int,
      "warnings": int,
      "curation_report": str,  # markdown body for curation upgrade section
    }
    """
    result = {"name": "mappings", "nodes": [], "edges": [], "errors": 0, "warnings": 0}
    ontology_ids = load_ontology_ids()
    canonical_rows_by_file: dict = {}

    # Group A: canonical mapping files
    for fname, location in sorted(GROUP_A_CANONICAL.items()):
        base = MAPPINGS_DIR_METATRAITS if location == "metatraits" else MAPPINGS_DIR_REPO
        path = base / fname
        if not path.exists():
            result["nodes"].append(Finding("INFO", "Mapping", f"{fname} not present"))
            continue
        findings, rows = check_canonical_mapping_file(
            path, registered_prefixes, metpo_curies, ontology_ids, verbose
        )
        result["nodes"].extend(findings)
        canonical_rows_by_file[fname] = rows

    # Group B: bespoke schema files
    for fname, expected in GROUP_B_BESPOKE.items():
        path = MAPPINGS_DIR_METATRAITS / fname
        if not path.exists():
            result["nodes"].append(Finding("INFO", "Mapping", f"{fname} not present"))
            continue
        findings, _ = check_bespoke_mapping_file(path, expected, verbose)
        result["nodes"].extend(findings)

    # Group C: queues / audit / proposals (under repo /mappings/)
    queue_path = MAPPINGS_DIR_REPO / "mediadive_unmapped_ingredients_to_curate.tsv"
    f, queue_rows = check_unmapped_queue(queue_path, verbose)
    result["nodes"].extend(f)

    cb_path = MAPPINGS_DIR_REPO / "culturebotai_reviewed_ingredients.tsv"
    f, cb_rows = check_culturebotai_reviewed(cb_path, verbose)
    result["nodes"].extend(f)

    # Group D: SSSOM
    sssom_path = MAPPINGS_DIR_REPO / "ingredient_mappings.sssom.tsv"
    f, _ = check_sssom_file(sssom_path, registered_prefixes, verbose)
    result["nodes"].extend(f)

    # Cross-file consistency
    result["edges"].extend(cross_file_consistency(canonical_rows_by_file, verbose))

    # Build curation upgrade report
    result["curation_report"] = build_curation_report(
        canonical_rows_by_file, queue_rows, cb_rows, ontology_ids
    )

    # Tally
    for f in result["nodes"] + result["edges"]:
        if f.severity == "ERROR":
            result["errors"] += 1
        elif f.severity == "WARNING":
            result["warnings"] += 1
    return result


def build_curation_report(canonical_rows_by_file: dict, queue_rows: list,
                          cb_rows: list, ontology_ids: set) -> str:
    """Build a markdown report actionable for upstream curation repos.

    Sections:
      1. Top unmapped ingredients (mediadive queue) by occurrence
      2. Cross-file conflicts (same subject_label, different object_id)
      3. Object IDs not resolvable in ontologies output
      4. Low-confidence canonical rows
      5. Prefix normalization candidates
      6. CultureBotAI review queue summary
    """
    lines: list = ["## Curation upgrade report",
                   "_Targets: CultureBotAI / MIM / CultureBotHT_", ""]

    # 1. Top unmapped queue
    lines.append("### 1. Top unmapped MediaDive ingredients (by occurrence)")
    if queue_rows:
        unmapped = [r for r in queue_rows
                    if (r.get("mapping_status") or "").strip().upper() == "UNMAPPED"]

        def _occ(r):
            try:
                return int((r.get("occurrences") or "0").strip() or "0")
            except ValueError:
                return 0

        unmapped.sort(key=_occ, reverse=True)
        if unmapped:
            lines.append("| ingredient | occurrences | mediadive id | parent ingredient |")
            lines.append("|---|---:|---|---|")
            for r in unmapped[:25]:
                lines.append(
                    f"| {r.get('preferred_term', '').strip()} "
                    f"| {_occ(r)} "
                    f"| {r.get('id', '').strip()} "
                    f"| {r.get('parent_ingredient', '').strip() or '—'} |"
                )
        else:
            lines.append("_All queue rows are MAPPED._")
    else:
        lines.append("_Queue file absent._")
    lines.append("")

    # 2. Conflicts
    label_to_targets: dict = defaultdict(set)
    label_to_files: dict = defaultdict(set)
    for fname, rows in canonical_rows_by_file.items():
        for r in rows:
            label = (r.get("subject_label") or "").strip().lower()
            obj = (r.get("object_id") or "").strip()
            if label and obj:
                label_to_targets[label].add(obj)
                label_to_files[label].add(fname)
    conflicts = [(label, targets, label_to_files[label])
                 for label, targets in label_to_targets.items() if len(targets) > 1]
    lines.append("### 2. Cross-file mapping conflicts")
    if conflicts:
        lines.append("| subject_label | object_ids | files |")
        lines.append("|---|---|---|")
        for label, targets, files in sorted(conflicts):
            lines.append(f"| {label} | {', '.join(sorted(targets))} "
                         f"| {', '.join(sorted(files))} |")
    else:
        lines.append("_No conflicts detected._")
    lines.append("")

    # 3. Broken refs
    broken: list = []
    if ontology_ids:
        watched_prefixes = {"CHEBI", "GO", "EC", "RO", "UBERON", "ENVO", "HP",
                            "MONDO", "PATO", "PR", "CL", "FOODON", "NCBITaxon", "OMP"}
        for fname, rows in canonical_rows_by_file.items():
            for r in rows:
                oid = (r.get("object_id") or "").strip()
                if not oid:
                    continue
                if get_prefix(oid) in watched_prefixes and oid not in ontology_ids:
                    broken.append((fname, r.get("subject_label", ""), oid))
    lines.append("### 3. Object IDs not resolvable in ontologies output")
    if broken:
        lines.append("| file | subject_label | object_id |")
        lines.append("|---|---|---|")
        for fname, label, oid in broken[:50]:
            lines.append(f"| {fname} | {label} | {oid} |")
        if len(broken) > 50:
            lines.append(f"_…and {len(broken) - 50} more._")
    else:
        lines.append("_All object IDs resolvable (or ontology output not loaded)._")
    lines.append("")

    # 4. Low-confidence
    low_conf: list = []
    for fname, rows in canonical_rows_by_file.items():
        for r in rows:
            conf = (r.get("confidence") or "").strip().lower()
            if conf and conf != "high":
                low_conf.append((fname, r.get("subject_label", ""),
                                 r.get("object_id", ""), conf))
    lines.append("### 4. Low-confidence canonical rows")
    if low_conf:
        lines.append("| file | subject_label | object_id | confidence |")
        lines.append("|---|---|---|---|")
        for fname, label, oid, conf in low_conf[:50]:
            lines.append(f"| {fname} | {label} | {oid} | {conf} |")
    else:
        lines.append("_All canonical rows are high-confidence._")
    lines.append("")

    # 5. Prefix normalization candidates
    aliases = {
        "PUBCHEM.COMPOUND": "pubchem.compound",
        "PubChem": "pubchem.compound",
        "CAS-RN": "cas",
        "Cas-rn": "cas",
    }
    prefix_hits: dict = defaultdict(int)
    for fname, rows in canonical_rows_by_file.items():
        for r in rows:
            oid = (r.get("object_id") or "").strip()
            p = get_prefix(oid)
            if p in aliases:
                prefix_hits[(fname, p, aliases[p])] += 1
    lines.append("### 5. Prefix normalization candidates")
    if prefix_hits:
        lines.append("| file | observed prefix | canonical prefix | rows |")
        lines.append("|---|---|---|---:|")
        for (fname, observed, canonical), n in sorted(prefix_hits.items()):
            lines.append(f"| {fname} | {observed} | {canonical} | {n} |")
    else:
        lines.append("_No prefix aliasing observed in canonical files._")
    lines.append("")

    # 6. CultureBotAI summary
    lines.append("### 6. CultureBotAI ingredient review queue")
    if cb_rows:
        statuses: dict = defaultdict(int)
        for r in cb_rows:
            statuses[(r.get("mapping_status") or "").strip() or "BLANK"] += 1
        lines.append("| status | count |")
        lines.append("|---|---:|")
        for status, n in sorted(statuses.items(), key=lambda x: -x[1]):
            lines.append(f"| {status} | {n} |")
    else:
        lines.append("_culturebotai_reviewed_ingredients.tsv not present._")
    lines.append("")

    return "\n".join(lines)


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
    parser.add_argument("--mappings", action="store_true",
                        help="Review curation TSVs under mappings/ and "
                             "kg_microbe/transform_utils/*/mappings/ in addition to the "
                             "transform/merged scope. Adds canonical schema + SSSOM checks "
                             "and a curation upgrade report.")
    parser.add_argument("--mappings-only", action="store_true",
                        help="Run ONLY the mappings review (skip transform/merged review).")
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
    mappings_result: dict = None

    if args.mappings_only:
        targets: list = []
    elif args.merged:
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

    if args.mappings or args.mappings_only:
        print(f"  Reviewing mapping files...", file=sys.stderr)
        mappings_result = review_mappings(args.verbose, registered_prefixes, metpo_curies)
        results.append(mappings_result)

    if args.format == "json":
        # Serialize findings
        output = []
        for r in results:
            entry = {
                "transform": r["name"],
                "errors": r["errors"],
                "warnings": r["warnings"],
                "nodes": [{"severity": f.severity, "check": f.check, "message": f.message}
                          for f in r["nodes"]],
                "edges": [{"severity": f.severity, "check": f.check, "message": f.message}
                          for f in r["edges"]],
            }
            if r.get("curation_report"):
                entry["curation_report"] = r["curation_report"]
            output.append(entry)
        rendered = json.dumps(output, indent=2)
        ext = "json"
    elif args.format == "md":
        rendered = format_text(results, format_md=True)
        ext = "md"
    else:
        rendered = format_text(results, format_md=False)
        ext = "txt"

    # Append the curation upgrade report (markdown) when mappings were reviewed.
    # In text mode the markdown body is appended verbatim with a separator
    # banner so the artifact is still useful to humans / upstream curators.
    if mappings_result and mappings_result.get("curation_report"):
        if args.format in ("md", "text"):
            rendered += "\n\n" + mappings_result["curation_report"]

    print(rendered)

    if not args.no_save:
        if args.mappings_only:
            scope = "mappings"
        elif args.mappings:
            scope = (
                f"{args.transform or ('merged' if args.merged else 'all-transforms')}"
                "+mappings"
            )
        elif args.merged:
            scope = "merged"
        elif args.transform:
            scope = args.transform
        else:
            scope = "all-transforms"
        saved = _save_review_artifact(rendered, scope, ext=ext)
        print(f"  Saved review to {saved}", file=sys.stderr)


if __name__ == "__main__":
    main()
