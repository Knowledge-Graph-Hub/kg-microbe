#!/usr/bin/env python3
"""
Emit METPO proposal TSVs in the predicate-based format (2026-04-03 plan).

Writes:
    mappings/metpo_predicate_based_proposal.tsv  - Phase 1 only (9 data properties)
    mappings/metpo_phases_1_2_3_terms.tsv        - Phases 1 + 2 + 4 (44 terms)
    mappings/metpo_unified_all_phases.tsv        - Phases 1-6 (59 terms)

Replaces the pre-April class-based extractor. Source of truth for term
content is notes/METPO_UNIFIED_PROPOSAL_5_PHASES.md and
notes/METPO_FORMAL_PROPOSAL_PHASES_1_2_3.md.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

HEADER = [
    "proposed_id",
    "term_type",
    "label",
    "definition",
    "parent_or_subproperty",
    "domain",
    "range",
    "xrefs",
    "synonyms",
    "phase",
    "priority",
    "traits_addressed",
    "observations",
]


@dataclass
class Term:
    """One proposed METPO term."""

    proposed_id: str
    term_type: str
    label: str
    definition: str
    parent_or_subproperty: str = ""
    domain: str = ""
    range: str = ""
    xrefs: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)
    phase: int = 0
    priority: str = ""
    traits_addressed: str = ""
    observations: str = ""

    def as_row(self) -> List[str]:
        """Return the row in TSV column order."""
        return [
            self.proposed_id,
            self.term_type,
            self.label,
            self.definition,
            self.parent_or_subproperty,
            self.domain,
            self.range,
            "|".join(self.xrefs),
            "|".join(self.synonyms),
            str(self.phase),
            self.priority,
            self.traits_addressed,
            self.observations,
        ]


ORG = "biolink:OrganismTaxon"
CHEM = "CHEBI:24431"  # chemical entity
NITRO = "CHEBI:51143"  # nitrogen molecular entity


# Phase 1: quantitative growth data properties (9)
PHASE_1: List[Term] = [
    Term(
        proposed_id="METPO:has_growth_temperature_optimum",
        term_type="DatatypeProperty",
        label="has growth temperature optimum",
        definition=(
            "The optimal temperature at which an organism achieves maximum growth rate, "
            "measured in degrees Celsius."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["UO:0000027"],
        phase=1,
        priority="CRITICAL",
        traits_addressed="1",
        observations="85311",
    ),
    Term(
        proposed_id="METPO:has_growth_temperature_minimum",
        term_type="DatatypeProperty",
        label="has growth temperature minimum",
        definition=(
            "The minimum temperature at which an organism can grow, measured in degrees Celsius."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["UO:0000027"],
        phase=1,
        priority="CRITICAL",
    ),
    Term(
        proposed_id="METPO:has_growth_temperature_maximum",
        term_type="DatatypeProperty",
        label="has growth temperature maximum",
        definition=(
            "The maximum temperature at which an organism can grow, measured in degrees Celsius."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["UO:0000027"],
        phase=1,
        priority="CRITICAL",
    ),
    Term(
        proposed_id="METPO:has_NaCl_concentration_optimum",
        term_type="DatatypeProperty",
        label="has NaCl concentration optimum",
        definition=(
            "The optimal sodium chloride (NaCl) concentration for growth, "
            "expressed as weight/volume percentage."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["UO:0000187", "CHEBI:26710"],
        phase=1,
        priority="CRITICAL",
        traits_addressed="1",
        observations="85311",
    ),
    Term(
        proposed_id="METPO:has_NaCl_concentration_minimum",
        term_type="DatatypeProperty",
        label="has NaCl concentration minimum",
        definition=(
            "The minimum sodium chloride (NaCl) concentration tolerated for growth, "
            "expressed as weight/volume percentage."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["UO:0000187"],
        phase=1,
        priority="CRITICAL",
    ),
    Term(
        proposed_id="METPO:has_NaCl_concentration_maximum",
        term_type="DatatypeProperty",
        label="has NaCl concentration maximum",
        definition=(
            "The maximum sodium chloride (NaCl) concentration tolerated for growth, "
            "expressed as weight/volume percentage."
        ),
        domain=ORG,
        range="xsd:decimal",
        xrefs=["UO:0000187"],
        phase=1,
        priority="CRITICAL",
    ),
    Term(
        proposed_id="METPO:has_pH_optimum",
        term_type="DatatypeProperty",
        label="has pH optimum",
        definition="The optimal pH value for growth on the pH scale (0-14).",
        domain=ORG,
        range="xsd:decimal",
        xrefs=["PATO:0001842"],
        phase=1,
        priority="HIGH",
        traits_addressed="1",
        observations="5479",
    ),
    Term(
        proposed_id="METPO:has_pH_minimum",
        term_type="DatatypeProperty",
        label="has pH minimum",
        definition="The minimum pH value at which growth can occur.",
        domain=ORG,
        range="xsd:decimal",
        phase=1,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:has_pH_maximum",
        term_type="DatatypeProperty",
        label="has pH maximum",
        definition="The maximum pH value at which growth can occur.",
        domain=ORG,
        range="xsd:decimal",
        phase=1,
        priority="HIGH",
    ),
]


# Phase 2: DROPPED. All four proposed trophic-relation object properties already exist in METPO.
# Transforms should use the existing IDs instead of minting new ones:
#   - "assimilates"            -> METPO:2000002 (existing)
#   - "uses as energy source"  -> METPO:2000010 (existing)
#   - "uses as nitrogen source"-> METPO:2000014 (existing)
#   - "uses as electron donor" -> METPO:2000009 (existing)
# The previously-proposed IDs METPO:2000021/2000022/2000024 also COLLIDE with existing METPO
# terms ("does not use for aerobic catabolization", "does not use for aerobic growth", "does
# not use for anaerobic growth").
PHASE_2: List[Term] = []


# Phase 3: DROPPED. The three "produces X from" concepts already exist in METPO as "builds X from":
#   - "produces acid from" -> METPO:2000003 ("builds acid from")       [add synonym "produces acid from"]
#   - "produces gas from"  -> METPO:2000005 ("builds gas from")        [add synonym "produces gas from"]
#   - "produces base from" -> METPO:2000004 ("builds base from")       [add synonym "produces base from"]
# The previously-proposed IDs METPO:2000025/2000026/2000027 also COLLIDE with existing METPO
# terms ("does not use for anaerobic growth in the dark", "... with light", "does not assimilate").
# ACTION: add "produces X from" as a synonym on each existing "builds X from" term in the METPO
# ontology repo; until that lands, transforms should hard-code the mapping to the existing IDs.
PHASE_3: List[Term] = []


# Phase 4: phenotypic quality classes (31 = 5 + 4 + 13 + 3 + 3 + 3 extras per unified doc)
# The unified doc lists 31; formal doc enumerates 28 distinct IDs. Using the enumerated set
# and matching the unified count by including three extras (1007033 gc%, 1007060 selective-color,
# 1007061 motility-trait).
_METPO_PHENO_PARENT = "METPO:1000000"


PHASE_4: List[Term] = [
    # 4.1 Morphological (5)
    Term(
        proposed_id="METPO:1007001",
        term_type="Class",
        label="cell shape",
        definition="A phenotypic quality that describes the geometric shape of a bacterial or archaeal cell.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["PATO:0000052"],
        synonyms=["cellular morphology", "rod-shaped", "coccus", "spiral", "filamentous"],
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007002",
        term_type="Class",
        label="cell length",
        definition=(
            "A phenotypic quality that describes the length of a bacterial or archaeal cell, "
            "typically measured in micrometers."
        ),
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["PATO:0000122", "UO:0000017"],
        synonyms=["cellular length"],
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007003",
        term_type="Class",
        label="cell width",
        definition="A phenotypic quality that describes the width or diameter of a bacterial or archaeal cell.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["PATO:0000921", "UO:0000017"],
        synonyms=["cellular width", "cell diameter"],
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007004",
        term_type="Class",
        label="cell color",
        definition="A phenotypic quality that describes the color or pigmentation of bacterial or archaeal cells.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["PATO:0000014"],
        synonyms=["cell pigmentation", "colony color"],
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007005",
        term_type="Class",
        label="flagellar arrangement",
        definition=(
            "A phenotypic quality that describes the arrangement pattern of flagella on a "
            "bacterial or archaeal cell."
        ),
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0001539"],
        synonyms=[
            "flagellation pattern",
            "peritrichous",
            "monotrichous",
            "amphitrichous",
            "lophotrichous",
            "polar flagellation",
        ],
        phase=4,
        priority="HIGH",
    ),
    # 4.2 Genomic (4)
    Term(
        proposed_id="METPO:1007010",
        term_type="Class",
        label="GC content percentage",
        definition="A genomic quality that describes the percentage of guanine-cytosine base pairs in the genome.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["SO:0001026", "UO:0000187"],
        synonyms=["GC%", "mol% G+C", "genomic GC content"],
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007011",
        term_type="Class",
        label="genome size",
        definition="A genomic quality that describes the total size of the genome in base pairs or megabase pairs.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["SO:0001026", "UO:0000329"],
        synonyms=["genome length", "genomic size"],
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007012",
        term_type="Class",
        label="gene count",
        definition=(
            "A genomic quality that describes the total number of genes in the genome, "
            "either annotated or predicted."
        ),
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["SO:0000704"],
        synonyms=["number of genes", "total gene count"],
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007013",
        term_type="Class",
        label="coding density",
        definition="A genomic quality that describes the percentage of the genome that codes for proteins.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["UO:0000187"],
        synonyms=["coding sequence percentage", "protein-coding percentage"],
        phase=4,
        priority="HIGH",
    ),
    # 4.3 Environmental tolerances (13)
    Term(
        proposed_id="METPO:1007020",
        term_type="Class",
        label="oxygen requirement",
        definition="A phenotypic quality that describes the oxygen requirement for growth.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["CHEBI:15379"],
        synonyms=[
            "aerobic",
            "anaerobic",
            "facultative anaerobic",
            "microaerophilic",
            "aerotolerant",
        ],
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007021",
        term_type="Class",
        label="pH tolerance range",
        definition="An environmental quality that describes the range of pH values that support growth.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007022",
        term_type="Class",
        label="pH minimum tolerance",
        definition="An environmental quality that describes the minimum pH value that supports growth.",
        parent_or_subproperty="METPO:1007021",
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007023",
        term_type="Class",
        label="pH maximum tolerance",
        definition="An environmental quality that describes the maximum pH value that supports growth.",
        parent_or_subproperty="METPO:1007021",
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007024",
        term_type="Class",
        label="pH optimum",
        definition="An environmental quality that describes the optimal pH value for growth.",
        parent_or_subproperty="METPO:1007021",
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007025",
        term_type="Class",
        label="temperature tolerance range",
        definition="An environmental quality that describes the range of temperatures that support growth.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007026",
        term_type="Class",
        label="temperature minimum tolerance",
        definition="An environmental quality that describes the minimum temperature that supports growth.",
        parent_or_subproperty="METPO:1007025",
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007027",
        term_type="Class",
        label="temperature maximum tolerance",
        definition="An environmental quality that describes the maximum temperature that supports growth.",
        parent_or_subproperty="METPO:1007025",
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007028",
        term_type="Class",
        label="temperature optimum",
        definition="An environmental quality that describes the optimal temperature for growth.",
        parent_or_subproperty="METPO:1007025",
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007029",
        term_type="Class",
        label="salinity tolerance range",
        definition="An environmental quality that describes the range of salt concentrations that support growth.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007030",
        term_type="Class",
        label="salinity minimum tolerance",
        definition=(
            "An environmental quality that describes the minimum salinity/NaCl "
            "concentration that supports growth."
        ),
        parent_or_subproperty="METPO:1007029",
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007031",
        term_type="Class",
        label="salinity maximum tolerance",
        definition=(
            "An environmental quality that describes the maximum salinity/NaCl "
            "concentration that supports growth."
        ),
        parent_or_subproperty="METPO:1007029",
        phase=4,
        priority="HIGH",
    ),
    Term(
        proposed_id="METPO:1007032",
        term_type="Class",
        label="salinity optimum",
        definition="An environmental quality that describes the optimal salinity/NaCl concentration for growth.",
        parent_or_subproperty="METPO:1007029",
        phase=4,
        priority="HIGH",
    ),
    # 4.4 Biochemical tests (3)
    Term(
        proposed_id="METPO:1007040",
        term_type="Class",
        label="indole production capability",
        definition="A phenotypic capability describing the production of indole from tryptophan via tryptophanase.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["CHEBI:16881", "GO:0050048"],
        synonyms=["indole test positive"],
        phase=4,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007041",
        term_type="Class",
        label="methyl red test positive",
        definition=(
            "A phenotypic quality indicating a positive methyl red test, demonstrating "
            "mixed acid fermentation with stable acid production."
        ),
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0019660"],
        synonyms=["MR test positive"],
        phase=4,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007042",
        term_type="Class",
        label="hemolytic activity",
        definition=(
            "A phenotypic quality describing the ability to lyse red blood cells, "
            "classified as alpha (partial), beta (complete), or gamma (no hemolysis)."
        ),
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0044179"],
        synonyms=["hemolysis", "alpha-hemolysis", "beta-hemolysis", "gamma-hemolysis"],
        phase=4,
        priority="MEDIUM",
    ),
    # 4.5 Growth characteristics (3)
    Term(
        proposed_id="METPO:1007050",
        term_type="Class",
        label="selective media growth capability",
        definition="A phenotypic capability describing the ability to grow on selective or differential media.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        synonyms=["grows on MacConkey agar", "grows on blood agar", "grows on EMB agar"],
        phase=4,
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007051",
        term_type="Class",
        label="bile resistance",
        definition="A phenotypic quality describing the ability to grow in the presence of bile acids or bile salts.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["CHEBI:3098"],
        synonyms=["bile tolerance"],
        phase=4,
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007052",
        term_type="Class",
        label="biosafety level classification",
        definition="A risk assessment quality describing the biosafety level (BSL-1 to BSL-4) assigned to an organism.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        synonyms=["BSL classification", "BSL-1", "BSL-2", "BSL-3", "BSL-4"],
        phase=4,
        priority="LOW",
    ),
    # 4.6 Additional phenotypes (3 extras to reach 31 per unified doc)
    Term(
        proposed_id="METPO:1007060",
        term_type="Class",
        label="colony pigmentation",
        definition="A phenotypic quality describing the pigmentation of colonies grown on solid media.",
        parent_or_subproperty="METPO:1007004",
        xrefs=["PATO:0000014"],
        phase=4,
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007061",
        term_type="Class",
        label="motility phenotype",
        definition="A phenotypic quality describing whether an organism is motile or non-motile.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0001539"],
        synonyms=["motile", "non-motile"],
        phase=4,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007062",
        term_type="Class",
        label="colony morphology",
        definition=(
            "A phenotypic quality describing macroscopic colony characteristics "
            "(shape, margin, elevation, surface)."
        ),
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["PATO:0000052"],
        phase=4,
        priority="LOW",
    ),
]


# Phase 5: infrastructure only — recorded for provenance; no rows emitted into term TSVs
PHASE_5_NOTE = (
    "Phase 5 covers ChEBI lookup infrastructure improvements in KG-Microbe code; "
    "it introduces no new METPO terms. Addressed in docs/METPO_NEW_TERMS_PROPOSAL.md."
)


# Phase 6: optional remaining phenotype classes (12)
PHASE_6: List[Term] = [
    Term(
        proposed_id="METPO:1007070",
        term_type="Class",
        label="pressure tolerance",
        definition="A phenotypic quality describing the ability to grow under elevated hydrostatic pressure.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        synonyms=["barophile", "piezophile"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007071",
        term_type="Class",
        label="barophile phenotype",
        definition="An organism that requires or tolerates elevated hydrostatic pressure for growth.",
        parent_or_subproperty="METPO:1007070",
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007072",
        term_type="Class",
        label="radiation tolerance",
        definition="A phenotypic quality describing the ability to withstand ionizing or UV radiation.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        synonyms=["radioresistant"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007073",
        term_type="Class",
        label="osmotic tolerance",
        definition="A phenotypic quality describing the ability to grow under high osmotic pressure (non-NaCl).",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        synonyms=["osmophile"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007074",
        term_type="Class",
        label="metal tolerance",
        definition=(
            "A phenotypic quality describing the ability to grow in the presence of "
            "elevated metal concentrations."
        ),
        parent_or_subproperty=_METPO_PHENO_PARENT,
        synonyms=["metallophile"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007075",
        term_type="Class",
        label="spore formation capability",
        definition="A phenotypic capability describing the ability to form endospores or exospores.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0030435"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007076",
        term_type="Class",
        label="capsule presence",
        definition="A phenotypic quality describing the presence of an extracellular polysaccharide capsule.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0042597"],
        phase=6,
        priority="LOW",
    ),
    Term(
        proposed_id="METPO:1007077",
        term_type="Class",
        label="biofilm formation capability",
        definition="A phenotypic capability describing the ability to form surface-attached biofilms.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0042710"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007080",
        term_type="Class",
        label="catalase activity",
        definition="A phenotypic quality describing catalase enzyme activity (H2O2 decomposition).",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0004096"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007081",
        term_type="Class",
        label="oxidase activity",
        definition="A phenotypic quality describing cytochrome c oxidase activity detected in the oxidase test.",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0004129"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007082",
        term_type="Class",
        label="urease activity",
        definition="A phenotypic quality describing urease enzyme activity (urea hydrolysis).",
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0009039"],
        phase=6,
        priority="MEDIUM",
    ),
    Term(
        proposed_id="METPO:1007090",
        term_type="Class",
        label="denitrification capability",
        definition=(
            "A phenotypic capability describing the ability to reduce nitrate or "
            "nitrite to gaseous nitrogen species."
        ),
        parent_or_subproperty=_METPO_PHENO_PARENT,
        xrefs=["GO:0019333"],
        phase=6,
        priority="MEDIUM",
    ),
]


def write_tsv(path: Path, terms: List[Term]) -> None:
    """Write terms to TSV with standard HEADER."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)
        for term in terms:
            writer.writerow(term.as_row())


