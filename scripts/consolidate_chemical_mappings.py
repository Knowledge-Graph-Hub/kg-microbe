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
8. mappings/mediaingredientmech_reviewed_ingredients.csv - MediaIngredientMech (priority=11)

The CultureBotAI and MediaIngredientMech reviewed mappings are
evidence-based and manually curated. MediaIngredientMech is the
authoritative canonical-naming source (priority=11): its preferred_term
becomes the canonical_name shown in kg-microbe. The names actually
encountered in kg-microbe source data (BacDive, MediaDive, KEGG, …) that
map to the same CURIE are retained as synonyms, along with CultureBotAI
and MIM's own preferred_term.

Name lookup respects priority: when two sources map the same ingredient
name to different CURIEs, priority decides the winner
(MediaIngredientMech 11 > CultureBotAI 10 > madin_etal 5 > chebi_xrefs 2 >
primary sources 1). Matches can be direct (CURIE xref) or via a synonym.
Synonyms and xrefs always accumulate (set union) regardless of priority.

The unified mapping keys on a generic CURIE (`id`) rather than just ChEBI.
Chemicals proper plus ontologies used as media ingredients — CHEBI,
kgmicrobe.compound, NCIT, FOODON foods, UBERON anatomical ingredients
(e.g. "beef heart", "sheep blood"), ENVO media components (e.g.
"seawater") — are written to ``mappings/unified_chemical_mappings.tsv.gz``.
Any other CURIE prefix (reserved for future non-ingredient mappings such
as PO plant structures not used as media) goes to the sibling file
``mappings/unified_other_mappings.tsv.gz``. Both files share the same
schema; `category` stores the biolink class so downstream transforms can
classify without hardcoded prefix routing.

Outputs:
  mappings/unified_chemical_mappings.tsv.gz  (CHEBI, kgmicrobe.compound,
                                              NCIT, FOODON, UBERON, ENVO)
  mappings/unified_other_mappings.tsv.gz     (anything else, e.g. PO)

Columns: id, category, canonical_name, formula, synonyms, xrefs, sources.
Downstream readers that still expect the legacy `chebi_id` column name
auto-alias `id` → `chebi_id` on load.
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

import pandas as pd


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
    # KG-Microbe native prefix for chemicals with no public ontology ID
    # (antibiotics / secondary metabolites minted from metatraits).
    "kgmicrobe.compound": "biolink:ChemicalEntity",
}

# CURIE prefixes this consolidator accepts as a primary `id`. Other prefixes
# are treated as xrefs (see loaders).
_ACCEPTED_PREFIXES = tuple(f"{p}:" for p in _CATEGORY_BY_PREFIX.keys())

