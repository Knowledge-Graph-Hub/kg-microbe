#!/usr/bin/env python3
"""
Emit METPO proposal TSVs containing only terms that do not already exist in METPO.

The proposal lists below are validated at generation time against the local METPO
snapshot (``data/transformed/ontologies/metpo_nodes.tsv``) so that we do not propose
classes or properties that already exist by label or synonym. Concepts that *did*
collide during the 2026-04 audit are recorded in ``EXISTING_METPO_ALIASES`` and
written to ``mappings/metpo_existing_aliases.tsv`` so downstream transforms can
adopt the existing METPO IDs instead of minting new ones.

Outputs:
    mappings/metpo_proposal_quantitative.tsv         - datatype properties + numeric
                                                       tolerance class forms (min/max)
    mappings/metpo_proposal_categorical.tsv          - parent classes + categorical children
    mappings/metpo_existing_aliases.tsv              - proposed concept -> existing METPO ID
    mappings/metpo_proposal_classes_robot.tsv        - ROBOT template (OWL classes) for
                                                       upstream submission
    mappings/metpo_proposal_properties_robot.tsv     - ROBOT template (OWL properties) for
                                                       upstream submission
    kg_microbe/transform_utils/metatraits/mappings/metpo_alias_mappings.tsv
        Tier-2 override file consumed by metatraits transform.

Validation:
    1. ``validate_against_metpo`` rejects label/synonym collisions with the existing METPO.
    2. ``validate_bacdive_observation_counts`` checks hardcoded ``observations`` against
       ``data/raw/bacdive_strains.json``.
    3. ``validate_metatraits_placeholder_coverage`` ensures every kgmicrobe.* placeholder
       in metatraits edges is covered by a proposed Term.
    4. ``validate_with_robot`` runs ``robot template`` + ``robot merge`` +
       ``robot reason --reasoner ELK`` to catch OWL-level errors and unsatisfiable classes.

Source of truth for term content: notes/METPO_UNIFIED_PROPOSAL_5_PHASES.md and
notes/METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md plus the 2026-04 audit against
``data/transformed/ontologies/metpo_nodes.tsv`` and ``data/raw/bacdive_strains.json``.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

HEADER = [
    "proposed_id",
    "scope",
    "term_type",
    "label",
    "definition",
    "parent_or_subproperty",
    "domain",
    "range",
    "xrefs",
    "synonyms",
    "priority",
    "traits_addressed",
    "observations",
]

ALIAS_HEADER = [
    "proposed_label",
    "proposed_synonyms",
    "existing_metpo_id",
    "existing_metpo_label",
    "existing_metpo_synonyms",
    "match_kind",
    "notes",
]

# Schema used by kg_microbe.utils.microbial_trait_mappings.load_microbial_trait_mappings()
TRAIT_MAPPINGS_HEADER = [
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
]

METATRAITS_MAPPINGS_DIR = Path("kg_microbe/transform_utils/metatraits/mappings")


@dataclass
class Term:

    """
    One proposed METPO term.

    `scope` selects the output TSV: 'quantitative' (numeric value or numeric
    tolerance class) vs. 'categorical' (parent class or enumerated child).
    """

    proposed_id: str
    term_type: str
    label: str
    definition: str
    scope: str = "categorical"
    parent_or_subproperty: str = ""
    domain: str = ""
    range: str = ""
    xrefs: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)
    priority: str = ""
    traits_addressed: str = ""
    observations: str = ""

    def as_row(self) -> List[str]:
        """Return the row in TSV column order."""
        return [
            self.proposed_id,
            self.scope,
            self.term_type,
            self.label,
            self.definition,
            self.parent_or_subproperty,
            self.domain,
            self.range,
            "|".join(self.xrefs),
            "|".join(self.synonyms),
            self.priority,
            self.traits_addressed,
            self.observations,
        ]


@dataclass
class Alias:

    """A proposed concept that already exists in METPO under a different ID."""

    proposed_label: str
    proposed_synonyms: List[str]
    existing_metpo_id: str
    existing_metpo_label: str
    match_kind: str  # "label", "synonym", "concept"
    notes: str = ""


ORG = "biolink:OrganismTaxon"

METPO_SNAPSHOT = Path("data/transformed/ontologies/metpo_nodes.tsv")
_PHENO_PARENT = "METPO:1000000"

# BacDive raw data — used by `compute_bacdive_observations` to validate the hardcoded
# `observations` counts on the categorical child Terms. The keys are child Term labels
# and the values are the expected occurrence counts from BacDive at the time the
# proposal was authored. The `BACDIVE_RULES` dict describes how to derive each count.
BACDIVE_SNAPSHOT = Path("data/raw/bacdive_strains.json")

# Metatraits transform output. Used by `validate_metatraits_placeholder_coverage`
# to scan emitted edges for `kgmicrobe.{trait,activity}:*` placeholder objects
# and confirm every one has a proposed METPO term in this proposal. Compounds
# (`kgmicrobe.compound:*`) are out of METPO scope (they are chemicals → CHEBI)
# and are intentionally excluded from the gap check.
METATRAITS_EDGES_PATH = Path("data/transformed/metatraits/edges.tsv")

# Migration map from `kgmicrobe.*` placeholder CURIEs to the proposed METPO IDs
# defined in PHASE_4_TERMS (categorical). Every key MUST appear as an `object`
# in metatraits edges; every value MUST be a Term in PHASE_4_TERMS. The
# extractor cross-checks both directions on each run.
KGMICROBE_PLACEHOLDER_MIGRATION: Dict[str, str] = {
    "kgmicrobe.trait:macconkey_agar_growth": "METPO:1007053",
    "kgmicrobe.trait:blood_agar_growth": "METPO:1007054",
    "kgmicrobe.trait:bile_susceptible": "METPO:1007056",
    "kgmicrobe.activity:coagulase_activity": "METPO:1007089",
}

BACDIVE_BASELINE_COUNTS: Dict[str, int] = {
    # Flagellum arrangement — comma-separated values; match by token presence.
    "polytrichous flagellation": 4,
    # Colony shape — exact value match. 'circular colony' aggregates BacDive
    # 'circular' (2436) + 'round' (213) since 'round colony' is its synonym.
    "circular colony": 2649,
    "irregular colony": 148,
    "filamentous colony": 16,
    "punctiform colony": 11,
    "rhizoid colony": 8,
    "fried-egg-shaped colony": 6,
}

# How to extract each count from BacDive: (json_path, list of acceptable values, match_kind).
# match_kind="exact": value (lowercased, stripped) must equal one of the tokens.
# match_kind="token": split on comma; any part (lowercased, stripped) must equal a token.
_BACDIVE_RULES: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...], str]] = {
    "polytrichous flagellation": (
        ("Morphology", "cell morphology", "flagellum arrangement"),
        ("polytrichous",),
        "token",
    ),
    "circular colony": (
        ("Morphology", "colony morphology", "colony shape"),
        ("circular", "round"),
        "exact",
    ),
    "irregular colony": (
        ("Morphology", "colony morphology", "colony shape"),
        ("irregular",),
        "exact",
    ),
    "filamentous colony": (
        ("Morphology", "colony morphology", "colony shape"),
        ("filamentous",),
        "exact",
    ),
    "punctiform colony": (
        ("Morphology", "colony morphology", "colony shape"),
        ("punctiform",),
        "exact",
    ),
    "rhizoid colony": (
        ("Morphology", "colony morphology", "colony shape"),
        ("rhizoid",),
        "exact",
    ),
    "fried-egg-shaped colony": (
        ("Morphology", "colony morphology", "colony shape"),
        ("fried-egg-shaped",),
        "exact",
    ),
}


# --------------------------------------------------------------------------- #
# Concepts that already exist in METPO. Audit on 2026-04-23 against
# data/transformed/ontologies/metpo_nodes.tsv (432 rows). Downstream transforms
# (metatraits, bacdive, ...) MUST resolve these labels to the existing METPO IDs
# rather than emitting `METPO:1007*` placeholders.
# --------------------------------------------------------------------------- #
EXISTING_METPO_ALIASES: List[Alias] = [
    # Phase 1: temperature/pH/salinity min & max -> existing datatype properties
    Alias("has growth temperature minimum", [],
          "METPO:2000702", "has minimum temperature value", "concept",
          "Phase 1 datatype property already exists; reuse for min growth temperature."),
    Alias("has growth temperature maximum", [],
          "METPO:2000703", "has maximum temperature value", "concept",
          "Phase 1 datatype property already exists; reuse for max growth temperature."),
    Alias("has NaCl concentration minimum", [],
          "METPO:2000708", "has minimum salinity value", "concept",
          "Phase 1 datatype property already exists; reuse for min NaCl concentration."),
    Alias("has NaCl concentration maximum", [],
          "METPO:2000709", "has maximum salinity value", "concept",
          "Phase 1 datatype property already exists; reuse for max NaCl concentration."),
    Alias("has pH minimum", [],
          "METPO:2000705", "has minimum pH value", "concept",
          "Phase 1 datatype property already exists; reuse for min growth pH."),
    Alias("has pH maximum", [],
          "METPO:2000706", "has maximum pH value", "concept",
          "Phase 1 datatype property already exists; reuse for max growth pH."),

    # Phase 4: morphology / genomics / tolerances / biochemical tests
    Alias("cell shape", ["cellular morphology", "rod-shaped", "coccus", "spiral", "filamentous"],
          "METPO:1000666", "cell shape", "label",
          "Existing class with rich children (rod shaped, coccus shaped, spiral shaped, ...)."),
    Alias("cell length", ["cellular length"],
          "METPO:1000881", "cell length", "label",
          "Existing class. Datatype property METPO:2000721 'has cell length value' "
          "covers the numeric value."),
    Alias("cell width", ["cellular width", "cell diameter"],
          "METPO:1000882", "cell width", "label",
          "Existing class. Datatype property METPO:2000722 'has cell width value' "
          "covers the numeric value."),
    Alias("cell color", ["cell pigmentation", "colony color"],
          "METPO:1003021", "pigmentation", "synonym",
          "'cell color' is already a synonym of METPO:1003021 'pigmentation'."),
    Alias("GC content percentage", ["GC%", "mol% G+C", "genomic GC content"],
          "METPO:1000127", "GC content", "synonym",
          "'GC percentage' is already a synonym of METPO:1000127. Datatype property "
          "METPO:2000715 'has GC percentage value' covers the numeric value."),
    Alias("genome size", ["genome length", "genomic size"],
          "METPO:2000711", "has genome size value", "synonym",
          "'genome size' is already a synonym of the datatype property METPO:2000711."),
    Alias("gene count", ["number of genes", "total gene count"],
          "METPO:2000713", "has gene count value", "synonym",
          "'gene count' is already a synonym of the datatype property METPO:2000713."),
    Alias("coding density", ["coding sequence percentage", "protein-coding percentage"],
          "METPO:2000716", "has coding density value", "synonym",
          "'coding density' is already a synonym of the datatype property METPO:2000716."),
    Alias("oxygen requirement",
          ["aerobic", "anaerobic", "facultative anaerobic", "microaerophilic", "aerotolerant"],
          "METPO:1000601", "oxygen preference", "concept",
          "Existing parent class with full oxygen-requirement child set "
          "(METPO:1000602-1000612)."),
    Alias("pH tolerance range", [],
          "METPO:1000332", "pH range", "concept",
          "METPO:1000332 'pH range' already models the tolerated pH window."),
    Alias("pH optimum", [],
          "METPO:1000331", "pH optimum", "label",
          "Exact label match."),
    Alias("temperature tolerance range", [],
          "METPO:1000306", "temperature range", "concept",
          "METPO:1000306 'temperature range' already models the tolerated temperature window."),
    Alias("temperature optimum", [],
          "METPO:1000304", "temperature optimum", "label",
          "Exact label match."),
    Alias("salinity tolerance range", [],
          "METPO:1000334", "NaCl range", "concept",
          "METPO:1000334 'NaCl range' already models the tolerated salinity window."),
    Alias("salinity optimum", [],
          "METPO:1000333", "NaCl optimum", "concept",
          "METPO:1000333 'NaCl optimum' already models the optimal salinity."),
    Alias("indole production capability", ["indole test positive"],
          "METPO:1005011", "indole test positive", "synonym",
          "'indole test positive' is the existing label."),
    Alias("methyl red test positive", ["MR test positive"],
          "METPO:1005014", "methyl red test positive", "label",
          "Exact label match."),
    Alias("hemolytic activity", ["hemolysis", "alpha-hemolysis", "beta-hemolysis", "gamma-hemolysis"],
          "METPO:1005025", "hemolysis", "synonym",
          "'hemolysis' is the existing METPO label."),
    Alias("biosafety level classification", ["BSL classification", "BSL-1", "BSL-2", "BSL-3", "BSL-4"],
          "METPO:1001101", "biosafety level", "concept",
          "Existing parent class with BSL-1..BSL-5 children (METPO:1001102-1001106)."),
    Alias("colony pigmentation", [],
          "METPO:1003021", "pigmentation", "concept",
          "Same concept as METPO:1003021 'pigmentation' (children: black, brown, "
          "cream, green, orange, pink, red, white, yellow, carotenoid)."),
    Alias("motility phenotype", ["motile", "non-motile"],
          "METPO:1000701", "motility", "concept",
          "Existing parent class with motile/non-motile/flagellated/gliding children."),

    # Phase 6
    Alias("spore formation capability", [],
          "METPO:1000870", "sporulation", "synonym",
          "'spore formation' is already a synonym of METPO:1000870; children "
          "spore-forming/non-spore-forming exist."),
    Alias("denitrification capability", [],
          "METPO:1005038", "denitrification", "concept",
          "Existing class. Predicate METPO:2000601 'denitrifies' / 2000602 "
          "'does not denitrify' for capability assertions."),
]


# --------------------------------------------------------------------------- #
# QUANTITATIVE: numeric values (datatype properties) + class forms for numeric
# tolerance limits (min/max). Companion to existing METPO datatype properties
# METPO:2000702/2000703/2000705/2000706/2000708/2000709.
# --------------------------------------------------------------------------- #
QUANTITATIVE_TERMS: List[Term] = [
    # Datatype properties — only "optimum" form is missing in METPO.
    Term(
        proposed_id="METPO:has_growth_temperature_optimum",
        scope="quantitative",
        term_type="DatatypeProperty",
        label="has growth temperature optimum",
        definition=(
            "The optimal temperature at which an organism achieves maximum growth rate, "
            "measured in degrees Celsius."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["UO:0000027"],
        priority="CRITICAL",
        traits_addressed="1",
        observations="85311",
    ),
    Term(
        proposed_id="METPO:has_NaCl_concentration_optimum",
        scope="quantitative",
        term_type="DatatypeProperty",
        label="has NaCl concentration optimum",
        definition=(
            "The optimal sodium chloride (NaCl) concentration for growth, "
            "expressed as weight/volume percentage."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["UO:0000187", "CHEBI:26710"],
        priority="CRITICAL",
        traits_addressed="1",
        observations="85311",
    ),
    Term(
        proposed_id="METPO:has_pH_optimum",
        scope="quantitative",
        term_type="DatatypeProperty",
        label="has pH optimum",
        definition=(
            "The optimal pH value for growth on the pH scale (0-14). Note: METPO:1000331 "
            "models pH optimum as a *class*; this datatype property carries the numeric value."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["PATO:0001842"],
        priority="HIGH",
        traits_addressed="1",
        observations="5479",
    ),
    # Class forms for tolerance min/max (companion to existing datatype properties).
    Term(
        proposed_id="METPO:1007022",
        scope="quantitative",
        term_type="Class",
        label="pH minimum tolerance",
        definition=(
            "An environmental quality (class form) that describes the minimum pH value "
            "supporting growth. Companion to datatype property METPO:2000705."
        ),
        parent_or_subproperty="METPO:1000332",
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007023",
        scope="quantitative",
        term_type="Class",
        label="pH maximum tolerance",
        definition=(
            "An environmental quality (class form) that describes the maximum pH value "
            "supporting growth. Companion to datatype property METPO:2000706."
        ),
        parent_or_subproperty="METPO:1000332",
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007026",
        scope="quantitative",
        term_type="Class",
        label="temperature minimum tolerance",
        definition=(
            "An environmental quality (class form) that describes the minimum temperature "
            "supporting growth. Companion to datatype property METPO:2000702."
        ),
        parent_or_subproperty="METPO:1000306",
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007027",
        scope="quantitative",
        term_type="Class",
        label="temperature maximum tolerance",
        definition=(
            "An environmental quality (class form) that describes the maximum temperature "
            "supporting growth. Companion to datatype property METPO:2000703."
        ),
        parent_or_subproperty="METPO:1000306",
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007030",
        scope="quantitative",
        term_type="Class",
        label="salinity minimum tolerance",
        definition=(
            "An environmental quality (class form) that describes the minimum salinity/NaCl "
            "concentration supporting growth. Companion to datatype property METPO:2000708."
        ),
        parent_or_subproperty="METPO:1000334",
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007031",
        scope="quantitative",
        term_type="Class",
        label="salinity maximum tolerance",
        definition=(
            "An environmental quality (class form) that describes the maximum salinity/NaCl "
            "concentration supporting growth. Companion to datatype property METPO:2000709."
        ),
        parent_or_subproperty="METPO:1000334",
        priority="HIGH",
    ),
]


# --------------------------------------------------------------------------- #
# CATEGORICAL: parent classes + enumerated children sourced from BacDive
# (data/raw/bacdive_strains.json) and existing kgmicrobe.trait:* placeholders
# in kg_microbe/transform_utils/metatraits/mappings/phenotype_mappings.tsv.
# --------------------------------------------------------------------------- #
CATEGORICAL_TERMS: List[Term] = [
    # ----- Flagellar arrangement -----
    # Parent class. METPO already has 7 children (METPO:1005031-1005037);
    # they currently lack a shared parent.
    Term(
        proposed_id="METPO:1007005",
        scope="categorical",
        term_type="Class",
        label="flagellar arrangement",
        definition=(
            "A phenotypic quality describing the arrangement pattern of flagella on a "
            "bacterial or archaeal cell. Parent class for METPO:1005031-1005037 "
            "(peritrichous, polar, amphitrichous, lophotrichous, monotrichous, lateral, "
            "subpolar)."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        xrefs=["GO:0001539"],
        synonyms=["flagellation pattern"],
        priority="HIGH",
    ),
    # Polytrichous is the only flagellation child not yet in METPO. BacDive
    # uses 'polytrichous, monopolar' (4 strains) — 'monopolar' is treated as a
    # synonym of polar (METPO:1005032), so only 'polytrichous flagellation' is added.
    Term(
        proposed_id="METPO:1007006",
        scope="categorical",
        term_type="Class",
        label="polytrichous flagellation",
        definition="Multiple flagella per cell (typically a tuft); often combined with polar attachment.",
        parent_or_subproperty="METPO:1007005",
        synonyms=["polytrichous"],
        priority="MEDIUM",
        observations="4",
    ),

    # ----- Selective media growth capability -----
    # Parent + children migrating placeholders kgmicrobe.trait:macconkey_agar_growth /
    # kgmicrobe.trait:blood_agar_growth / kgmicrobe.trait:bile_susceptible from
    # phenotype_mappings.tsv into METPO.
    Term(
        proposed_id="METPO:1007050",
        scope="categorical",
        term_type="Class",
        label="selective media growth capability",
        definition="A phenotypic capability describing the ability to grow on selective or differential media.",
        parent_or_subproperty=_PHENO_PARENT,
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007053",
        scope="categorical",
        term_type="Class",
        label="growth on MacConkey agar",
        definition=(
            "Capability to grow on MacConkey agar; differential medium typically used to "
            "distinguish lactose-fermenting Gram-negative bacteria."
        ),
        parent_or_subproperty="METPO:1007050",
        synonyms=["MacConkey agar growth", "grows on MacConkey agar"],
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007054",
        scope="categorical",
        term_type="Class",
        label="growth on blood agar",
        definition=(
            "Capability to grow on blood agar; enriched medium typically used for fastidious "
            "organisms and hemolysis assessment."
        ),
        parent_or_subproperty="METPO:1007050",
        synonyms=["blood agar growth", "grows on blood agar"],
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007055",
        scope="categorical",
        term_type="Class",
        label="growth on EMB agar",
        definition=(
            "Capability to grow on Eosin Methylene Blue (EMB) agar; selective and "
            "differential medium for Gram-negative enteric bacteria."
        ),
        parent_or_subproperty="METPO:1007050",
        synonyms=["EMB agar growth", "Eosin Methylene Blue agar growth"],
        priority="LOW",
    ),
    # Bile-acid response hierarchy: a neutral parent (METPO:1007051) groups
    # the assay outcomes for bile-acid challenge. Susceptibility (growth
    # inhibited) lives under the neutral response parent — NOT under a
    # "selective media growth" parent, which would imply the opposite
    # polarity (i.e. that susceptible taxa can grow on the selective
    # medium).
    Term(
        proposed_id="METPO:1007051",
        scope="categorical",
        term_type="Class",
        label="bile acid response",
        definition=(
            "A phenotypic quality describing the organism's growth response when "
            "challenged with bile acids or bile salts. Encompasses both "
            "tolerance/resistance (growth proceeds) and susceptibility (growth "
            "is inhibited); the specific outcome is asserted by child classes."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        xrefs=["CHEBI:3098"],
        synonyms=["bile resistance", "bile tolerance", "bile salt response"],
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007056",
        scope="categorical",
        term_type="Class",
        label="bile acid susceptible",
        definition="Phenotype where growth is inhibited by bile acids or bile salts.",
        parent_or_subproperty="METPO:1007051",
        xrefs=["CHEBI:3098"],
        synonyms=["growth: bile acid susceptible"],
        priority="LOW",
    ),

    # ----- Colony morphology -----
    # Parent + colony-shape children sourced from BacDive (15 distinct colony
    # shape values; 6 cover >99% of observations: circular, irregular,
    # filamentous, punctiform, rhizoid, fried-egg).
    Term(
        proposed_id="METPO:1007062",
        scope="categorical",
        term_type="Class",
        label="colony morphology",
        definition=(
            "A phenotypic quality describing macroscopic colony characteristics "
            "(shape, margin, elevation, surface, color, size)."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        xrefs=["PATO:0000052"],
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007063",
        scope="categorical",
        term_type="Class",
        label="colony shape",
        definition=(
            "Subaspect of colony morphology describing the overall macroscopic colony "
            "outline as observed on solid medium."
        ),
        parent_or_subproperty="METPO:1007062",
        xrefs=["PATO:0000052"],
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007064",
        scope="categorical",
        term_type="Class",
        label="circular colony",
        definition="Colony with a regular round outline.",
        parent_or_subproperty="METPO:1007063",
        synonyms=["round colony"],
        priority="LOW",
        observations="2649",
    ),
    Term(
        proposed_id="METPO:1007065",
        scope="categorical",
        term_type="Class",
        label="irregular colony",
        definition="Colony with an irregular (non-round, non-rhizoid) outline.",
        parent_or_subproperty="METPO:1007063",
        priority="LOW",
        observations="148",
    ),
    Term(
        proposed_id="METPO:1007066",
        scope="categorical",
        term_type="Class",
        label="filamentous colony",
        definition="Colony with thread-like or filamentous outline.",
        parent_or_subproperty="METPO:1007063",
        priority="LOW",
        observations="16",
    ),
    Term(
        proposed_id="METPO:1007067",
        scope="categorical",
        term_type="Class",
        label="punctiform colony",
        definition="Very small (pinpoint) colony, typically <1 mm diameter.",
        parent_or_subproperty="METPO:1007063",
        priority="LOW",
        observations="11",
    ),
    Term(
        proposed_id="METPO:1007068",
        scope="categorical",
        term_type="Class",
        label="rhizoid colony",
        definition="Colony with branching, root-like outline.",
        parent_or_subproperty="METPO:1007063",
        priority="LOW",
        observations="8",
    ),
    Term(
        proposed_id="METPO:1007069",
        scope="categorical",
        term_type="Class",
        label="fried-egg-shaped colony",
        definition="Colony with raised opaque centre and translucent peripheral zone, resembling a fried egg.",
        parent_or_subproperty="METPO:1007063",
        synonyms=["fried-egg colony"],
        priority="LOW",
        observations="6",
    ),

    # ----- Phase 6: tolerances + biochemical activities -----
    Term(
        proposed_id="METPO:1007070",
        scope="categorical",
        term_type="Class",
        label="pressure tolerance",
        definition="A phenotypic quality describing the ability to grow under elevated hydrostatic pressure.",
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["barophile", "piezophile"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007071",
        scope="categorical",
        term_type="Class",
        label="barophile phenotype",
        definition="An organism that requires or tolerates elevated hydrostatic pressure for growth.",
        parent_or_subproperty="METPO:1007070",
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007072",
        scope="categorical",
        term_type="Class",
        label="radiation tolerance",
        definition="A phenotypic quality describing the ability to withstand ionizing or UV radiation.",
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["radioresistant"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007073",
        scope="categorical",
        term_type="Class",
        label="osmotic tolerance",
        definition="A phenotypic quality describing the ability to grow under high osmotic pressure (non-NaCl).",
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["osmophile"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007074",
        scope="categorical",
        term_type="Class",
        label="metal tolerance",
        definition=(
            "A phenotypic quality describing the ability to grow in the presence of "
            "elevated metal concentrations."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["metallophile"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007076",
        scope="categorical",
        term_type="Class",
        label="capsule presence",
        definition="A phenotypic quality describing the presence of an extracellular polysaccharide capsule.",
        parent_or_subproperty=_PHENO_PARENT,
        xrefs=["GO:0042597"],
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007077",
        scope="categorical",
        term_type="Class",
        label="biofilm formation capability",
        definition="A phenotypic capability describing the ability to form surface-attached biofilms.",
        parent_or_subproperty=_PHENO_PARENT,
        xrefs=["GO:0042710"],
        priority="MEDIUM",
    ),
    # Catalase/oxidase/urease tests — neutral assay-result parents (NOT
    # subclasses of "X activity") with positive/negative children. A "negative"
    # result is the absence of detectable activity, so subclassing it under an
    # activity parent would be polarity-inverted (catalase-negative organisms
    # would roll up as "has catalase activity"). The parent here is the test/
    # assay itself; its children are the observed test outcomes. Pattern
    # matches METPO's existing biochemical-test classes (e.g.
    # METPO:1005010-1005018 for indole/MR/VP).
    Term(
        proposed_id="METPO:1007080",
        scope="categorical",
        term_type="Class",
        label="catalase test",
        definition=(
            "A biochemical test that detects catalase enzyme activity by exposing "
            "cells to hydrogen peroxide and observing for visible bubbling. The "
            "test outcome (positive or negative) is captured by its child classes; "
            "this class itself does not assert that the organism has catalase activity."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["catalase activity test", "catalase assay"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007083",
        scope="categorical",
        term_type="Class",
        label="catalase positive",
        definition=(
            "Phenotype where the catalase test yields a positive result (visible "
            "bubbling on H2O2), indicating that the organism has detectable "
            "catalase activity (GO:0004096)."
        ),
        parent_or_subproperty="METPO:1007080",
        xrefs=["GO:0004096"],
        synonyms=["catalase test positive", "catalase +"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007084",
        scope="categorical",
        term_type="Class",
        label="catalase negative",
        definition=(
            "Phenotype where the catalase test yields a negative result (no "
            "bubbling on H2O2), indicating absence of detectable catalase activity."
        ),
        parent_or_subproperty="METPO:1007080",
        synonyms=["catalase test negative", "catalase -"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007081",
        scope="categorical",
        term_type="Class",
        label="oxidase test",
        definition=(
            "A biochemical test that detects cytochrome c oxidase activity using a "
            "redox indicator. The test outcome (positive or negative) is captured "
            "by its child classes; this class itself does not assert oxidase activity."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["oxidase activity test", "cytochrome oxidase test"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007085",
        scope="categorical",
        term_type="Class",
        label="oxidase positive",
        definition=(
            "Phenotype where the oxidase test yields a positive result, indicating "
            "detectable cytochrome c oxidase activity (GO:0004129)."
        ),
        parent_or_subproperty="METPO:1007081",
        xrefs=["GO:0004129"],
        synonyms=["oxidase test positive", "oxidase +"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007086",
        scope="categorical",
        term_type="Class",
        label="oxidase negative",
        definition=(
            "Phenotype where the oxidase test yields a negative result, indicating "
            "absence of detectable cytochrome c oxidase activity."
        ),
        parent_or_subproperty="METPO:1007081",
        synonyms=["oxidase test negative", "oxidase -"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007082",
        scope="categorical",
        term_type="Class",
        label="urease test",
        definition=(
            "A biochemical test that detects urease enzyme activity by observing "
            "urea hydrolysis (typically via a pH-indicator color change). The test "
            "outcome (positive or negative) is captured by its child classes; this "
            "class itself does not assert urease activity."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["urease activity test", "urea hydrolysis test"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007087",
        scope="categorical",
        term_type="Class",
        label="urease positive",
        definition=(
            "Phenotype where the urease test yields a positive result, indicating "
            "detectable urease activity (GO:0009039)."
        ),
        parent_or_subproperty="METPO:1007082",
        xrefs=["GO:0009039"],
        synonyms=["urease test positive", "urease +"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007088",
        scope="categorical",
        term_type="Class",
        label="urease negative",
        definition=(
            "Phenotype where the urease test yields a negative result, indicating "
            "absence of detectable urease activity."
        ),
        parent_or_subproperty="METPO:1007082",
        synonyms=["urease test negative", "urease -"],
        priority="MEDIUM",
    ),
    # Coagulase activity — migrates kgmicrobe.activity:coagulase_activity placeholder
    # currently emitted by metatraits transform (36,343 edges in
    # data/transformed/metatraits/edges.tsv). No EC/GO term exists for the
    # bacteriological coagulase test at the appropriate granularity.
    Term(
        proposed_id="METPO:1007089",
        scope="categorical",
        term_type="Class",
        label="coagulase activity",
        definition=(
            "A phenotypic quality describing coagulase enzyme activity (clotting of "
            "blood plasma). Diagnostic marker, e.g. for Staphylococcus aureus."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["coagulase test"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007090",
        scope="categorical",
        term_type="Class",
        label="coagulase positive",
        definition="Phenotype where the coagulase test yields a positive result (plasma clotting).",
        parent_or_subproperty="METPO:1007089",
        synonyms=["coagulase test positive", "coagulase +"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007091",
        scope="categorical",
        term_type="Class",
        label="coagulase negative",
        definition="Phenotype where the coagulase test yields a negative result.",
        parent_or_subproperty="METPO:1007089",
        synonyms=["coagulase test negative", "coagulase -"],
        priority="MEDIUM",
    ),
    # Xerophilic and epibiont phenotypes — surfaced from the bacdive
    # isolation_source mapping audit (mappings/isolation_source_to_ontology.tsv,
    # 2026-05-02) as residual unmapped microbial-trait labels with no
    # existing ENVO/UBERON/PATO/MICRO term that fits.
    Term(
        proposed_id="METPO:1007092",
        scope="categorical",
        term_type="Class",
        label="xerophilic phenotype",
        definition=(
            "A phenotypic quality describing a microbe that thrives in low water-activity "
            "environments (typically aw < 0.85). Sibling concept of osmotic and metal "
            "tolerance; distinct from halophily because the limiting factor is water "
            "activity rather than salt concentration."
        ),
        parent_or_subproperty="METPO:1007073",
        synonyms=["xerophile", "xerotolerant"],
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007093",
        scope="categorical",
        term_type="Class",
        label="epibiont phenotype",
        definition=(
            "A phenotypic quality describing a microbe that lives on the external surface "
            "of a host organism or substrate, as distinct from endosymbionts (which live "
            "inside the host). Captures host-association mode, not specific host taxonomy."
        ),
        parent_or_subproperty=_PHENO_PARENT,
        synonyms=["epibiont", "ectosymbiont"],
        priority="LOW",
    ),
]


# Phase 5: infrastructure only — recorded for provenance; no rows emitted.
PHASE_5_NOTE = (
    "Phase 5 covers ChEBI lookup infrastructure improvements in KG-Microbe code; "
    "it introduces no new METPO terms. Addressed in docs/METPO_NEW_TERMS_PROPOSAL.md."
)


# --------------------------------------------------------------------------- #
# Validation against the local METPO snapshot
# --------------------------------------------------------------------------- #


_NORM_RE = re.compile(r"[\s_\-]+")


def _norm(s: str) -> str:
    """Normalize a label/synonym for collision detection."""
    return _NORM_RE.sub(" ", (s or "").strip().lower()).strip()


def _load_metpo_index(snapshot: Path) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, Tuple[str, str]]]:
    """Return (label_index, synonym_index): normalized text -> (id, original_text)."""
    if not snapshot.exists():
        raise FileNotFoundError(
            f"METPO snapshot not found at {snapshot}. Run "
            "`poetry run kg transform -s ontologies` first, or download metpo.json."
        )
    label_index: Dict[str, Tuple[str, str]] = {}
    synonym_index: Dict[str, Tuple[str, str]] = {}
    with open(snapshot, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            mid = row.get("id", "")
            if not mid.startswith("METPO:"):
                continue
            name = (row.get("name") or "").strip()
            if name:
                label_index.setdefault(_norm(name), (mid, name))
            for syn in (row.get("synonym") or "").split("|"):
                syn = syn.strip()
                if syn:
                    synonym_index.setdefault(_norm(syn), (mid, syn))
    return label_index, synonym_index


def _alias_proposed_keys() -> Set[str]:
    """Return normalized labels + synonyms explicitly declared as duplicates."""
    keys: Set[str] = set()
    for alias in EXISTING_METPO_ALIASES:
        keys.add(_norm(alias.proposed_label))
        for syn in alias.proposed_synonyms:
            keys.add(_norm(syn))
    return keys


def validate_against_metpo(
    terms: Iterable[Term],
    snapshot: Path = METPO_SNAPSHOT,
) -> None:
    """
    Fail if any kept Term collides with an existing METPO label or synonym.

    A collision is allowed only when the colliding label/synonym is also
    declared in EXISTING_METPO_ALIASES (i.e. we have explicitly accepted that
    this concept is being modeled by an existing METPO ID).
    """
    label_index, synonym_index = _load_metpo_index(snapshot)
    alias_keys = _alias_proposed_keys()

    collisions: List[str] = []
    for term in terms:
        candidates = [(term.label, "label")] + [(s, "synonym") for s in term.synonyms]
        for text, source in candidates:
            key = _norm(text)
            if not key:
                continue
            if key in alias_keys:
                continue
            hit = label_index.get(key)
            if hit:
                collisions.append(
                    f"{term.proposed_id} ({source}={text!r}) collides with "
                    f"{hit[0]} {hit[1]!r} (existing label)"
                )
                continue
            hit = synonym_index.get(key)
            if hit:
                collisions.append(
                    f"{term.proposed_id} ({source}={text!r}) collides with "
                    f"{hit[0]} {hit[1]!r} (existing synonym)"
                )

    if collisions:
        msg = (
            "Refusing to emit METPO proposals: the following terms already exist in "
            f"{snapshot} and are not declared in EXISTING_METPO_ALIASES.\n"
            "Either (a) drop the duplicate Term entry and add an Alias, or "
            "(b) reword the proposal so it no longer collides.\n\n"
            + "\n".join(f"  - {c}" for c in collisions)
        )
        raise SystemExit(msg)


def compute_bacdive_observations(snapshot: Path = BACDIVE_SNAPSHOT) -> Dict[str, int]:
    """
    Tally per-child observation counts from BacDive raw JSON.

    Returns a dict keyed by child label (matching BACDIVE_BASELINE_COUNTS) with
    integer counts. Walks `data/raw/bacdive_strains.json` once, applying the
    rules in `_BACDIVE_RULES` to each strain's Morphology fields.
    """
    import json

    with open(snapshot) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit(f"Unexpected BacDive structure in {snapshot}: {type(data).__name__}")

    counts: Dict[str, int] = {label: 0 for label in _BACDIVE_RULES}
    for strain in data:
        for label, (path, tokens, kind) in _BACDIVE_RULES.items():
            morph = strain.get(path[0]) or {}
            sub = morph.get(path[1]) if isinstance(morph, dict) else None
            if sub is None:
                continue
            entries = sub if isinstance(sub, list) else [sub]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                raw = entry.get(path[2])
                if not isinstance(raw, str):
                    continue
                value = raw.strip().lower()
                if not value:
                    continue
                if kind == "exact":
                    if value in tokens:
                        counts[label] += 1
                elif kind == "token":
                    parts = [p.strip() for p in value.split(",")]
                    if any(t in parts for t in tokens):
                        counts[label] += 1
    return counts


def validate_bacdive_observation_counts(snapshot: Path = BACDIVE_SNAPSHOT) -> None:
    """
    Compare BacDive-derived counts to the hardcoded baseline.

    Skipped (warning only) if `data/raw/bacdive_strains.json` is absent so the
    extractor remains runnable without raw data. When the file is present, any
    divergence from `BACDIVE_BASELINE_COUNTS` raises SystemExit so a stale or
    drifted proposal cannot be regenerated silently.
    """
    if not snapshot.exists():
        print(f"[skip] {snapshot} not present — observation counts not validated")
        return
    actual = compute_bacdive_observations(snapshot)
    mismatches = [
        f"  - {label}: baseline={BACDIVE_BASELINE_COUNTS[label]} actual={actual[label]}"
        for label in BACDIVE_BASELINE_COUNTS
        if actual.get(label) != BACDIVE_BASELINE_COUNTS[label]
    ]
    if mismatches:
        msg = (
            "BacDive observation counts have drifted from the proposal baseline. "
            "Either update BACDIVE_BASELINE_COUNTS and the matching Term.observations "
            "fields, or revert the source data.\n\n" + "\n".join(mismatches)
        )
        raise SystemExit(msg)
    print(f"[ok] BacDive observation counts match baseline ({len(actual)} children)")


def validate_metatraits_placeholder_coverage(
    edges_path: Path = METATRAITS_EDGES_PATH,
    terms: List[Term] = None,
) -> None:
    """
    Assert every kgmicrobe.{trait,activity}:* placeholder is migrated.

    Scans `data/transformed/metatraits/edges.tsv` for objects with prefix
    `kgmicrobe.trait:` or `kgmicrobe.activity:` (the metatraits transform's
    placeholder CURIEs for unmapped traits) and exits non-zero if any are
    missing from `KGMICROBE_PLACEHOLDER_MIGRATION`. Also verifies that every
    target METPO ID in the migration map exists as a Term in the proposal.

    Skipped (warning only) when `data/transformed/metatraits/edges.tsv` is
    absent so the extractor remains runnable on machines that have not yet
    run the metatraits transform.
    """
    proposed_ids = {t.proposed_id for t in (terms or [])}
    missing_terms = sorted(
        target
        for target in KGMICROBE_PLACEHOLDER_MIGRATION.values()
        if target not in proposed_ids
    )
    if missing_terms:
        raise SystemExit(
            "KGMICROBE_PLACEHOLDER_MIGRATION targets missing from proposal: "
            + ", ".join(missing_terms)
        )

    if not edges_path.exists():
        print(f"[skip] {edges_path} not present — placeholder coverage not validated")
        return

    placeholders: Set[str] = set()
    with edges_path.open() as f:
        f.readline()
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 3:
                continue
            obj = cols[2]
            if obj.startswith(("kgmicrobe.trait:", "kgmicrobe.activity:")):
                placeholders.add(obj)

    uncovered = sorted(p for p in placeholders if p not in KGMICROBE_PLACEHOLDER_MIGRATION)
    if uncovered:
        lines = "\n".join(f"  - {p}" for p in uncovered)
        raise SystemExit(
            "Uncovered kgmicrobe.{trait,activity}:* placeholders in metatraits edges:\n"
            + lines
            + "\n\nAdd each to KGMICROBE_PLACEHOLDER_MIGRATION and add a Term to "
            + "PHASE_4_TERMS in scripts/extract_metpo_proposals.py."
        )
    print(
        f"[ok] {len(placeholders)} kgmicrobe.{{trait,activity}}:* placeholder(s) "
        f"in metatraits edges — all covered by proposal."
    )


def write_tsv(path: Path, terms: List[Term]) -> None:
    """Write terms to TSV with standard HEADER."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)
        for term in terms:
            writer.writerow(term.as_row())


