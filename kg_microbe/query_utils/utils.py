"""Utility functions for formatting and displaying query results."""

from typing import Dict


def format_organism_report(query_result: Dict) -> str:
    """
    Generate markdown report from organism query results.

    :param query_result: Dict from query_organism_full()
    :return: Markdown formatted report string
    """
    taxon_id = query_result["taxon_id"]
    name = query_result["name"]
    synonyms = query_result["synonyms"]
    traits = query_result["traits"]
    media = query_result["media"]
    composition = query_result["composition"]
    strains = query_result["strains"]
    sources = query_result["sources"]

    # Build report sections
    report = []

    # Header
    report.append(f"# Organism Report: {name} ({taxon_id})\n")

    # Overview section
    report.append("## Overview\n")
    if synonyms:
        report.append(f"**Synonyms**: {', '.join(synonyms)}\n")
    else:
        report.append("**Synonyms**: None\n")

    # Phenotypic Traits section
    if not traits.empty:
        # Filter for phenotype/trait predicates
        trait_predicates = traits[
            (traits["predicate"].str.contains("METPO:", na=False))
            | (traits["predicate"].str.contains("has_phenotype", na=False))
        ]

        if not trait_predicates.empty:
            report.append(f"\n## Phenotypic Traits ({len(trait_predicates)} traits)\n")
            report.append("| Trait | Value | Predicate | Source |\n")
            report.append("|-------|-------|-----------|--------|\n")

            for _, row in trait_predicates.iterrows():
                trait_name = row.get("object_name", row.get("object", ""))
                predicate = row.get("predicate", "")
                source = row.get("primary_knowledge_source", "")
                category = row.get("object_category", "")

                # Shorten long trait names
                if len(trait_name) > 50:
                    trait_name = trait_name[:47] + "..."

                report.append(f"| {category} | {trait_name} | {predicate} | {source} |\n")

    # Growth Media Preferences section
    report.append(f"\n## Growth Media Preferences\n")

    grows_in = media["grows_in"]
    no_growth = media["no_growth"]

    if grows_in:
        report.append(f"\n### Grows In ({len(grows_in)} media)\n")
        for i, m in enumerate(grows_in, 1):
            medium_name = m["medium_name"]
            medium_id = m["medium_id"]
            source = m["source"]

            # Get composition count if available
            comp_info = ""
            if not composition.empty:
                comp_row = composition[composition["medium_id"] == medium_id]
                if not comp_row.empty:
                    chem_count = comp_row["chemical_count"].iloc[0]
                    comp_info = f" - {chem_count} chemicals"

            report.append(f"{i}. **{medium_name}** ({medium_id}){comp_info}\n")
            report.append(f"   - Source: {source}\n")
    else:
        report.append("\n### Grows In\n")
        report.append("(No growth media data available)\n")

    if no_growth:
        report.append(f"\n### Does Not Grow In ({len(no_growth)} media)\n")
        for i, m in enumerate(no_growth, 1):
            medium_name = m["medium_name"]
            medium_id = m["medium_id"]
            source = m["source"]
            report.append(f"{i}. **{medium_name}** ({medium_id})\n")
            report.append(f"   - Source: {source}\n")

    # Media Composition Details section
    if not composition.empty and len(grows_in) > 0:
        report.append("\n## Media Composition Details\n")
        for _, row in composition.iterrows():
            medium_id = row["medium_id"]
            chem_count = row["chemical_count"]
            chemicals = row["chemicals"]

            # Find medium name
            medium_name = next(
                (m["medium_name"] for m in grows_in if m["medium_id"] == medium_id),
                medium_id,
            )

            report.append(f"\n### {medium_name} ({medium_id})\n")
            report.append(f"**Chemical components** ({chem_count} total):\n")

            # Split chemicals and show first 10
            chem_list = chemicals.split("; ") if chemicals else []
            for chem in chem_list[:10]:
                report.append(f"- {chem}\n")

            if len(chem_list) > 10:
                report.append(f"- ... and {len(chem_list) - 10} more\n")

    # Strain Information section
    if not strains.empty:
        report.append(f"\n## Strain Information ({len(strains)} strains)\n")

        # Show first 10 strains
        for _, row in strains.head(10).iterrows():
            strain_id = row["strain_id"]
            strain_name = row["strain_name"]
            report.append(f"- {strain_name} ({strain_id})\n")

        if len(strains) > 10:
            report.append(f"- ... and {len(strains) - 10} more\n")

    # Data Sources section
    report.append("\n## Data Sources\n")
    if sources:
        for source in sources:
            report.append(f"- {source}\n")
    else:
        report.append("(No source attribution available)\n")

    # Footer
    report.append("\n---\n")
    report.append("*Report generated from KG-Microbe knowledge graph*\n")

    return "".join(report)
