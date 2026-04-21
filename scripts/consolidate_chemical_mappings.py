#!/usr/bin/env python3
"""
Consolidate all chemical mapping files into a unified mapping resource.

Consolidates (in priority order — later-listed priority wins when sources
disagree about canonical_name/formula for the same entry):
1. mappings/chemical_mappings.tsv - KEGG/BacDive to ChEBI                   (priority=1)
2. data/raw/compound_mappings_strict.tsv - MediaDive ingredients            (priority=1)
3. data/raw/compound_mappings_strict_hydrate.tsv - Hydrated compounds       (priority=1)
4. kg_microbe/transform_utils/bacdive/metabolite_mapping.json               (priority=1)
5. kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv - ChEBI xrefs (priority=2)
6. kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv         (priority=5)
7. mappings/culturebotai_reviewed_ingredients.tsv - CultureBotAI reviewed    (priority=10)
8. mappings/ingredient_mappings.sssom.tsv - MediaIngredientMech SSSOM         (priority=11)
   Auto-synced from the MediaIngredientMech sibling repo
   (../MediaIngredientMech/mappings/ingredient_mappings.sssom.tsv) on every run
   via ``sync_mim_sssom``. The sibling repo is the source of truth; the
   vendored copy is refreshed in place whenever its content hash diverges.

The CultureBotAI and MediaIngredientMech reviewed mappings are
evidence-based and manually curated. MediaIngredientMech is the
authoritative canonical-naming source (priority=11): its subject_label
becomes the canonical_name shown in kg-microbe for symmetric matches
(``skos:exactMatch``, ``skos:closeMatch``). For asymmetric matches
(``skos:narrowMatch``, ``skos:broadMatch``) the MIM term is added only
as a synonym and the ontology's own label is kept canonical. The names
actually encountered in kg-microbe source data (BacDive, MediaDive,
KEGG, …) that map to the same CURIE are retained as synonyms, along
with CultureBotAI and MIM's own subject_label.

Name lookup respects priority: when two sources map the same ingredient
name to different CURIEs, priority decides the winner
(MediaIngredientMech 11 > CultureBotAI 10 > madin_etal 5 > chebi_xrefs 2 >
primary sources 1). Matches can be direct (CURIE xref) or via a synonym.
Synonyms and xrefs always accumulate (set union) regardless of priority.

The unified mapping keys on a generic CURIE (`id`) rather than just ChEBI.
Primary-id prefixes are ranked so that higher-ranked prefixes win when
multiple candidates exist for the same entity:

    CHEBI = FOODON = ENVO = UBERON   (ontology-scoped, tied top)
  > PubChem                          (structured public registry)
  > CAS-RN = mediadive.ingredient    (flat registry + minted fallback)
  > kgmicrobe.compound               (last-resort in-house mint)

See ``_PRIMARY_PREFIX_RANK`` and ``best_primary()``.

Output:
  mappings/unified_ingredient_mappings.sssom.tsv.gz
      The single unified mapping product, in SSSOM format (validated with
      the ``sssom`` package on write). Per-entity attributes that SSSOM
      cannot express natively — ``formula``, ``category`` (biolink class) —
      travel as SSSOM extension columns ``object_formula`` /
      ``object_category``, declared in the mapping-set header's
      ``extension_definitions``. Runtime transforms read this same file via
      ``kg_microbe.utils.chemical_mapping_utils``, which reconstructs the
      entity-centric view in memory by grouping rows on ``object_id``.
"""

import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

import pandas as pd

# Path (relative to kg-microbe repo root) where the sibling MediaIngredientMech
# checkout is expected to live. The MIM repo is the source of truth for the
# ingredient SSSOM mapping set and is synced into ``mappings/`` on every run.
_MIM_SIBLING_RELPATH = Path("..") / "MediaIngredientMech" / "mappings" / "ingredient_mappings.sssom.tsv"
_MIM_VENDORED_RELPATH = Path("mappings") / "ingredient_mappings.sssom.tsv"


def _read_sssom_records(filepath: Path) -> dict:
    """
    Read a unified SSSOM file (plain or gzipped) into per-entity records.

    Groups rows on ``object_id`` and reconstructs the entity-centric view
    that the TSV index used to hold: ``canonical_name``, ``formula``,
    ``category``, pipe-joinable ``synonyms`` / ``xrefs`` / ``sources``.

    Row classification (matches ``export_unified_sssom``):
      - subject starts with ``kgm.name:`` and ``comment == "canonical_name"``
        → entity's canonical name (from ``subject_label``).
      - subject starts with ``kgm.name:`` and ``comment == "synonym"``
        → synonym (added to the entity's synonym set).
      - subject is any other CURIE → xref (added to the entity's xref set);
        unless subject == object (attribute_carrier row, skipped as a no-op
        equivalence, formula/category still picked up from its columns).

    Extension columns ``object_formula`` / ``object_category`` ride on every
    row — the first non-empty value wins per ``object_id``.

    Returns: ``{curie: {"canonical_name": str, "formula": str, "category": str,
    "synonyms": set, "xrefs": set, "sources": set}}``.
    """
    import csv
    import gzip as _gzip

    open_fn = (
        (lambda p: _gzip.open(p, "rt", encoding="utf-8", newline=""))
        if str(filepath).endswith(".gz")
        else (lambda p: open(p, "r", encoding="utf-8", newline=""))
    )

    records: dict = {}

    with open_fn(filepath) as fh:
        # Skip comment/metadata lines (start with '#'); the header is the
        # first non-comment line.
        reader_iter = (line for line in fh if not line.startswith("#"))
        reader = csv.DictReader(reader_iter, delimiter="\t")
        for row in reader:
            obj = (row.get("object_id") or "").strip()
            if not obj:
                continue

            rec = records.get(obj)
            if rec is None:
                rec = {
                    "canonical_name": "",
                    "formula": "",
                    "category": "",
                    "synonyms": set(),
                    "xrefs": set(),
                    "sources": set(),
                }
                records[obj] = rec

            # First non-empty extension attributes win per object.
            if not rec["formula"]:
                form = (row.get("object_formula") or "").strip()
                if form:
                    rec["formula"] = form
            if not rec["category"]:
                cat = (row.get("object_category") or "").strip()
                if cat:
                    rec["category"] = cat

            # Accumulate source labels from every row.
            src = (row.get("source") or "").strip()
            if src:
                for part in src.split("|"):
                    p = part.strip()
                    if p:
                        rec["sources"].add(p)

            subj = (row.get("subject_id") or "").strip()
            comment = (row.get("comment") or "").strip()
            subj_label = (row.get("subject_label") or "").strip()
            obj_label = (row.get("object_label") or "").strip()

            if not rec["canonical_name"] and obj_label:
                rec["canonical_name"] = obj_label

            if subj.startswith("kgm.name:"):
                # Either canonical_name or synonym row; canonical is already
                # captured via object_label above. Synonyms are captured from
                # subject_label here.
                if comment == "synonym" and subj_label:
                    rec["synonyms"].add(subj_label)
                # canonical_name rows: subject_label matches canonical; no-op.
            elif subj and subj != obj:
                rec["xrefs"].add(subj)
            # subj == obj is the attribute_carrier case — no xref/synonym.

    return records


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 of a file (streaming; safe for large files)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_mim_sssom(base_dir: Path) -> Path:
    """
    Sync the vendored MIM SSSOM mapping from the sibling repo if present.

    The MediaIngredientMech repo is the authoritative source of truth for
    ingredient → ontology SSSOM mappings and is updated regularly. When
    checked out as a sibling of kg-microbe, this function refreshes the
    vendored copy at ``mappings/ingredient_mappings.sssom.tsv`` so the
    consolidator always ingests the latest curations.

    Behaviour:
      - sibling present, content differs → overwrite vendored (sibling wins)
      - sibling present, content matches → no copy, just confirm up-to-date
      - sibling absent, vendored present → warn and continue with vendored
      - neither present → raise FileNotFoundError

    Returns the path to use (always the vendored path, which is authoritative
    once synced).
    """
    vendored = (base_dir / _MIM_VENDORED_RELPATH).resolve()
    sibling = (base_dir / _MIM_SIBLING_RELPATH).resolve()

    if sibling.exists():
        if not vendored.exists():
            print(f"Syncing MIM SSSOM (vendored copy missing): {sibling} → {vendored}")
            shutil.copy2(sibling, vendored)
        elif _file_sha256(sibling) != _file_sha256(vendored):
            print(f"Syncing MIM SSSOM from source of truth: {sibling} → {vendored}")
            shutil.copy2(sibling, vendored)
        else:
            print(f"MIM SSSOM up-to-date with sibling repo ({sibling})")
        return vendored

    if vendored.exists():
        print(
            f"Warning: MediaIngredientMech sibling repo not found at {sibling};\n"
            f"  using vendored copy {vendored} (may be stale — "
            "clone/pull MediaIngredientMech as a sibling of kg-microbe and re-run)"
        )
        return vendored

    raise FileNotFoundError(
        "MIM SSSOM mapping not found. Expected either:\n"
        f"  sibling repo: {sibling}\n"
        f"  vendored copy: {vendored}\n"
        "Clone MediaIngredientMech (https://github.com/KG-Hub/MediaIngredientMech) "
        "as a sibling of kg-microbe, or restore the vendored copy."
    )