def write_metatraits_alias_overrides(path: Path, aliases: List[Alias]) -> int:
    """
    Emit a Tier-2 override TSV that load_microbial_trait_mappings() will ingest.

    For each alias, emit rows keyed by `proposed_label` and each `proposed_synonym`,
    pointing at the existing METPO ID. This guards against cases where source-data
    labels do not appear in METPO's `metatraits synonym` column and would otherwise
    fall through to "unmapped".
    """
    rows: List[List[str]] = []
    today = "2026-04-25"
    seen_subjects: Set[str] = set()
    for alias in aliases:
        candidates = [alias.proposed_label] + list(alias.proposed_synonyms)
        for subject in candidates:
            subject = subject.strip()
            if not subject:
                continue
            key = subject.lower()
            if key in seen_subjects:
                continue
            seen_subjects.add(key)
            rows.append([
                subject,
                key,
                alias.existing_metpo_id,
                alias.existing_metpo_label,
                "METPO",
                "skos:closeMatch" if alias.match_kind == "concept" else "skos:exactMatch",
                "high",
                "semapv:ManualMappingCuration",
                "extract_metpo_proposals",
                "metpo_proposal_audit",
                f"biolink:has_phenotype; {alias.notes}",
                today,
            ])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(TRAIT_MAPPINGS_HEADER)
        writer.writerows(rows)
    return len(rows)