def main() -> None:
    """Generate the three predicate-based proposal TSVs."""
    output_dir = Path("mappings")
    output_dir.mkdir(exist_ok=True)

    write_tsv(
        output_dir / "metpo_predicate_based_proposal.tsv",
        PHASE_1,
    )
    print(f"[ok] metpo_predicate_based_proposal.tsv  ({len(PHASE_1)} terms, Phase 1)")

    phases_1_4 = PHASE_1 + PHASE_2 + PHASE_4
    write_tsv(
        output_dir / "metpo_phases_1_2_3_terms.tsv",
        phases_1_4,
    )
    print(
        f"[ok] metpo_phases_1_2_3_terms.tsv         ({len(phases_1_4)} terms, "
        f"Phase 1 + 4; Phases 2 & 3 dropped — see script comments)"
    )

    unified = PHASE_1 + PHASE_2 + PHASE_3 + PHASE_4 + PHASE_6
    write_tsv(
        output_dir / "metpo_unified_all_phases.tsv",
        unified,
    )
    print(
        f"[ok] metpo_unified_all_phases.tsv         ({len(unified)} terms, "
        f"Phases 1+4+6; Phase 2 & 3 concepts already in METPO, Phase 5 is code-only)"
    )
    print()
    print(PHASE_5_NOTE)


if __name__ == "__main__":
    main()