def normalize_name(name: str) -> str:
    """Normalize chemical name for comparison."""
    if pd.isna(name) or not name:
        return ""
    # Convert to lowercase, remove extra spaces, punctuation
    normalized = str(name).lower().strip()
    normalized = re.sub(r"[^\w\s-]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def extract_chebi_id(value: str) -> str:
    """Extract ChEBI ID from various formats."""
    if pd.isna(value) or not value:
        return ""
    value = str(value)
    if value.startswith("CHEBI:"):
        return value
    if value.startswith("chebi:"):
        return "CHEBI:" + value[6:]
    # Try to extract number
    match = re.search(r"(\d+)", value)
    if match:
        return f"CHEBI:{match.group(1)}"
    return ""


# Category lookup by CURIE prefix. The unified mapping stores the biolink
# category as a data column so downstream transforms do not need hardcoded
# prefix-to-category routing.
_CATEGORY_BY_PREFIX: Dict[str, str] = {
    "CHEBI": "biolink:ChemicalSubstance",
    "FOODON": "biolink:Food",
    "UBERON": "biolink:AnatomicalEntity",
    "ENVO": "biolink:EnvironmentalFeature",
    "NCIT": "biolink:ChemicalSubstance",
    "PO": "biolink:AnatomicalEntity",
    # PubChem CID — used as primary when no ontology (CHEBI/FOODON/UBERON/ENVO)
    # match exists for an ingredient. Ranks above CAS-RN / mediadive.ingredient.
    "pubchem.compound": "biolink:ChemicalEntity",
    # CAS registry number — flat registry code, used as primary only when no
    # higher-ranked prefix resolves (tied with mediadive.ingredient).
    "cas": "biolink:ChemicalEntity",
    # MediaDive-minted fallback id for unresolved ingredients. Emitted directly
    # by the mediadive transform; accepted here so the unified file can carry
    # curated names/synonyms for these ingredients when no ontology mapping
    # exists yet (tied with CAS-RN).
    "mediadive.ingredient": "biolink:ChemicalEntity",
    # KG-Microbe native prefix for chemicals with no public ontology ID
    # (antibiotics / secondary metabolites minted from metatraits). Last-resort
    # mint — ranks below every other accepted prefix.
    "kgmicrobe.compound": "biolink:ChemicalEntity",
}

# CURIE prefixes this consolidator accepts as a primary `id`. Other prefixes
# are treated as xrefs (see loaders).
_ACCEPTED_PREFIXES = tuple(f"{p}:" for p in _CATEGORY_BY_PREFIX.keys())

# Prefix preference for the primary `id` column. Higher rank wins when
# multiple candidate CURIEs exist for the same entity. Ordering per
# KG-Microbe convention:
#     CHEBI = FOODON = ENVO = UBERON   (ontology-scoped, top tier)
#   > PubChem                          (structured public registry)
#   > CAS-RN = mediadive.ingredient    (flat registry + minted fallback)
#   > kgmicrobe.compound               (last-resort in-house mint)
# Equal-rank entries are only realistic for the tied-ontology tier (scopes
# are disjoint so collisions rarely materialise) and the CAS/mediadive tier.
_PRIMARY_PREFIX_RANK: Dict[str, int] = {
    "CHEBI": 100,
    "FOODON": 100,
    "UBERON": 100,
    "ENVO": 100,
    "NCIT": 100,
    "PO": 100,
    "pubchem.compound": 80,
    "cas": 60,
    "mediadive.ingredient": 60,
    "kgmicrobe.compound": 40,
}

# Prefixes routed to the unified *chemical* file. Covers chemicals proper
# (CHEBI, PubChem, CAS, kgmicrobe.compound, NCIT) *and* ontologies used for
# media ingredients (FOODON foods, UBERON anatomical ingredients like "beef
# heart" or "sheep blood", ENVO media components like "seawater"), plus the
# mediadive-minted fallback (mediadive.ingredient). Anything not listed here
# goes to the unified *other* file — reserved for future non-ingredient
# mappings (e.g. PO plant structures not used as media).
_CHEMICAL_PREFIXES = {
    "CHEBI",
    "kgmicrobe.compound",
    "NCIT",
    "FOODON",
    "UBERON",
    "ENVO",
    "pubchem.compound",
    "cas",
    "mediadive.ingredient",
}


def category_for(curie: str) -> str:
    """Return biolink category for a CURIE based on its prefix, or '' if unknown."""
    if not curie or ":" not in curie:
        return ""
    prefix = curie.split(":", 1)[0]
    return _CATEGORY_BY_PREFIX.get(prefix, "")


def is_accepted_primary(curie: str) -> bool:
    """Return True if the CURIE is a supported primary key for the unified file."""
    return bool(curie) and curie.startswith(_ACCEPTED_PREFIXES)


def prefix_rank(curie: str) -> int:
    """Return the primary-prefix rank of a CURIE (higher = preferred)."""
    if not curie or ":" not in curie:
        return 0
    return _PRIMARY_PREFIX_RANK.get(curie.split(":", 1)[0], 0)


def best_primary(candidates) -> str:
    """
    Return the highest-ranked accepted primary CURIE from candidates, or ''.

    Candidates may be any iterable of CURIE strings; non-accepted prefixes and
    empty strings are discarded before ranking. Within a tied rank, the first
    candidate in iteration order wins — callers that care about a deterministic
    tiebreak should pass candidates in their preferred order.
    """
    best = ""
    best_rank = -1
    for c in candidates:
        c = (c or "").strip()
        if not is_accepted_primary(c):
            continue
        r = prefix_rank(c)
        if r > best_rank:
            best = c
            best_rank = r
    return best


def is_chemical_curie(curie: str) -> bool:
    """Return True if the CURIE's prefix belongs in the unified chemical file."""
    if not curie or ":" not in curie:
        return False
    return curie.split(":", 1)[0] in _CHEMICAL_PREFIXES


class ChemicalMappingConsolidator:

    """Consolidate chemical mappings from multiple sources."""

    def __init__(self):
        """Initialize consolidator."""
        self.chemicals: Dict[str, Dict] = {}  # id -> chemical data
        self.name_index: Dict[str, str] = {}  # normalized_name -> id
        self.formula_index: Dict[str, Set[str]] = defaultdict(set)  # formula -> set of ids
        self.chebi_adapter = None  # Will be initialized when needed

    def add_chemical(
        self,
        id: str,
        canonical_name: str = "",
        formula: str = "",
        synonyms: List[str] = None,
        xrefs: List[str] = None,
        source: str = "",
        priority: int = 1,
    ):
        """
        Add or update an entry keyed by CURIE.

        Accepts any CURIE whose prefix is in ``_CATEGORY_BY_PREFIX`` (CHEBI
        for chemicals, FOODON/UBERON/ENVO/… for non-chemical ingredients).
        The biolink category is derived from the prefix at insert time.

        ``priority`` governs conflict resolution. A higher-priority source
        overrides the canonical_name and formula of any lower-priority source
        for the same id. Synonyms, xrefs, and sources always accumulate
        regardless of priority (union semantics).
        """
        if not is_accepted_primary(id):
            return

        if id not in self.chemicals:
            self.chemicals[id] = {
                "id": id,
                "category": category_for(id),
                "canonical_name": "",
                "formula": "",
                "synonyms": set(),
                "xrefs": set(),
                "sources": set(),
                "priority": 0,
            }

        chem = self.chemicals[id]

        # Canonical name: higher-priority source wins outright; within the
        # same priority band, prefer the first non-empty value (stable).
        if canonical_name and not pd.isna(canonical_name):
            canonical_name = str(canonical_name)
            if priority > chem["priority"]:
                chem["canonical_name"] = canonical_name
            elif priority == chem["priority"] and not chem["canonical_name"]:
                chem["canonical_name"] = canonical_name

        # Formula: higher-priority wins outright; empty formula is also
        # fillable from any priority (missing-data fill, not a conflict).
        # Unlike canonical_name we do not require same-or-higher priority for
        # empty-fill because formulas are objective chemistry — if one source
        # has a formula and higher-priority sources simply omit the field,
        # keeping the formula available is strictly better than dropping it.
        if formula and not pd.isna(formula):
            formula = str(formula)
            if priority > chem["priority"] or not chem["formula"]:
                chem["formula"] = formula

        # Track the highest priority that has contributed to this record.
        if priority > chem["priority"]:
            chem["priority"] = priority

        # Add synonyms
        if synonyms:
            chem["synonyms"].update([s for s in synonyms if s])

        # Add xrefs
        if xrefs:
            chem["xrefs"].update([x for x in xrefs if x])

        # Track source
        if source:
            chem["sources"].add(source)

        # Update indices. Both canonical_name and any provided synonyms
        # feed the name lookup index so downstream lookups by ingredient
        # name can resolve through either. Tiebreak order when the same
        # name would map to different CURIEs:
        #   1. higher *source* priority wins (MIM 11 > CultureBotAI 10 >
        #      manual 5 > chebi_xrefs 2 > primary 1)
        #   2. at equal source priority, higher *prefix* rank wins
        #      (CHEBI/FOODON/UBERON/ENVO > PubChem > CAS/mediadive >
        #      kgmicrobe.compound) — prevents a cas:* or mediadive.ingredient
        #      synonym added at priority=1 from clobbering an already-indexed
        #      CHEBI entry at priority=1.
        def _set_name_index(name: str) -> None:
            norm_name = normalize_name(name)
            if not norm_name:
                return
            existing_id = self.name_index.get(norm_name)
            if existing_id is None:
                self.name_index[norm_name] = id
                return
            if existing_id == id:
                return
            existing_priority = self.chemicals[existing_id]["priority"]
            if priority > existing_priority:
                self.name_index[norm_name] = id
            elif priority == existing_priority and prefix_rank(id) > prefix_rank(existing_id):
                self.name_index[norm_name] = id

        if canonical_name:
            _set_name_index(canonical_name)
        if synonyms:
            for syn in synonyms:
                if syn:
                    _set_name_index(syn)

        if formula:
            self.formula_index[formula].add(id)

    def load_primary_mappings(self, filepath: Path):
        """Load mappings/chemical_mappings.tsv."""
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t")

        for _, row in df.iterrows():
            chebi_id = extract_chebi_id(row.get("chebi_id", ""))
            if not chebi_id:
                continue

            canonical_name = row.get("chebi_label", "")
            formula = row.get("chebi_formula", "")
            original_term = row.get("original_term", "")
            term_source = row.get("term_source", "")

            # Collect synonyms and xrefs
            synonyms = []
            xrefs = []

            if original_term and not pd.isna(original_term):
                original_term = str(original_term)
                # Check if it's an external reference
                if original_term.startswith("cpd:"):
                    xrefs.append(f"kegg.compound:{original_term[4:]}")
                else:
                    synonyms.append(original_term)

            self.add_chemical(
                id=chebi_id,
                canonical_name=canonical_name,
                formula=formula,
                synonyms=synonyms,
                xrefs=xrefs,
                source=f"primary_mappings[{term_source}]",
                priority=1,
            )

        print(f"  Loaded {len(df)} entries")

    def load_compound_mappings(self, filepath: Path):
        """Load data/raw/compound_mappings_strict*.tsv."""
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t")

        for _, row in df.iterrows():
            # Try multiple ChEBI ID columns
            chebi_id = extract_chebi_id(row.get("chebi_id", "")) or extract_chebi_id(
                row.get("mapped", "")
            )
            if not chebi_id:
                # Try base_chebi_id
                chebi_id = extract_chebi_id(row.get("base_chebi_id", ""))
            if not chebi_id:
                continue

            canonical_name = row.get("chebi_label", "")
            formula = row.get("chebi_formula", "")
            original = row.get("original", "")
            base_compound = row.get("base_compound", "")

            synonyms = []
            if original:
                synonyms.append(original)
            if base_compound and base_compound != original:
                synonyms.append(base_compound)

            # Hydrate-specific data
            xrefs = []
            if "hydrate" in str(filepath):
                hydrated_chebi = extract_chebi_id(row.get("hydrated_chebi_id", ""))
                if hydrated_chebi and hydrated_chebi != chebi_id:
                    xrefs.append(hydrated_chebi)

            self.add_chemical(
                id=chebi_id,
                canonical_name=canonical_name,
                formula=formula,
                synonyms=synonyms,
                xrefs=xrefs,
                source="mediadive_compounds",
                priority=1,
            )

        print(f"  Loaded {len(df)} entries")

    def load_metabolite_json(self, filepath: Path):
        """Load kg_microbe/transform_utils/bacdive/metabolite_mapping.json."""
        print(f"Loading {filepath}...")
        with open(filepath) as f:
            data = json.load(f)

        for chebi_id, name in data.items():
            chebi_id = extract_chebi_id(chebi_id)
            if not chebi_id:
                continue

            self.add_chemical(
                id=chebi_id,
                canonical_name=name,
                synonyms=[name],
                source="bacdive_metabolites",
                priority=1,
            )

        print(f"  Loaded {len(data)} entries")

    def load_chebi_xrefs(self, filepath: Path):
        """Load kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv."""
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t")

        # Group by ChEBI ID
        grouped = df.groupby("id")["xref"].apply(list).to_dict()

        for chebi_id, xref_list in grouped.items():
            chebi_id = extract_chebi_id(chebi_id)
            if not chebi_id:
                continue

            self.add_chemical(
                id=chebi_id, xrefs=xref_list, source="chebi_xrefs", priority=2
            )

        print(f"  Loaded {len(grouped)} ChEBI IDs with xrefs")

    def load_manual_annotations(self, filepath: Path):
        """Load kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv."""
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t")

        for _, row in df.iterrows():
            chebi_id = extract_chebi_id(row.get("object_id", ""))
            if not chebi_id:
                continue

            canonical_name = row.get("object_label", "")
            traits_term = row.get("traits_dataset_term", "")
            action = row.get("action", "")

            synonyms = []
            if traits_term:
                synonyms.append(traits_term)

            self.add_chemical(
                id=chebi_id,
                canonical_name=canonical_name,
                synonyms=synonyms,
                source=f"manual_annotation[{action}]",
                priority=5,
            )

        print(f"  Loaded {len(df)} entries")

    def load_metatraits_chemical_mappings(self, filepath: Path):
        """
        Load kg_microbe/transform_utils/metatraits/mappings/chemical_mappings.tsv.

        SSSOM-style table mapping metatraits trait phrases (subject_label,
        e.g. "produces: ethanol") to ontology IDs. The subject_label is added
        as a synonym so `find_chebi_by_name` resolves the full trait phrase to
        the underlying chemical entity.
        """
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t", dtype=str).fillna("")

        loaded = 0
        for _, row in df.iterrows():
            curie = (row.get("object_id", "") or "").strip()
            if not is_accepted_primary(curie):
                continue

            canonical_name = (row.get("object_label", "") or "").strip()
            subject_label = (row.get("subject_label", "") or "").strip()
            normalized = (row.get("subject_label_normalized", "") or "").strip()

            synonyms = [s for s in (subject_label, normalized) if s]

            self.add_chemical(
                id=curie,
                canonical_name=canonical_name,
                synonyms=synonyms,
                source="metatraits_chemical_mappings",
                priority=5,
            )
            loaded += 1

        print(f"  Loaded {loaded} entries")

    def load_metatraits_special_chemicals(self, filepath: Path):
        """
        Load kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv.

        Manually corrected trait-pattern → ontology-ID overrides for high-frequency
        phrasings the NLP/synonym pipeline gets wrong (e.g. "electron acceptor:
        sulfur compounds" → CHEBI:26835). Both `trait_pattern` and `chemical_name`
        are loaded as synonyms so downstream lookups resolve either form.
        """
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t", dtype=str).fillna("")

        loaded = 0
        for _, row in df.iterrows():
            curie = (row.get("ontology_id", "") or "").strip()
            if not is_accepted_primary(curie):
                continue

            canonical_name = (row.get("ontology_name", "") or "").strip()
            trait_pattern = (row.get("trait_pattern", "") or "").strip()
            chemical_name = (row.get("chemical_name", "") or "").strip()

            synonyms = [s for s in (trait_pattern, chemical_name) if s]

            self.add_chemical(
                id=curie,
                canonical_name=canonical_name,
                synonyms=synonyms,
                source="metatraits_special_chemicals",
                priority=5,
            )
            loaded += 1

        print(f"  Loaded {loaded} entries")

    def load_existing_unified_tsv(self, filepath: Path):
        """
        Load a legacy unified TSV.GZ baseline (migration fallback only).

        The TSV outputs have been retired in favour of SSSOM-with-extension-
        columns; this method exists only so the first consolidator run after
        the switch can pick up ``formula`` and ``category`` values from the
        old file before it is deleted. Delete this method and the matching
        main() call once the SSSOM baseline reliably carries the extension
        columns.
        """
        import gzip as _gzip

        print(f"Loading legacy TSV baseline from {filepath}...")
        with _gzip.open(filepath, "rt") as f:
            df = pd.read_csv(f, sep="\t", dtype=str).fillna("")

        priority_for = {
            "mediaingredientmech_reviewed": 11,
            "culturebotai_reviewed": 10,
            "manual_annotation": 5,
            "manual_corrections": 5,
            "metatraits_manual": 5,
            "metatraits_chemical_synonyms": 5,
            "metatraits_special_chemicals": 5,
            "metatraits_chemical_mappings": 5,
            "chebi_xrefs": 2,
        }

        def infer_priority(sources_str: str) -> int:
            parts = [p.strip() for p in sources_str.split("|") if p.strip()]
            best = 1
            for src in parts:
                for prefix, pri in priority_for.items():
                    if src.startswith(prefix):
                        best = max(best, pri)
            return best

        id_column = "id" if "id" in df.columns else "chebi_id"
        for _, row in df.iterrows():
            curie = row.get(id_column, "")
            if not is_accepted_primary(curie):
                continue
            synonyms = [s for s in row.get("synonyms", "").split("|") if s]
            xrefs = [x for x in row.get("xrefs", "").split("|") if x]
            sources = [s for s in row.get("sources", "").split("|") if s]
            priority = infer_priority(row.get("sources", ""))

            self.add_chemical(
                id=curie,
                canonical_name=row.get("canonical_name", ""),
                formula=row.get("formula", ""),
                synonyms=synonyms,
                xrefs=xrefs,
                source="",
                priority=priority,
            )
            self.chemicals[curie]["sources"].update(sources)

        print(f"  Loaded {len(df)} legacy baseline entries")

    def load_existing_unified(self, filepath: Path):
        """
        Load an existing unified SSSOM file as a baseline.

        Reads ``unified_ingredient_mappings.sssom.tsv.gz`` (the primary and
        only unified output) and reconstructs per-entity records by grouping
        rows on ``object_id``.

        The unified SSSOM is the source of truth once legacy per-source
        inputs have been archived. This loader re-ingests every row so that
        the consolidator can layer additional sources on top (via priority)
        without losing prior content.

        Priority is inferred per row from the ``source`` column:
          - mediaingredientmech_reviewed → 11
          - culturebotai_reviewed        → 10
          - manual_annotation*           → 5
          - chebi_xrefs                  → 2
          - everything else              → 1

        Row-shape semantics (produced by ``export_unified_sssom``):
          - xref rows: subject is a plain CURIE (not ``kgm.name:``), carries
            an equivalent identifier for the object.
          - canonical_name rows: subject is ``kgm.name:<slug>`` with
            ``comment == "canonical_name"``; the ``subject_label`` and
            ``object_label`` both hold the entity's canonical name.
          - synonym rows: subject is ``kgm.name:<slug>`` with
            ``comment == "synonym"``; ``subject_label`` is the synonym text.
          - attribute_carrier rows: subject equals object; emitted only when
            an entity has extension attributes but no other mapping rows.

        Extension columns ``object_formula`` and ``object_category`` ride on
        every row as per-entity attributes; the loader takes the first
        non-empty value per ``object_id``.
        """
        print(f"Loading existing unified SSSOM from {filepath}...")
        records = _read_sssom_records(filepath)

        priority_for = {
            "mediaingredientmech_reviewed": 11,
            "culturebotai_reviewed": 10,
            "manual_annotation": 5,
            "manual_corrections": 5,
            "metatraits_manual": 5,
            "metatraits_chemical_synonyms": 5,
            "metatraits_special_chemicals": 5,
            "metatraits_chemical_mappings": 5,
            "chebi_xrefs": 2,
        }

        def infer_priority(sources_str: str) -> int:
            parts = [p.strip() for p in sources_str.split("|") if p.strip()]
            best = 1
            for src in parts:
                for prefix, pri in priority_for.items():
                    if src.startswith(prefix):
                        best = max(best, pri)
            return best

        # Guard against previously-polluted baselines.
        POLLUTION_CAP = 500
        pollution_skipped = 0

        for curie, rec in records.items():
            if not is_accepted_primary(curie):
                continue
            synonyms = list(rec["synonyms"])
            xrefs = list(rec["xrefs"])
            sources = list(rec["sources"])
            if len(synonyms) > POLLUTION_CAP or len(xrefs) > POLLUTION_CAP:
                print(
                    f"  WARN: {curie} has {len(synonyms)} synonyms / "
                    f"{len(xrefs)} xrefs — dropping as polluted baseline"
                )
                synonyms = []
                xrefs = []
                pollution_skipped += 1
            priority = infer_priority("|".join(sources))

            self.add_chemical(
                id=curie,
                canonical_name=rec["canonical_name"],
                formula=rec["formula"],
                synonyms=synonyms,
                xrefs=xrefs,
                source="",  # use explicit add below to preserve all source labels
                priority=priority,
            )
            # Preserve every historical source label rather than collapsing them
            self.chemicals[curie]["sources"].update(sources)

        if pollution_skipped:
            print(
                f"  Dropped polluted synonyms/xrefs from "
                f"{pollution_skipped} baseline row(s)"
            )
        print(f"  Loaded {len(records)} baseline entries")

    def load_culturebotai_reviewed(self, filepath: Path):
        """
        Load mappings/culturebotai_reviewed_ingredients.tsv.

        Authoritative: evidence-based and manually reviewed media-ingredient
        mappings from the CultureBotAI project. When this file asserts a
        canonical_name, CAS RN, CHEBI, or non-CHEBI ontology ID for an
        ingredient, the assertion overrides lower-priority sources.

        Columns consumed:
          - ingredient_name     → canonical_name (and added as synonym)
          - chebi_id            → primary key candidate (top-ranked prefix)
          - culturemech_term_id → primary key candidate for FOODON/UBERON/ENVO
                                  ingredients (meat extract, beef heart,
                                  defibrinated sheep blood, seawater, …)
          - mim_id              → primary key candidate — MediaIngredientMech's
                                  preferred CURIE, typically FOODON/UBERON/ENVO
                                  for non-chemical ingredients
          - kg_microbe_node_id  → primary key candidate — curator's intended
                                  final primary; usually CHEBI
          - cas_rn              → primary key candidate (last-resort via
                                  ``cas:<number>``) when no ontology id
                                  resolves; also always added as xref

        Primary selection follows the unified prefix ranking
        (``best_primary``): ontology CURIEs win over PubChem/CAS/mediadive
        over kgmicrobe.compound. ``cas_rn`` is always recorded as an xref
        even when a higher-ranked primary is chosen.
        """
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t", dtype=str).fillna("")

        added = 0
        skipped = 0
        for _, row in df.iterrows():
            ingredient_name = row.get("ingredient_name", "").strip()
            cas_rn = row.get("cas_rn", "").strip()
            culturemech_term = row.get("culturemech_term_id", "").strip()
            mim_id = row.get("mim_id", "").strip()
            kg_node_id = row.get("kg_microbe_node_id", "").strip()
            chebi_id = extract_chebi_id(row.get("chebi_id", ""))
            cas_curie = f"cas:{cas_rn}" if cas_rn else ""

            # Pick the best available primary using the unified prefix rank:
            # CHEBI/FOODON/UBERON/ENVO/NCIT > PubChem > CAS > mediadive.ingredient
            # > kgmicrobe.compound. mim_id and kg_microbe_node_id are included
            # because they routinely carry FOODON/UBERON/ENVO when chebi_id and
            # culturemech_term_id are empty (e.g. "Yeast extract (BD-Difco)"
            # has mim_id=FOODON:03315426 but chebi_id/culturemech_term_id blank).
            # ``cas_curie`` is a last-resort candidate so cas-only rows get a
            # primary id instead of being dropped.
            primary_id = best_primary(
                [chebi_id, culturemech_term, mim_id, kg_node_id, cas_curie]
            )
            if not primary_id:
                skipped += 1
                continue

            synonyms = [ingredient_name] if ingredient_name else []
            xrefs = []
            for candidate in (cas_curie, culturemech_term, mim_id, kg_node_id, chebi_id):
                if candidate and candidate != primary_id and is_accepted_primary(candidate):
                    xrefs.append(candidate)
            # cas_curie may not be an accepted primary on older configs, but we
            # always want it as an xref when present (independent of primary).
            if cas_curie and cas_curie != primary_id and cas_curie not in xrefs:
                xrefs.append(cas_curie)

            self.add_chemical(
                id=primary_id,
                canonical_name=ingredient_name,
                synonyms=synonyms,
                xrefs=xrefs,
                source="culturebotai_reviewed",
                priority=10,
            )
            added += 1

        print(f"  Loaded {added} reviewed entries (skipped {skipped} with no supported CURIE)")

    @staticmethod
    def _validate_sssom_file(filepath: Path) -> None:
        """
        Validate an SSSOM mapping set with the ``sssom`` package.

        Runs two checks:
          1. LinkML JSON-Schema validation against ``sssom-schema`` via
             ``sssom.validators.validate`` (with ``fail_on_error=True`` so
             any schema violation raises).
          2. ``check_all_prefixes_in_curie_map`` — every CURIE prefix used
             in the data rows must be declared in the file's ``curie_map``
             header.

        Raises the underlying exception from ``sssom`` on any failure;
        the consolidator should abort rather than ingest an invalid set.
        """
        from sssom.parsers import parse_sssom_table
        from sssom.validators import (
            SchemaValidationType,
            check_all_prefixes_in_curie_map,
            validate,
        )

        print(f"Validating SSSOM file {filepath}...")
        msdf = parse_sssom_table(str(filepath))
        validate(msdf, [SchemaValidationType.JsonSchema], fail_on_error=True)
        check_all_prefixes_in_curie_map(msdf)
        print(f"  ✓ SSSOM validation passed ({len(msdf.df)} rows, "
              f"{len(msdf.prefix_map)} prefixes)")

    def load_mediaingredientmech_sssom(self, filepath: Path):
        """
        Load mappings/ingredient_mappings.sssom.tsv.

        Authoritative: expert-curated media-ingredient → ontology mappings
        from the MediaIngredientMech project (sibling repo of kg-microbe),
        delivered as a standard SSSOM mapping set.

        The file is parsed and validated by the ``sssom`` package against
        the published ``sssom-schema`` (LinkML JSON Schema) and its curie
        map is cross-checked before any row is consumed. Validation errors
        abort the consolidator rather than silently contaminating the
        unified mapping.

        Columns consumed:
          - subject_id        → MIM CURIE; emitted as xref
          - subject_label     → MIM's curated preferred term for the ingredient.
                                For symmetric matches (exactMatch, closeMatch)
                                this becomes the canonical_name. For asymmetric
                                matches it is added as a synonym only.
          - predicate_id      → skos predicate; decides symmetric vs asymmetric
          - object_id         → primary key (CHEBI/FOODON/UBERON/ENVO/…)
          - object_label      → ontology's canonical name; becomes canonical
                                for asymmetric matches, added as a synonym in
                                all cases.
          - other             → pipe-delimited list of additional MIM-curated
                                synonyms harvested from the ingredient evidence
          - confidence        → informational only (all rows kept)

        Rows whose ``object_id`` prefix is not in the consolidator's accepted
        set are skipped.
        """
        self._validate_sssom_file(filepath)
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t", dtype=str, comment="#").fillna("")

        symmetric = {"skos:exactMatch", "skos:closeMatch"}

        added = 0
        skipped_unsupported = 0
        for _, row in df.iterrows():
            object_id = row.get("object_id", "").strip()
            if not is_accepted_primary(object_id):
                recovered = extract_chebi_id(object_id)
                if not recovered:
                    skipped_unsupported += 1
                    continue
                object_id = recovered

            predicate = row.get("predicate_id", "").strip()
            subject_id = row.get("subject_id", "").strip()
            subject_label = row.get("subject_label", "").strip()
            object_label = row.get("object_label", "").strip()
            other = row.get("other", "").strip()

            # Symmetric matches: MIM's curated term wins canonical naming.
            # Asymmetric (narrow/broad): ontology label stays canonical; MIM
            # term is still captured as a synonym.
            if predicate in symmetric:
                canonical = subject_label
            else:
                canonical = object_label

            synonyms = [s for s in (subject_label, object_label) if s]
            if other:
                synonyms.extend(s.strip() for s in other.split("|") if s.strip())

            xrefs = [subject_id] if subject_id.startswith("MIM:") else []

            self.add_chemical(
                id=object_id,
                canonical_name=canonical,
                synonyms=synonyms,
                xrefs=xrefs,
                source="mediaingredientmech_reviewed",
                priority=11,
            )
            added += 1

        print(
            f"  Loaded {added} MIM SSSOM entries "
            f"(skipped {skipped_unsupported} unsupported object_id prefix)"
        )

    def _get_chebi_adapter(self):
        """Get or create ChEBI adapter."""
        if self.chebi_adapter is None:
            try:
                from oaklib import get_adapter

                from kg_microbe.transform_utils.constants import CHEBI_SOURCE

                self.chebi_adapter = get_adapter(f"sqlite:{CHEBI_SOURCE}")
                print("  Initialized ChEBI adapter")
            except Exception as e:
                print(f"  Warning: Could not initialize ChEBI adapter: {e}")
                print("  ChEBI synonyms will not be added")
        return self.chebi_adapter

    def enrich_with_chebi_synonyms(self):
        """Add ChEBI ontology synonyms to each chemical."""
        print("\nEnriching with ChEBI synonyms...")
        adapter = self._get_chebi_adapter()

        if not adapter:
            print("  Skipped - ChEBI adapter not available")
            return

        enriched_count = 0
        synonym_count = 0

        chebi_source_priority = 2  # matches load_chebi_xrefs
        for curie, chem in self.chemicals.items():
            if not curie.startswith("CHEBI:"):
                continue
            try:
                # ChEBI label: only fill in when the existing canonical is empty,
                # and never overwrite names asserted by higher-priority sources.
                label = adapter.label(curie)
                if label and not chem["canonical_name"] and chem["priority"] <= chebi_source_priority:
                    chem["canonical_name"] = label

                # Get synonyms from ChEBI (always accumulate — synonyms are additive)
                synonyms = list(adapter.entity_aliases(curie))
                if synonyms:
                    # Filter out None values
                    valid_synonyms = [s for s in synonyms if s is not None]
                    chem["synonyms"].update(valid_synonyms)
                    synonym_count += len(valid_synonyms)
                    enriched_count += 1

            except Exception:
                # Skip entries that don't exist in ChEBI
                pass

        print(f"  Enriched {enriched_count} chemicals with {synonym_count} ChEBI synonyms")

    def enrich_with_chebi_xref_labels(self):
        """
        Harvest labels/aliases for CHEBI xrefs that don't have their own record.

        Covers the case where a primary record (e.g. a non-CHEBI ingredient,
        or another CHEBI entry) carries a CHEBI xref that no loader ever
        promoted to its own row — so the cross-record propagation pass has
        nothing to pull from. For each such xref we look up its label and
        aliases via the ChEBI OAK adapter and merge them into the owning
        record's synonyms.
        """
        print("\nEnriching CHEBI xref labels via OAK...")
        adapter = self._get_chebi_adapter()
        if not adapter:
            print("  Skipped - ChEBI adapter not available")
            return

        primaries = set(self.chemicals.keys())
        records_augmented = 0
        synonyms_added = 0
        for chem in self.chemicals.values():
            chebi_xrefs = [
                x for x in chem["xrefs"]
                if x.startswith("CHEBI:") and x not in primaries
            ]
            if not chebi_xrefs:
                continue
            added_here: Set[str] = set()
            for xref in chebi_xrefs:
                try:
                    label = adapter.label(xref)
                    if label:
                        added_here.add(label)
                    aliases = adapter.entity_aliases(xref)
                    added_here.update(a for a in aliases if a)
                except Exception:  # noqa: S110 - obsolete CHEBI ids are expected to miss
                    pass
            # Do not pollute synonyms with this record's own canonical.
            added_here.discard(chem["canonical_name"])
            new_syns = added_here - chem["synonyms"]
            if new_syns:
                chem["synonyms"].update(new_syns)
                records_augmented += 1
                synonyms_added += len(new_syns)

        print(
            f"  Augmented {records_augmented} records with "
            f"{synonyms_added} synonyms harvested from CHEBI xrefs"
        )

    def propagate_synonyms_via_xrefs(self):
        """
        Pull names across equivalent-CURIE records into each primary's synonyms.

        When one loader keys an entity by its top-ranked CURIE (e.g., a
        CHEBI-primary record with ``xrefs=[pubchem.compound:Y, cas:Z]``) and
        another loader independently created a record keyed by one of those
        xrefs, the two are semantically the same entity but live as separate
        rows. This pass reads each record's xrefs, looks up any that are
        themselves primary keys of other records, and merges the other
        record's ``canonical_name`` + ``synonyms`` into this record's
        synonyms. The operation is symmetric — the other record's xrefs
        typically include the first record's primary CURIE, so both sides
        pick up each other's names in a single pass.

        The name snapshot is taken up front so newly-added synonyms can't
        feed back and amplify. Canonical names are never reassigned — only
        the synonym set accumulates. No records are merged or deleted.
        """
        print("\nPropagating synonyms across equivalent-CURIE records via xrefs...")
        # Snapshot names by primary CURIE before mutation so propagation
        # uses a fixed input set (no feedback).
        name_snapshot: Dict[str, Set[str]] = {}
        for curie, chem in self.chemicals.items():
            names: Set[str] = set()
            if chem["canonical_name"]:
                names.add(chem["canonical_name"])
            names.update(s for s in chem["synonyms"] if s)
            if names:
                name_snapshot[curie] = names

        records_augmented = 0
        synonyms_added = 0
        for chem in self.chemicals.values():
            added_here: Set[str] = set()
            for xref in chem["xrefs"]:
                other_names = name_snapshot.get(xref)
                if not other_names:
                    continue
                # Exclude this record's own canonical name from the incoming
                # set — otherwise it would show up in synonyms.
                incoming = other_names - {chem["canonical_name"]}
                new_syns = incoming - chem["synonyms"]
                if new_syns:
                    added_here.update(new_syns)
            if added_here:
                chem["synonyms"].update(added_here)
                records_augmented += 1
                synonyms_added += len(added_here)

        print(
            f"  Augmented {records_augmented} records with "
            f"{synonyms_added} cross-CURIE synonyms"
        )

    def export_unified_sssom(self, sssom_output_path: Path):
        """
        Export the unified mapping as a standards-compliant SSSOM set.

        This is the single unified mapping product for kg-microbe. It is
        validated with the ``sssom`` package before write (both LinkML
        JSON-schema and ``check_all_prefixes_in_curie_map``). The runtime
        loader in ``kg_microbe.utils.chemical_mapping_utils`` reads this
        same file and reconstructs the entity-centric index in memory by
        grouping rows on ``object_id``.

        Free-text synonyms are materialised by minting a synthetic
        ``kgm.name:<slug>`` subject per normalised name. ``slug`` is the
        output of ``normalize_name`` with spaces replaced by ``_``. Multiple
        entries can share the same slug (name collisions across chemicals
        are rare but valid — SSSOM supports many-to-one / one-to-many
        mappings natively).

        Predicate semantics:
          * Identifier xrefs imported from public chemistry databases use
            ``skos:exactMatch``.
          * Canonical name → primary CURIE via ``kgm.name:`` uses
            ``skos:exactMatch`` with ``semapv:LexicalMatching``.
          * Free-text synonym → primary CURIE via ``kgm.name:`` uses
            ``skos:closeMatch`` with ``semapv:LexicalMatching`` (synonyms
            are textually close but not formally equivalent identifiers).
          * Bibliographic / descriptive xref prefixes (pubmed, patent,
            wikipedia.en, …) are not equivalence statements and are skipped
            rather than emitted with a misleading predicate.

        Formula and biolink category are per-entity attributes, not
        mappings. They are carried as SSSOM extension columns
        ``object_formula`` and ``object_category`` — declared in the
        mapping-set ``extension_definitions`` header — so the runtime
        loader can reconstruct the entity-centric view directly from
        this file without a separate TSV index.
        """
        import subprocess
        from datetime import date

        # Prefixes emitted as exactMatch equivalences. Everything else is
        # treated as bibliographic / descriptive and skipped.
        exact_prefixes = {
            "CHEBI", "FOODON", "UBERON", "ENVO", "NCIT",
            "kgmicrobe.compound",
            "mediadive.ingredient",
            "MIM", "MediaIngredientMech",
            "cas", "kegg.compound", "kegg.drug", "kegg.glycan",
            "pubchem.compound", "hmdb", "drugbank",
            "drugbank.metabolite", "chemspider", "lipidmaps",
            "lipidmaps_class", "metacyc.compound", "umbbd.compound",
            "knapsack", "foodb.food", "smid", "ymdb", "ecmdb",
            "resid", "lincs.smallmolecule", "drugcentral",
            "chemidplus", "agr", "ppdb", "pesticides", "molbase",
            "vsdb", "pdb", "pdb-ccd", "webelements", "cba", "bpdb",
            "reaxys", "fao_who_standards", "glytoucan", "glygen",
            "beilstein", "gmelin",
        }

        bibliographic_prefixes = {
            "pubmed", "pmc", "patent", "citexplore", "ppr", "wikipedia.en",
        }

        # URI expansions. Where the prefix has an obo/purl home we use it;
        # otherwise we fall back to bioregistry for a stable, resolvable IRI.
        prefix_map = {
            "CHEBI": "http://purl.obolibrary.org/obo/CHEBI_",
            "FOODON": "http://purl.obolibrary.org/obo/FOODON_",
            "UBERON": "http://purl.obolibrary.org/obo/UBERON_",
            "ENVO": "http://purl.obolibrary.org/obo/ENVO_",
            "NCIT": "http://purl.obolibrary.org/obo/NCIT_",
            "obo": "http://purl.obolibrary.org/obo/",
            "semapv": "https://w3id.org/semapv/vocab/",
            "skos": "http://www.w3.org/2004/02/skos/core#",
            "orcid": "https://orcid.org/",
            # MIM and MediaIngredientMech are two CURIE schemes over the same
            # sibling repo: MIM:<semantic_key> (used by the authoritative
            # SSSOM mapping set) vs MediaIngredientMech:<000NNN> (sequential
            # record identifiers). The SSSOM validator requires distinct URI
            # expansions per prefix, so they are differentiated by subpath.
            "MIM": "https://github.com/KG-Hub/MediaIngredientMech/blob/main/data/ingredients/mapped/",
            "MediaIngredientMech": "https://github.com/KG-Hub/MediaIngredientMech/blob/main/data/ingredients/records/",
            "kgmicrobe.compound": "https://w3id.org/kg-microbe/compound/",
            # MediaDive-minted fallback id. No upstream resolver; give it a
            # kg-microbe-scoped IRI so the SSSOM curie_map is complete.
            "mediadive.ingredient": "https://w3id.org/kg-microbe/mediadive/ingredient/",
            # kgm.name is a synthetic namespace minted by this exporter to
            # give free-text names/synonyms CURIE subjects so they can be
            # expressed as SSSOM mappings. Slugs are deterministic (see
            # normalize_name) so regenerations stay stable.
            "kgm.name": "https://w3id.org/kg-microbe/name/",
        }
        # Generic bioregistry fallback for everything else we emit.
        for prefix in sorted(exact_prefixes):
            if prefix not in prefix_map:
                prefix_map[prefix] = f"https://bioregistry.io/{prefix}:"

        # Git SHA for reproducibility in the mapping-set header.
        try:
            git_sha = (
                subprocess.check_output(
                    ["git", "-C", str(sssom_output_path.parent.parent), "rev-parse", "HEAD"],
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )
        except Exception:
            git_sha = "unknown"

        def _sanitize_tsv(value: str) -> str:
            if value is None:
                return ""
            return (
                str(value)
                .replace("\t", " ")
                .replace("\r", " ")
                .replace("\n", " ")
                .strip()
            )

        def _is_valid_curie(value: str) -> bool:
            if not value or ":" not in value:
                return False
            prefix, local = value.split(":", 1)
            return bool(prefix) and bool(local)

        def _slugify_name(name: str) -> str:
            """
            Produce a CURIE-safe slug from a free-text name.

            ``normalize_name`` lowercases and strips punctuation but keeps
            unicode letters (β/α/ζ/þ/υ/…) that the SSSOM validator rejects
            as invalid CURIE local IDs. Fold those to ASCII via NFKD
            decomposition + drop remaining non-ASCII, then substitute
            underscores for spaces. If folding empties the string, return
            "" so the caller can skip the row.
            """
            import unicodedata
            norm = normalize_name(name)
            if not norm:
                return ""
            folded = unicodedata.normalize("NFKD", norm).encode("ascii", "ignore").decode("ascii")
            folded = folded.replace(" ", "_")
            # Keep only CURIE-safe chars (pchar-ish: alnum, underscore, hyphen,
            # dot). Everything else collapses away.
            folded = re.sub(r"[^A-Za-z0-9_.\-]", "", folded)
            return folded.strip("_.-")

        # Counters for the summary line.
        xref_rows = 0
        name_rows = 0
        synonym_rows = 0
        skipped_self = 0
        skipped_biblio = 0
        skipped_unknown_prefix = 0
        skipped_malformed = 0
        skipped_empty_slug = 0

        mapping_rows = []
        today = date.today().isoformat()

        for curie in sorted(self.chemicals.keys()):
            chem = self.chemicals[curie]
            object_id = curie
            object_label = _sanitize_tsv(chem["canonical_name"])
            object_formula = _sanitize_tsv(chem.get("formula", ""))
            object_category = _sanitize_tsv(chem.get("category", ""))
            # Primary source prefix determines object_source when CHEBI.
            object_source = (
                "obo:chebi.owl" if object_id.startswith("CHEBI:")
                else f"obo:{object_id.split(':', 1)[0].lower()}.owl"
            )
            source_tag = "|".join(sorted(chem["sources"])) if chem["sources"] else ""

            def _row(subject_id, subject_label, predicate, justification, comment):
                return {
                    "subject_id": subject_id,
                    "subject_label": subject_label,
                    "predicate_id": predicate,
                    "object_id": object_id,
                    "object_label": object_label,
                    "object_source": object_source,
                    "mapping_justification": justification,
                    "source": source_tag,
                    "mapping_date": today,
                    "confidence": "",
                    "comment": comment,
                    "object_formula": object_formula,
                    "object_category": object_category,
                }

            for xref in sorted(chem["xrefs"]):
                if not _is_valid_curie(xref):
                    skipped_malformed += 1
                    continue
                subject_prefix = xref.split(":", 1)[0]
                if xref == object_id:
                    skipped_self += 1
                    continue
                if subject_prefix in bibliographic_prefixes:
                    skipped_biblio += 1
                    continue
                if subject_prefix not in exact_prefixes:
                    skipped_unknown_prefix += 1
                    continue

                mapping_rows.append(_row(
                    xref, "", "skos:exactMatch",
                    "semapv:UnspecifiedMatching", "",
                ))
                xref_rows += 1

            # Emit the canonical name as an exactMatch row via kgm.name:.
            # Skip if there's no canonical name (e.g. CHEBI:2 has no label).
            if chem["canonical_name"]:
                slug = _slugify_name(chem["canonical_name"])
                if slug:
                    mapping_rows.append(_row(
                        f"kgm.name:{slug}",
                        _sanitize_tsv(chem["canonical_name"]),
                        "skos:exactMatch",
                        "semapv:LexicalMatching",
                        "canonical_name",
                    ))
                    name_rows += 1
                else:
                    skipped_empty_slug += 1

            # Emit every synonym as a closeMatch row via kgm.name:. Avoid
            # duplicating the canonical slug — the canonical row already
            # carries exactMatch for that subject.
            canonical_slug = _slugify_name(chem["canonical_name"]) if chem["canonical_name"] else ""
            seen_synonym_slugs = {canonical_slug} if canonical_slug else set()
            for syn in sorted(chem["synonyms"]):
                slug = _slugify_name(syn)
                if not slug:
                    skipped_empty_slug += 1
                    continue
                if slug in seen_synonym_slugs:
                    continue
                seen_synonym_slugs.add(slug)
                mapping_rows.append(_row(
                    f"kgm.name:{slug}",
                    _sanitize_tsv(syn),
                    "skos:closeMatch",
                    "semapv:LexicalMatching",
                    "synonym",
                ))
                synonym_rows += 1

            # If this entity has formula or category but no xref/name/synonym
            # row was emitted (rare — e.g. CHEBI with only a formula, no
            # label/xrefs/synonyms), emit a self-row so the extension
            # attributes survive the round trip. Uses skos:exactMatch on
            # (object_id, object_id) with justification SemanticSimilarityMatching
            # would be wrong; instead we use MatchingProcess=unspecified and
            # mark it "attribute_carrier" so the loader knows not to treat
            # it as a mapping edge.
            if not chem["canonical_name"] and not chem["synonyms"] and not chem["xrefs"] and (object_formula or object_category):
                mapping_rows.append(_row(
                    object_id, "", "skos:exactMatch",
                    "semapv:UnspecifiedMatching", "attribute_carrier",
                ))

        rows_emitted = xref_rows + name_rows + synonym_rows

        # Build the header.
        header_lines = ["# curie_map:"]
        for prefix in sorted(prefix_map.keys()):
            header_lines.append(f'#   {prefix}: "{prefix_map[prefix]}"')
        header_lines += [
            '# license: "https://creativecommons.org/publicdomain/zero/1.0/"',
            '# mapping_set_id: "https://w3id.org/sssom/mappings/kg_microbe_unified_ingredients"',
            f'# mapping_set_version: "{today}"',
            '# mapping_set_description: "kg-microbe unified ingredient mappings (CHEBI + FOODON + UBERON + ENVO + NCIT + kgmicrobe.compound). Emitted from scripts/consolidate_chemical_mappings.py. Row types: (1) xref-CURIE → primary-CURIE as skos:exactMatch; (2) canonical-name via kgm.name:<slug> → primary-CURIE as skos:exactMatch / semapv:LexicalMatching; (3) free-text synonym via kgm.name:<slug> → primary-CURIE as skos:closeMatch / semapv:LexicalMatching. Per-row `comment` is empty for xrefs, `canonical_name` for name rows, `synonym` for synonym rows."',
            f'# mapping_date: "{today}"',
            f'# mapping_tool: "kg-microbe/scripts/consolidate_chemical_mappings.py@{git_sha}"',
            '# extension_definitions:',
            '#   - slot_name: source',
            '#     property: "https://w3id.org/kg-microbe/source"',
            '#     type_hint: "xsd:string"',
            '#   - slot_name: object_formula',
            '#     property: "https://w3id.org/kg-microbe/object_formula"',
            '#     type_hint: "xsd:string"',
            '#   - slot_name: object_category',
            '#     property: "https://w3id.org/kg-microbe/object_category"',
            '#     type_hint: "xsd:string"',
        ]

        column_order = [
            "subject_id", "subject_label", "predicate_id",
            "object_id", "object_label", "object_source",
            "mapping_justification", "source", "mapping_date",
            "confidence", "comment",
            "object_formula", "object_category",
        ]

        print(f"\nExporting unified SSSOM → {sssom_output_path}")
        sssom_output_path.parent.mkdir(parents=True, exist_ok=True)
        # Gzip if the output path ends in .gz — the sssom parser accepts
        # gzipped input transparently. Uncompressed the file is ~150 MB
        # (over GitHub's 100 MB per-file limit); compressed it is ~18 MB.
        import gzip
        open_fn = (
            (lambda p: gzip.open(p, "wt", encoding="utf-8"))
            if str(sssom_output_path).endswith(".gz")
            else (lambda p: p.open("w", encoding="utf-8"))
        )
        with open_fn(sssom_output_path) as fh:
            for line in header_lines:
                fh.write(line + "\n")
            fh.write("\t".join(column_order) + "\n")
            for row in mapping_rows:
                fh.write("\t".join(_sanitize_tsv(row.get(c, "")) for c in column_order) + "\n")

        print(
            f"  Emitted {rows_emitted} mappings "
            f"(xrefs={xref_rows}, names={name_rows}, synonyms={synonym_rows})"
        )
        print(
            f"  Skipped: self={skipped_self}, bibliographic={skipped_biblio}, "
            f"unknown_prefix={skipped_unknown_prefix}, malformed={skipped_malformed}, "
            f"empty_slug={skipped_empty_slug}"
        )

        # Round-trip validate with the sssom package.
        self._validate_sssom_file(sssom_output_path)


def main():
    """Main consolidation workflow."""
    base_dir = Path(__file__).parent.parent
    consolidator = ChemicalMappingConsolidator()

    sssom_output_path = base_dir / "mappings" / "unified_ingredient_mappings.sssom.tsv.gz"
    # Legacy TSV baselines. Read before the SSSOM baseline so the SSSOM
    # (the new source of truth) can overlay/supersede any stale values.
    # These paths are retired outputs — kept as read-only migration
    # fallbacks and deleted after the first SSSOM regeneration that
    # carries the extension columns forward.
    legacy_tsv_paths = [
        base_dir / "mappings" / "unified_chemical_mappings.tsv.gz",
        base_dir / "mappings" / "unified_other_mappings.tsv.gz",
    ]
    for legacy in legacy_tsv_paths:
        if legacy.exists():
            consolidator.load_existing_unified_tsv(legacy)

    # Seed from the existing unified SSSOM (single source of truth going
    # forward). Each row's sources contribute to the accumulated per-entity
    # source set; priority is inferred from the source labels.
    if sssom_output_path.exists():
        consolidator.load_existing_unified(sssom_output_path)

    # Load any legacy source files that still exist. Missing inputs are
    # silently skipped; their content is assumed to already be folded into
    # the existing unified baseline.
    optional_inputs = [
        ("primary_mappings", base_dir / "mappings" / "chemical_mappings.tsv",
         consolidator.load_primary_mappings),
        ("compound_mappings_strict", base_dir / "data" / "raw" / "compound_mappings_strict.tsv",
         consolidator.load_compound_mappings),
        ("compound_mappings_strict_hydrate",
         base_dir / "data" / "raw" / "compound_mappings_strict_hydrate.tsv",
         consolidator.load_compound_mappings),
        ("bacdive_metabolites",
         base_dir / "kg_microbe" / "transform_utils" / "bacdive" / "metabolite_mapping.json",
         consolidator.load_metabolite_json),
        ("chebi_xrefs",
         base_dir / "kg_microbe" / "transform_utils" / "ontologies" / "xrefs" / "chebi_xrefs.tsv",
         consolidator.load_chebi_xrefs),
        ("madin_manual_annotation",
         base_dir / "kg_microbe" / "transform_utils" / "madin_etal" / "chebi_manual_annotation.tsv",
         consolidator.load_manual_annotations),
        ("metatraits_chemical_mappings",
         base_dir / "kg_microbe" / "transform_utils" / "metatraits" / "mappings" / "chemical_mappings.tsv",
         consolidator.load_metatraits_chemical_mappings),
        ("metatraits_special_chemicals",
         base_dir / "kg_microbe" / "transform_utils" / "metatraits" / "mappings" / "special_chemical_mappings.tsv",
         consolidator.load_metatraits_special_chemicals),
    ]
    for name, path, loader in optional_inputs:
        if path.exists():
            loader(path)
        else:
            print(f"Skipping {name}: {path} not present")

    # Authoritative CultureBotAI reviewed mappings (required).
    consolidator.load_culturebotai_reviewed(
        base_dir / "mappings" / "culturebotai_reviewed_ingredients.tsv"
    )

    # Authoritative MediaIngredientMech SSSOM mapping set (required).
    # MIM sibling repo is the source of truth — sync the vendored copy first.
    mim_sssom_path = sync_mim_sssom(base_dir)
    consolidator.load_mediaingredientmech_sssom(mim_sssom_path)

    # Enrich with ChEBI synonyms
    consolidator.enrich_with_chebi_synonyms()

    # Harvest labels for CHEBI xrefs that never got their own primary row.
    consolidator.enrich_with_chebi_xref_labels()

    # Propagate names across equivalent-CURIE records via xrefs so losing
    # candidates' labels end up on the primary node as synonyms.
    consolidator.propagate_synonyms_via_xrefs()

    # Export the standards-compliant SSSOM — the single unified mapping
    # product. Runtime transforms read this same file via
    # ``kg_microbe.utils.chemical_mapping_utils``; the entity-centric TSV
    # index has been retired in favour of SSSOM-with-extension-columns.
    consolidator.export_unified_sssom(sssom_output_path)

    print(f"\n✓ Unified SSSOM created: {sssom_output_path}")
    print(f"  To inspect: gunzip -c {sssom_output_path.name} | head")


if __name__ == "__main__":
    main()