SUBSET_TAG = "metpo_proposal_2026_04"


def write_robot_template_classes(path: Path, terms: List[Term]) -> int:
    """
    Emit a ROBOT template TSV for OWL class declarations.

    Two header rows: human-readable column names then ROBOT directives.
    Filters terms to Class declarations only.
    """
    header = [
        "proposed_id", "label", "definition", "definition_source",
        "parent", "synonyms", "xrefs", "subset",
        "priority", "observations", "traits_addressed",
    ]
    directives = [
        "ID", "LABEL", "A IAO:0000115", ">A IAO:0000119",
        "SC %", "A oboInOwl:hasExactSynonym SPLIT=|",
        "A oboInOwl:hasDbXref SPLIT=|", "A oboInOwl:inSubset",
        "", "", "",
    ]
    classes = [t for t in terms if t.term_type == "Class"]
    with open(path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerow(directives)
        for t in classes:
            writer.writerow([
                t.proposed_id, t.label, t.definition, "TODO:add_citation",
                t.parent_or_subproperty, "|".join(t.synonyms),
                "|".join(t.xrefs), SUBSET_TAG,
                t.priority, t.observations, t.traits_addressed,
            ])
    return len(classes)


def write_robot_template_properties(path: Path, terms: List[Term]) -> int:
    """Emit a ROBOT template TSV for property declarations."""
    header = [
        "proposed_id", "label", "definition", "definition_source",
        "type", "domain", "range", "xrefs", "subset",
        "priority", "traits_addressed", "observations",
    ]
    directives = [
        "ID", "LABEL", "A IAO:0000115", ">A IAO:0000119",
        "TYPE", "DOMAIN", "RANGE",
        "A oboInOwl:hasDbXref SPLIT=|", "A oboInOwl:inSubset",
        "", "", "",
    ]
    props = [t for t in terms if t.term_type in ("DatatypeProperty", "ObjectProperty", "AnnotationProperty")]
    with open(path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerow(directives)
        for t in props:
            owl_type = f"owl:{t.term_type}"
            writer.writerow([
                t.proposed_id, t.label, t.definition, "TODO:add_citation",
                owl_type, t.domain, t.range,
                "|".join(t.xrefs), SUBSET_TAG,
                t.priority, t.traits_addressed, t.observations,
            ])
    return len(props)


def validate_with_robot(classes_path: Path, properties_path: Path) -> None:
    """
    Compile both ROBOT templates, merge, and run ELK reasoner.

    Best-effort: prints a skip notice and returns 0 if `robot` is not on PATH.
    Raises on validation failure (non-zero exit from any robot subcommand).
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("robot"):
        print("[skip] robot binary not on PATH — skipping ROBOT template + ELK validation")
        return

    prefixes = [
        "--prefix", "METPO: http://purl.obolibrary.org/obo/METPO_",
        "--prefix", "biolink: https://w3id.org/biolink/vocab/",
    ]
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        classes_owl = td_path / "classes.owl"
        props_owl = td_path / "props.owl"
        merged_owl = td_path / "merged.owl"
        reasoned_owl = td_path / "reasoned.owl"

        subprocess.run(
            ["robot", "template", "--template", str(classes_path),
             *prefixes, "--output", str(classes_owl)],
            check=True,
        )
        subprocess.run(
            ["robot", "template", "--template", str(properties_path),
             *prefixes, "--output", str(props_owl)],
            check=True,
        )
        subprocess.run(
            ["robot", "merge", "--input", str(classes_owl),
             "--input", str(props_owl), "--output", str(merged_owl)],
            check=True,
        )
        subprocess.run(
            ["robot", "reason", "--reasoner", "ELK",
             "--input", str(merged_owl),
             "--axiom-generators", "SubClass EquivalentClass",
             "--output", str(reasoned_owl)],
            check=True,
        )
        print("[ok] ROBOT template + ELK reason passed (no UNSAT classes)")


def write_alias_tsv(path: Path, aliases: List[Alias]) -> None:
    """Write the proposed-concept -> existing-METPO-ID alias map."""
    # Build a one-shot METPO row index so we can pull synonyms per existing_id.
    metpo_rows: Dict[str, Dict[str, str]] = {}
    with open(METPO_SNAPSHOT, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            if row.get("id", "").startswith("METPO:"):
                metpo_rows[row["id"]] = row

    with open(path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(ALIAS_HEADER)
        for alias in aliases:
            row = metpo_rows.get(alias.existing_metpo_id, {})
            existing_syns = [
                s.strip()
                for s in (row.get("synonym") or "").split("|")
                if s.strip()
            ]
            writer.writerow([
                alias.proposed_label,
                "|".join(alias.proposed_synonyms),
                alias.existing_metpo_id,
                alias.existing_metpo_label,
                "|".join(existing_syns),
                alias.match_kind,
                alias.notes,
            ])


# --------------------------------------------------------------------------- #
# Cleanup of obsolete proposal TSVs (replaced by the quantitative/categorical pair)
# --------------------------------------------------------------------------- #
OBSOLETE_OUTPUTS = [
    "metpo_predicate_based_proposal.tsv",
    "metpo_phases_1_and_4_terms.tsv",
    "metpo_unified_all_phases.tsv",
]


def remove_obsolete_outputs(output_dir: Path) -> None:
    """Delete TSVs replaced by the quantitative/categorical split."""
    for name in OBSOLETE_OUTPUTS:
        p = output_dir / name
        if p.exists():
            p.unlink()
            print(f"[rm] {p}")


def main(
    output_dir: Path = Path("mappings"),
    metatraits_dir: Path = METATRAITS_MAPPINGS_DIR,
) -> None:
    """Generate the METPO proposal TSVs after collision check."""
    output_dir.mkdir(parents=True, exist_ok=True)
    metatraits_dir.mkdir(parents=True, exist_ok=True)

    all_terms = QUANTITATIVE_TERMS + CATEGORICAL_TERMS
    validate_against_metpo(all_terms)
    print(f"[ok] collision check passed for {len(all_terms)} proposed terms")

    validate_bacdive_observation_counts()

    validate_metatraits_placeholder_coverage(terms=CATEGORICAL_TERMS)

    remove_obsolete_outputs(output_dir)

    write_tsv(output_dir / "metpo_proposal_quantitative.tsv", QUANTITATIVE_TERMS)
    print(
        f"[ok] metpo_proposal_quantitative.tsv      ({len(QUANTITATIVE_TERMS)} terms: "
        f"datatype properties + numeric tolerance class forms)"
    )

    write_tsv(output_dir / "metpo_proposal_categorical.tsv", CATEGORICAL_TERMS)
    n_parents = sum(1 for t in CATEGORICAL_TERMS if t.parent_or_subproperty == _PHENO_PARENT)
    n_children = len(CATEGORICAL_TERMS) - n_parents
    print(
        f"[ok] metpo_proposal_categorical.tsv       ({len(CATEGORICAL_TERMS)} terms: "
        f"{n_parents} top-level + {n_children} children)"
    )

    write_alias_tsv(output_dir / "metpo_existing_aliases.tsv", EXISTING_METPO_ALIASES)
    print(
        f"[ok] metpo_existing_aliases.tsv           ({len(EXISTING_METPO_ALIASES)} concepts "
        f"already in METPO; downstream transforms must reuse the existing IDs)"
    )

    n_rows = write_metatraits_alias_overrides(
        metatraits_dir / "metpo_alias_mappings.tsv",
        EXISTING_METPO_ALIASES,
    )
    print(
        f"[ok] metpo_alias_mappings.tsv             ({n_rows} subject_label rows wired "
        f"into metatraits Tier-2 lookup)"
    )

    classes_robot_path = output_dir / "metpo_proposal_classes_robot.tsv"
    props_robot_path = output_dir / "metpo_proposal_properties_robot.tsv"
    n_classes = write_robot_template_classes(classes_robot_path, all_terms)
    n_props = write_robot_template_properties(props_robot_path, all_terms)
    print(f"[ok] metpo_proposal_classes_robot.tsv     ({n_classes} OWL class rows, ROBOT template)")
    print(f"[ok] metpo_proposal_properties_robot.tsv  ({n_props} OWL property rows, ROBOT template)")

    validate_with_robot(classes_robot_path, props_robot_path)

    print()
    print(PHASE_5_NOTE)


if __name__ == "__main__":
    sys.exit(main())
