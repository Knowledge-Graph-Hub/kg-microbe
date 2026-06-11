#!/usr/bin/env python
"""
Generate the LinkML schema for the Fermentation Explorer clean database.

Bootstrapped from a schema-automator ``generalize-tsv`` draft, then curated here
into a typed, enumerated schema. The clean database
(``data/raw/fermentation_explorer_database_clean.csv``;
thackmann/FermentationExplorer ``database_clean.zip``) has 20,806 records x 52
columns: consolidated multi-source taxonomy, organism phenotypes, and
fermentation metabolism / end products.

The script reads the CSV to populate the controlled-vocabulary enums from the
data (splitting BacDive's ``;`` multi-value delimiter), and writes the schema
with one ``FermentationRecord`` class plus a ``FermentationDatabase`` container.

Usage::

    python scripts/generate_fermentation_explorer_schema.py \
        --input data/raw/fermentation_explorer_database_clean.csv \
        --output schema/fermentation_explorer.yaml
"""

import argparse
import re
from pathlib import Path

import pandas as pd
import yaml

SEMI = ";"


def snake(col: str) -> str:
    """Snake-case a column header (e.g. 'pH for growth' -> 'ph_for_growth')."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", col.strip()).strip("_").lower()
    return re.sub(r"_+", "_", s)


# Per-column curation: (range, multivalued-delimiter or None, enum-name or None, description).
# Columns are referenced by snake_case name. range None -> string.
LINK = "HTML anchor (<a href=...>) markup as stored in the clean database."
LINEAGE = "Lineage string in GTDB style (d__;p__;c__;o__;f__;g__;s__)."
SPEC = {
    "genus": (None, None, None, "Genus name."),
    "species": (None, None, None, "Species epithet."),
    "subspecies": (None, None, None, "Subspecies epithet."),
    "strain": (None, SEMI, None, "Strain designation(s); ';'-delimited."),
    "lpsn_id": (
        None,
        None,
        None,
        "LPSN identifier (unique, non-null; used as the record identifier).",
    ),
    "lpsn_page_link": (None, None, None, f"LPSN page link. {LINK}"),
    "lpsn_taxonomy": (None, None, None, f"LPSN taxonomy. {LINEAGE}"),
    "gtdb_id": (None, None, None, "GTDB genome accession."),
    "gtdb_id_link": (None, None, None, f"GTDB link. {LINK}"),
    "gtdb_taxonomy": (None, None, None, f"GTDB taxonomy. {LINEAGE}"),
    "gold_organism_id": (None, ",", None, "JGI GOLD organism ID(s); ','-delimited."),
    "gold_organism_id_link": (None, ",", None, f"GOLD organism link(s). {LINK}"),
    "gold_project_id": (None, ",", None, "JGI GOLD project ID(s); ','-delimited."),
    "gold_project_id_link": (None, ",", None, f"GOLD project link(s). {LINK}"),
    "ncbi_taxonomy_id": (None, None, None, "NCBI Taxonomy ID."),
    "ncbi_taxonomy_id_link": (None, None, None, f"NCBI Taxonomy link. {LINK}"),
    "ncbi_taxonomy": (None, None, None, f"NCBI taxonomy. {LINEAGE}"),
    "img_genome_id": (None, None, None, "JGI IMG genome ID."),
    "img_genome_id_link": (None, None, None, f"IMG genome link. {LINK}"),
    "img_genome_id_max_genes": (
        None,
        None,
        None,
        "IMG genome ID of the assembly with the most genes.",
    ),
    "bacdive_id": (None, None, None, "BacDive strain ID."),
    "bacdive_id_link": (None, None, None, f"BacDive link. {LINK}"),
    "antibiotic_resistance": (None, SEMI, None, "Antibiotics the organism resists; ';'-delimited."),
    "antibiotic_sensitivity": (
        None,
        SEMI,
        None,
        "Antibiotics the organism is sensitive to; ';'-delimited.",
    ),
    "cell_length_in_microns": ("float", None, None, "Cell length (micrometres)."),
    "cell_shape": (None, SEMI, "CellShapeEnum", "Cell shape(s); ';'-delimited."),
    "cell_width_in_microns": ("float", None, None, "Cell width (micrometres)."),
    "colony_size": ("float", None, None, "Colony size (mm)."),
    "flagellum_arrangement": (
        None,
        SEMI,
        "FlagellumArrangementEnum",
        "Flagellum arrangement(s); ';'-delimited.",
    ),
    "gram_stain": (None, SEMI, "GramStainEnum", "Gram stain result(s); ';'-delimited."),
    "incubation_period_in_days": ("float", None, None, "Incubation period (days)."),
    "indole_test": (None, SEMI, "IndoleTestEnum", "Indole test result."),
    "motility": (None, SEMI, "MotilityEnum", "Motility."),
    "oxygen_tolerance": (
        None,
        SEMI,
        "OxygenToleranceEnum",
        "Oxygen tolerance class(es); ';'-delimited.",
    ),
    "ph_for_growth": ("float", None, None, "Representative pH for growth."),
    "pathogenicity": (None, SEMI, "PathogenicityEnum", "Pathogenicity host(s); ';'-delimited."),
    "salt_for_growth_in_moles_per_liter": (
        "float",
        None,
        None,
        "Representative salt concentration for growth (mol/L).",
    ),
    "spore_formation": (None, SEMI, "SporeFormationEnum", "Spore formation."),
    "temperature_for_growth_in_degrees": (
        "float",
        None,
        None,
        "Representative growth temperature (degrees C).",
    ),
    "voges_proskauer": (None, SEMI, "VogesProskauerEnum", "Voges-Proskauer test result."),
    "isolation_category_1": (
        None,
        SEMI,
        "IsolationCategory1Enum",
        "Level 1 BacDive isolation-source category; ';'-delimited.",
    ),
    "isolation_category_2": (
        None,
        SEMI,
        "IsolationCategory2Enum",
        "Level 2 BacDive isolation-source category; ';'-delimited.",
    ),
    "isolation_category_3": (
        None,
        SEMI,
        "IsolationCategory3Enum",
        "Level 3 BacDive isolation-source category; ';'-delimited.",
    ),
    "bergey_article_link": (None, None, None, f"Bergey's Manual article link. {LINK}"),
    "bergey_taxonomy": (None, None, None, f"Bergey taxonomy. {LINEAGE}"),
    "type_of_metabolism": (None, SEMI, "TypeOfMetabolismEnum", "Type of metabolism."),
    "end_products": (None, SEMI, None, "Metabolic end products; ';'-delimited."),
    "major_end_products": (None, SEMI, None, "Major metabolic end products; ';'-delimited."),
    "minor_end_products": (None, SEMI, None, "Minor metabolic end products; ';'-delimited."),
    "substrates_for_end_products": (
        None,
        SEMI,
        None,
        "Substrates yielding the end products; ';'-delimited.",
    ),
    "fermentation_substrates": (None, SEMI, None, "Substrates fermented; ';'-delimited."),
    "faprotax_traits": (None, SEMI, None, "FAPROTAX functional traits; ';'-delimited."),
}
ENUM_DESCRIPTIONS = {
    "CellShapeEnum": "Cell shapes observed in the database.",
    "FlagellumArrangementEnum": "Flagellum arrangements observed in the database.",
    "GramStainEnum": "Gram stain results.",
    "IndoleTestEnum": "Indole test results.",
    "MotilityEnum": "Motility values.",
    "OxygenToleranceEnum": "Oxygen tolerance classes.",
    "PathogenicityEnum": "Pathogenicity hosts.",
    "SporeFormationEnum": "Spore formation values.",
    "VogesProskauerEnum": "Voges-Proskauer test results.",
    "TypeOfMetabolismEnum": "Types of energy metabolism.",
    "IsolationCategory1Enum": "Level 1 of BacDive's isolation-source classification (no '#' prefix).",
    "IsolationCategory2Enum": "Level 2 of BacDive's isolation-source classification (no '#' prefix).",
    "IsolationCategory3Enum": "Level 3 of BacDive's isolation-source classification (no '#' prefix).",
}


def base_values(series, delim):
    """Distinct delimiter-split, stripped values of a column, sorted."""
    out = set()
    for v in series.dropna():
        for part in str(v).split(delim):
            part = part.strip()
            if part:
                out.add(part)
    return sorted(out)


def main():
    """Read the clean CSV, build enums from the data, and write the schema."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="data/raw/fermentation_explorer_database_clean.csv")
    ap.add_argument("--output", default="schema/fermentation_explorer.yaml")
    args = ap.parse_args()

    df = pd.read_csv(args.input, dtype=str)
    df.columns = [snake(c) for c in df.columns]

    # enums from data
    enums = {}
    for col, (_rng, _mv, enum_name, _desc) in SPEC.items():
        if enum_name and col in df.columns:
            vals = base_values(df[col], SPEC[col][1] or SEMI)
            enums.setdefault(
                enum_name,
                {
                    "description": ENUM_DESCRIPTIONS.get(enum_name, enum_name),
                    "permissible_values": {},
                },
            )
            for v in vals:
                enums[enum_name]["permissible_values"].setdefault(v, {})

    # slots
    slots = {}
    for col, (rng, mv, enum_name, desc) in SPEC.items():
        slot = {"description": desc}
        if col == "lpsn_id":
            slot["identifier"] = True
        slot["range"] = enum_name or rng or "string"
        if mv:
            slot["multivalued"] = True
        slot["required"] = col == "genus"
        slots[col] = slot

    schema = {
        "name": "FermentationExplorer",
        "title": "Fermentation Explorer database (clean)",
        "id": "https://w3id.org/kg-microbe/fermentation-explorer",
        "description": (
            "LinkML schema for the Fermentation Explorer clean database "
            "(thackmann/FermentationExplorer database_clean.zip -> "
            "data/raw/fermentation_explorer_database_clean.csv): "
            f"{len(df):,} records x {len(df.columns)} columns of consolidated "
            "multi-source taxonomy (LPSN/GTDB/GOLD/NCBI/IMG/Bergey), organism "
            "phenotypes, and fermentation metabolism / end products. Bootstrapped "
            "with schema-automator (generalize-tsv) then curated: enums populated "
            "from the data, ';'-delimited cells modelled multivalued (GOLD IDs use "
            "','), measurements typed float, and *_link columns flagged as HTML. "
            "The raw 95-column per-source table is "
            "data/raw/fermentation_explorer_database_raw.csv (reference/triage)."
        ),
        "prefixes": {
            "linkml": "https://w3id.org/linkml/",
            "FermentationExplorer": "https://w3id.org/kg-microbe/fermentation-explorer/",
        },
        "default_prefix": "FermentationExplorer",
        "default_range": "string",
        "imports": ["linkml:types"],
        "classes": {
            "FermentationDatabase": {
                "tree_root": True,
                "description": "Container for Fermentation Explorer records.",
                "attributes": {
                    "records": {
                        "range": "FermentationRecord",
                        "multivalued": True,
                        "inlined_as_list": True,
                    }
                },
            },
            "FermentationRecord": {
                "description": (
                    "One organism record: taxonomy, phenotype and fermentation "
                    "metabolism for a strain."
                ),
                "slots": list(SPEC.keys()),
            },
        },
        "slots": slots,
        "enums": enums,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as fh:
        yaml.safe_dump(schema, fh, sort_keys=False, allow_unicode=True, width=100)
    print(f"wrote {args.output}: {len(slots)} slots, {len(enums)} enums")
    for en, e in enums.items():
        print(f"  {en}: {len(e['permissible_values'])} values")


if __name__ == "__main__":
    main()
