"""
Preserve finite reviewed non-process group labels without inventing process identity.

These are representation dispositions, NOT ontology mappings. FAPROTAX documents
taxon groups, host associations and pathogen groups as well as metabolic functions;
the ``Type_of_metabolism`` column does not make every value a biological process.
Source membership remains a prediction and never becomes a direct infection,
habitat, or universal phenotype claim. See docs/microbedecoder_process_curation.md.
"""

# Exact column/literal pairs only. Never classify a new label by a substring,
# regular expression, capitalization change, or its taxonomic-looking spelling.
REPORTED_METABOLISM_ANNOTATIONS = frozenset(
    {("Bergey_Type_of_metabolism", "Other")}
    | {
        ("FAPROTAX_Type_of_metabolism", label)
        for label in (
            "photosynthetic_cyanobacteria",
            "animal_parasites_or_symbionts",
            "human_associated",
            "human_pathogens_all",
            "intracellular_parasites",
            "mammal_gut",
            "human_gut",
            "invertebrate_parasites",
            "human_pathogens_meningitis",
            "human_pathogens_septicemia",
            "human_pathogens_gastroenteritis",
            "predatory_or_exoparasitic",
            "human_pathogens_pneumonia",
            "human_pathogens_diarrhea",
            "human_pathogens_nosocomia",
            "fish_parasites",
            # Qualified trophic types and source application groups are not
            # exact process identities. Keep their full source-scoped literal;
            # these finite dispositions do not imply a native attribute type.
            "aerobic_anoxygenic_phototrophy",
            "aerobic_chemoheterotrophy",
            "anoxygenic_photoautotrophy",
            "anoxygenic_photoautotrophy_Fe_oxidizing",
            "anoxygenic_photoautotrophy_H2_oxidizing",
            "anoxygenic_photoautotrophy_S_oxidizing",
            "oxygenic_photoautotrophy",
            "phototrophy",
            "methylotrophy",
            "oil_bioremediation",
        )
    }
)


def is_reported_metabolism_annotation(source_column: str, literal: str) -> bool:
    """Identify reviewed metadata/group membership while retaining its exact source scope."""
    return (source_column, literal) in REPORTED_METABOLISM_ANNOTATIONS