# Prefixes routed to the unified *chemical* file. Covers chemicals proper
# (CHEBI, kgmicrobe.compound, NCIT) *and* ontologies used for media
# ingredients (FOODON foods, UBERON anatomical ingredients like "beef heart"
# or "sheep blood", ENVO media components like "seawater"). Anything not
# listed here goes to the unified *other* file — reserved for future
# non-ingredient mappings (e.g. PO plant structures not used as media).
_CHEMICAL_PREFIXES = {
    "CHEBI",
    "kgmicrobe.compound",
    "NCIT",
    "FOODON",
    "UBERON",
    "ENVO",
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

        # Formula: higher-priority wins, same-priority keeps first non-empty.
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
        # name can resolve through either. When the same name would map
        # to different CURIEs from different sources, the higher-priority
        # source wins the lookup — MIM (priority 11) overrides
        # CultureBotAI (10) which overrides primary sources (priority 1).
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
            if priority > self.chemicals[existing_id]["priority"]:
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
        """Load kg_microbe/transform_utils/metatraits/mappings/chemical_mappings.tsv.

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
        """Load kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv.

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

    def load_existing_unified(self, filepath: Path):
        """
        Load an existing unified mappings TSV.GZ as a baseline.

        Accepts either ``unified_chemical_mappings.tsv.gz`` or
        ``unified_other_mappings.tsv.gz`` — the schema is identical and rows
        are filtered by their CURIE prefix on export, so the in-memory bag
        of entries is shared between the two files.

        The unified files are the source of truth once legacy per-source
        inputs have been archived. This loader re-ingests every row so that
        the consolidator can layer additional sources on top (via priority)
        without losing prior content.

        Priority is inferred from the ``sources`` column:
          - mediaingredientmech_reviewed → 11
          - culturebotai_reviewed        → 10
          - manual_annotation*           → 5
          - chebi_xrefs                  → 2
          - everything else              → 1
        """
        import gzip as _gzip

        print(f"Loading existing unified mapping from {filepath}...")
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

        # Legacy baselines used `chebi_id` as the key column. Accept either.
        id_column = "id" if "id" in df.columns else "chebi_id"

        # Guard against previously-polluted baselines: a single CURIE should
        # never legitimately have thousands of synonyms/xrefs. If a row is
        # visibly poisoned (past merge bugs concatenated many CHEBI entries
        # into one), drop those fields rather than carrying the damage
        # forward. Authoritative sources will re-supply the real values.
        POLLUTION_CAP = 500
        pollution_skipped = 0

        for _, row in df.iterrows():
            curie = row.get(id_column, "")
            if not is_accepted_primary(curie):
                continue
            synonyms = [s for s in row.get("synonyms", "").split("|") if s]
            xrefs = [x for x in row.get("xrefs", "").split("|") if x]
            sources = [s for s in row.get("sources", "").split("|") if s]
            if len(synonyms) > POLLUTION_CAP or len(xrefs) > POLLUTION_CAP:
                print(
                    f"  WARN: {curie} has {len(synonyms)} synonyms / "
                    f"{len(xrefs)} xrefs — dropping as polluted baseline"
                )
                synonyms = []
                xrefs = []
                pollution_skipped += 1
            priority = infer_priority(row.get("sources", ""))

            self.add_chemical(
                id=curie,
                canonical_name=row.get("canonical_name", ""),
                formula=row.get("formula", ""),
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
        print(f"  Loaded {len(df)} baseline entries")

    def load_culturebotai_reviewed(self, filepath: Path):
        """
        Load mappings/culturebotai_reviewed_ingredients.tsv.

        Authoritative: evidence-based and manually reviewed media-ingredient
        mappings from the CultureBotAI project. When this file asserts a
        canonical_name, CAS RN, CHEBI, or non-CHEBI ontology ID for an
        ingredient, the assertion overrides lower-priority sources.

        Columns consumed:
          - ingredient_name     → canonical_name (and added as synonym)
          - chebi_id            → primary key when present
          - culturemech_term_id → primary key fallback for FOODON/UBERON/ENVO
                                  ingredients (meat extract, beef heart,
                                  defibrinated sheep blood, seawater, …)
          - cas_rn              → xref (`cas:<number>`)
        """
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t", dtype=str).fillna("")

        added = 0
        skipped = 0
        for _, row in df.iterrows():
            ingredient_name = row.get("ingredient_name", "").strip()
            cas_rn = row.get("cas_rn", "").strip()
            culturemech_term = row.get("culturemech_term_id", "").strip()
            chebi_id = extract_chebi_id(row.get("chebi_id", ""))

            # Prefer CHEBI as primary when available; fall back to a non-CHEBI
            # CURIE in culturemech_term_id for food/anatomy/environment items.
            primary_id = chebi_id or (
                culturemech_term if is_accepted_primary(culturemech_term) else ""
            )
            if not primary_id:
                skipped += 1
                continue

            synonyms = [ingredient_name] if ingredient_name else []
            xrefs = []
            if cas_rn:
                xrefs.append(f"cas:{cas_rn}")
            if culturemech_term and culturemech_term != primary_id:
                xrefs.append(culturemech_term)

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

    def load_mediaingredientmech_reviewed(self, filepath: Path):
        """
        Load mappings/mediaingredientmech_reviewed_ingredients.csv.

        Authoritative: expert-curated media-ingredient → ontology mappings
        from the MediaIngredientMech project (sibling repo of kg-microbe).
        The file is an export of
        ``MediaIngredientMech/data/curated/mapped_ingredients_index.csv``.

        Columns consumed (CSV, comma-separated):
          - preferred_term   → canonical_name (and added as synonym)
          - ontology_id      → primary key (CHEBI/FOODON/UBERON/ENVO/…)
          - ontology_source  → prefix (informational; prefix is derived from
                               ontology_id)
          - mapping_status   → filter: only MAPPED rows are kept
          - occurrences      → informational only
          - id (MediaIngredientMech:NNNNNN) → xref

        REJECTED / NEEDS_EXPERT / ARCHIVED rows are skipped. Rows whose
        ``ontology_id`` prefix is not in the consolidator's accepted set
        are also skipped.
        """
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, dtype=str).fillna("")

        added = 0
        skipped_unsupported = 0
        skipped_not_mapped = 0
        for _, row in df.iterrows():
            if row.get("mapping_status", "").strip() != "MAPPED":
                skipped_not_mapped += 1
                continue

            ontology_id = row.get("ontology_id", "").strip()
            if not is_accepted_primary(ontology_id):
                # Try to recover CHEBI from numeric-only values.
                recovered = extract_chebi_id(ontology_id)
                if not recovered:
                    skipped_unsupported += 1
                    continue
                ontology_id = recovered

            preferred_term = row.get("preferred_term", "").strip()
            mim_id = row.get("id", "").strip()

            synonyms = [preferred_term] if preferred_term else []
            xrefs = [mim_id] if mim_id.startswith("MediaIngredientMech:") else []

            # MIM is the canonical naming source for kg-microbe: its
            # preferred_term becomes the canonical_name for the resolved
            # CURIE, and kg-microbe source data terms that map to the same
            # CURIE (loaded at priority=1) are retained in the synonyms set.
            self.add_chemical(
                id=ontology_id,
                canonical_name=preferred_term,
                synonyms=synonyms,
                xrefs=xrefs,
                source="mediaingredientmech_reviewed",
                priority=11,
            )
            added += 1

        print(
            f"  Loaded {added} MIM reviewed entries "
            f"(skipped {skipped_unsupported} unsupported prefix, "
            f"{skipped_not_mapped} not-MAPPED)"
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

    def export_unified_mapping(
        self,
        chemical_output_path: Path,
        other_output_path: Path,
    ):
        """
        Export the unified mapping, split across two files by CURIE prefix.

        Chemical/ingredient entries (see ``_CHEMICAL_PREFIXES``) go to
        ``chemical_output_path``; everything else goes to
        ``other_output_path``. The "other" file is only written if there is
        at least one qualifying row (empty files are left alone rather than
        created with just a header).
        """
        print(
            f"\nExporting unified mapping split:\n"
            f"  chemical → {chemical_output_path}\n"
            f"  other    → {other_output_path}"
        )

        def _sanitize(value):
            """
            Strip tab/newline/pipe characters from a single field value.

            Needed because ChEBI aliases occasionally contain literal tabs or
            newlines (e.g. IUPAC names with embedded whitespace) which would
            otherwise corrupt the TSV and break downstream pandas parsing.
            """
            if value is None:
                return ""
            return (
                str(value)
                .replace("\t", " ")
                .replace("\r", " ")
                .replace("\n", " ")
                .replace("|", ";")
                .strip()
            )

        def _sort_key(curie: str):
            """Sort: prefix alphabetically, numeric local ID ascending when numeric."""
            prefix, _, local = curie.partition(":")
            try:
                return (prefix, 0, int(local))
            except ValueError:
                return (prefix, 1, local)

        chemical_records = []
        other_records = []
        for curie in sorted(self.chemicals.keys(), key=_sort_key):
            chem = self.chemicals[curie]

            # Sort and join synonyms/xrefs/sources. Sanitize each value
            # exactly once per element — earlier versions sanitized twice
            # (once in the `if` clause and once in the set comprehension),
            # which is measurable overhead on large synonym sets.
            def _clean_set(values):
                out = set()
                for v in values:
                    if v is None:
                        continue
                    cleaned = _sanitize(v)
                    if cleaned:
                        out.add(cleaned)
                return sorted(out)

            synonyms_list = _clean_set(chem["synonyms"])
            synonyms_str = "|".join(synonyms_list) if synonyms_list else ""

            xrefs_list = _clean_set(chem["xrefs"])
            xrefs_str = "|".join(xrefs_list) if xrefs_list else ""

            sources_list = _clean_set(chem["sources"])
            sources_str = "|".join(sources_list) if sources_list else ""

            record = {
                "id": curie,
                "category": _sanitize(chem["category"]),
                "canonical_name": _sanitize(chem["canonical_name"]),
                "formula": _sanitize(chem["formula"]),
                "synonyms": synonyms_str,
                "xrefs": xrefs_str,
                "sources": sources_str,
            }
            if is_chemical_curie(curie):
                chemical_records.append(record)
            else:
                other_records.append(record)

        # Chemical file is always written (even if empty, so downstream
        # consumers have a stable path).
        pd.DataFrame(chemical_records).to_csv(
            chemical_output_path, sep="\t", index=False, compression="gzip"
        )

        # Other file is only written if there are rows to put in it — avoids
        # littering the repo with an empty placeholder. If a stale file from
        # a prior run would otherwise be re-ingested as baseline next time,
        # remove it so the export state matches the current split.
        if other_records:
            pd.DataFrame(other_records).to_csv(
                other_output_path, sep="\t", index=False, compression="gzip"
            )
        elif other_output_path.exists():
            other_output_path.unlink()

        def _syn_xref_totals(records):
            syns = sum(len(r["synonyms"].split("|")) for r in records if r["synonyms"])
            xs = sum(len(r["xrefs"].split("|")) for r in records if r["xrefs"])
            return syns, xs

        chem_syn, chem_xref = _syn_xref_totals(chemical_records)
        other_syn, other_xref = _syn_xref_totals(other_records)

        print(f"  Chemical entries: {len(chemical_records)} "
              f"(synonyms: {chem_syn}, xrefs: {chem_xref})")
        if other_records:
            print(f"  Other entries:    {len(other_records)} "
                  f"(synonyms: {other_syn}, xrefs: {other_xref})")
        else:
            print("  Other entries:    0 (file not written)")


def main():
    """Main consolidation workflow."""
    base_dir = Path(__file__).parent.parent
    consolidator = ChemicalMappingConsolidator()

    chemical_output_path = base_dir / "mappings" / "unified_chemical_mappings.tsv.gz"
    other_output_path = base_dir / "mappings" / "unified_other_mappings.tsv.gz"

    # Seed from any existing unified files (split or legacy single-file).
    # Each row preserves its source labels; priority is inferred from them.
    for baseline in (chemical_output_path, other_output_path):
        if baseline.exists():
            consolidator.load_existing_unified(baseline)

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

    # Authoritative MediaIngredientMech reviewed mappings (required).
    consolidator.load_mediaingredientmech_reviewed(
        base_dir / "mappings" / "mediaingredientmech_reviewed_ingredients.csv"
    )

    # Enrich with ChEBI synonyms
    consolidator.enrich_with_chebi_synonyms()

    # Export unified mapping (split into chemical + other files)
    consolidator.export_unified_mapping(chemical_output_path, other_output_path)

    print(f"\n✓ Unified chemical mapping created: {chemical_output_path}")
    if other_output_path.exists():
        print(f"✓ Unified other mapping created:    {other_output_path}")
    print(f"  To use: gunzip -c {chemical_output_path.name} | head")


if __name__ == "__main__":
    main()
