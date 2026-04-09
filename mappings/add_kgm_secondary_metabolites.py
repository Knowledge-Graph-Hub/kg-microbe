#!/usr/bin/env python3
"""
Add KGM custom terms for secondary metabolites/antibiotics with no public CHEBI IDs.

Adds entries to:
1. kg_microbe/transform_utils/custom_curies.yaml  — KGM node definitions
2. kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv — produces: X entries
3. mappings/unified_chemical_mappings.tsv.gz — blasticidin (CHEBI:22905, only real hit)
"""

import gzip
import re
from pathlib import Path

HERE = Path(__file__).parent.parent  # repo root

# ── Compound data ────────────────────────────────────────────────────────────
# (trait_compound, kgm_slug, description)
# Compounds already in KGM YAML are marked with existing_kgm=True
# Compounds with real CHEBI are handled separately

COMPOUNDS = [
    # Already in KGM YAML — just need special_chemical_mappings entries
    ("setamycin",           "setamycin",           None, True),
    ("gardimycin",          "gardimycin",          None, True),
    ("kijanimicin",         "kijanimicin",         None, True),
    ("candiplanecin",       "candiplanecin",       None, True),
    ("decaplanin",          "decaplanin",          None, True),
    ("ristocetin B",        "ristocetin_b",        None, True),
    ("Cetocycline",         "cetocycline",         None, True),
    ("butyricin 7423",      "butyricin_7423",      None, True),
    ("dopsisamine",         "dopsisamine",         None, True),
    ("indochrome",          "indochrome",          None, True),
    ("nocamycin",           "nocamycin",           None, True),
    ("hitachimycin",        "hitachimycin",        None, True),
    ("ardacin B",           "ardacin_b",           None, True),
    ("Ethylenediamine-N,N'-disuccinic acid",
                            "ethylenediamine_n_n_prime_disuccinic_acid", None, True),
    # New KGM entries needed
    ("halomicin",           "halomicin",
     "Macrolide antibiotic produced by Micromonospora halophytica", False),
    ("mycobacidin",         "mycobacidin",
     "Siderophore/antibiotic produced by Mycobacterium and Nocardia spp.", False),
    ("geomycin",            "geomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("aburamycin A",        "aburamycin_a",
     "Polyene macrolide antibiotic produced by Streptomyces spp.", False),
    ("poly(L-lysine) polymer", "poly_l_lysine_polymer",
     "Cationic polypeptide biopolymer (epsilon-poly-L-lysine) produced by Streptomyces albulus and related species", False),
    ("monazomycin",         "monazomycin",
     "Polyene antibiotic produced by Streptomyces spp.", False),
    ("azureomycin",         "azureomycin",
     "Chromopeptide antibiotic produced by Streptomyces spp.", False),
    ("avoparcin",           "avoparcin",
     "Glycopeptide antibiotic produced by Streptomyces candidus; formerly used as growth promoter", False),
    ("actinohivin",         "actinohivin",
     "Lectin-like antiviral protein produced by Longispora albida (Actinomycetes)", False),
    ("dynemicin",           "dynemicin",
     "Enediyne antibiotic produced by Micromonospora chersina", False),
    ("abyssomicin B",       "abyssomicin_b",
     "Spirotetronic acid antibiotic (abyssomicin family) produced by Verrucosispora spp.", False),
    ("abyssomicin G",       "abyssomicin_g",
     "Spirotetronic acid antibiotic (abyssomicin family) produced by Verrucosispora spp.", False),
    ("atrop-abyssomicin C", "atrop_abyssomicin_c",
     "Atropisomeric form of abyssomicin C; spirotetronic acid antibiotic", False),
    ("abyssomicin H",       "abyssomicin_h",
     "Spirotetronic acid antibiotic (abyssomicin family) produced by Verrucosispora spp.", False),
    ("abyssomicin D",       "abyssomicin_d",
     "Spirotetronic acid antibiotic (abyssomicin family) produced by Verrucosispora spp.", False),
    ("actinotiocin",        "actinotiocin",
     "Thiopeptide antibiotic produced by Streptomyces spp.", False),
    ("sporangiomycin",      "sporangiomycin",
     "Lipopeptide antibiotic produced by Planomonospora spp.", False),
    ("chlororaphin",        "chlororaphin",
     "Phenazine derivative antibiotic produced by Pseudomonas chlororaphis", False),
    ("sarcidin",            "sarcidin",
     "Antibiotic produced by Sarcina spp.", False),
    ("achromoviromycin",    "achromoviromycin",
     "Antiviral antibiotic produced by Streptomyces spp.", False),
    ("primocarcin",         "primocarcin",
     "Anthracycline antibiotic produced by Streptomyces spp.", False),
    ("alanosine",           "alanosine",
     "Amino acid analogue antibiotic and antitumor agent produced by Streptomyces alanosinicus", False),
    ("danomycin",           "danomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("actinomycetin",       "actinomycetin",
     "Bacteriocin-like protein produced by Actinomyces spp.", False),
    ("champamycin B",       "champamycin_b",
     "Polyene antibiotic (champamycin family) produced by Streptomyces spp.", False),
    ("ascosin",             "ascosin",
     "Polyene macrolide antifungal produced by Streptomyces spp.", False),
    ("limocrocin",          "limocrocin",
     "Polyene chromophore antibiotic produced by Streptomyces spp.", False),
    ("eurocidin",           "eurocidin",
     "Polyene macrolide antifungal produced by Streptomyces spp.", False),
    ("pamamycin",           "pamamycin",
     "Macrolide signaling molecule and antibiotic produced by Streptomyces alboniger", False),
    ("angustmycin",         "angustmycin",
     "Nucleoside antibiotic produced by Streptomyces hygroscopicus", False),
    ("camphomycin",         "camphomycin",
     "Polypeptide antibiotic produced by Streptomyces spp.", False),
    ("cinerubin A",         "cinerubin_a",
     "Anthracycline antibiotic produced by Streptomyces violaceus", False),
    ("canarius",            "canarius",
     "Antibiotic produced by Streptomyces canarius", False),
    ("rhodomycin A",        "rhodomycin_a",
     "Anthracycline antibiotic produced by Streptomyces purpurascens", False),
    ("durhamycin",          "durhamycin",
     "Antibiotic produced by Streptomyces hygroscopicus subsp. durhamensis", False),
    ("angolamycin",         "angolamycin",
     "Macrolide antibiotic produced by Streptomyces hygroscopicus", False),
    ("flavofungin",         "flavofungin",
     "Polyene macrolide antifungal produced by Streptomyces spp.", False),
    ("glebomycin",          "glebomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("5,6-dihydro-5-azathymidine", "dihydro_azathymidine",
     "Nucleoside analogue produced by Streptomyces spp.", False),
    ("bandamycin",          "bandamycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("minimycin",           "minimycin",
     "Nucleoside antibiotic produced by Streptomyces spp.", False),
    ("vulgamycin",          "vulgamycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("trans-styrylacetic acid", "trans_styrylacetic_acid",
     "Aromatic carboxylic acid secondary metabolite produced by Streptomyces spp.", False),
    ("phoslactomycin",      "phoslactomycin",
     "Polyketide phosphate ester antibiotic produced by Streptomyces spp.", False),
    ("amphotericin A",      "amphotericin_a",
     "Minor polyene macrolide component (less active isomer of amphotericin B) produced by Streptomyces nodosus", False),
    ("synergistin A",       "synergistin_a",
     "Streptogramin A component antibiotic produced by Streptomyces spp.", False),
    ("staphylomycin M1",    "staphylomycin_m1",
     "Streptogramin B component antibiotic produced by Streptomyces virginiae", False),
    ("plicacetin",          "plicacetin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("pluramycin A",        "pluramycin_a",
     "Antitumor antibiotic produced by Streptomyces pluricolorescens", False),
    ("fradicin",            "fradicin",
     "Polyene antifungal antibiotic produced by Streptomyces fradiae", False),
    ("rubradirin",          "rubradirin",
     "Antibiotic produced by Streptomyces achromogenes subsp. rubradiris", False),
    ("ardacin C",           "ardacin_c",
     "Glycopeptide antibiotic component (ardacin family) produced by Kibdelosporangium spp.", False),
    ("ardacin A",           "ardacin_a",
     "Glycopeptide antibiotic component (ardacin family) produced by Kibdelosporangium spp.", False),
    ("venturicidin B",      "venturicidin_b",
     "Macrolide ATP synthase inhibitor antibiotic produced by Streptomyces spp.", False),
    ("cystargin",           "cystargin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("xanthocidin",         "xanthocidin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("transvalencin A",     "transvalencin_a",
     "Antibiotic produced by Streptomyces transvalensis", False),
    ("7-Hydro-8-methylpteroylglutamylglutamic acid", "hydro_methylpteroylglutamylglutamic_acid",
     "Pteroyl-amino acid secondary metabolite", False),
    ("bacteriocin ISK-1",   "bacteriocin_isk_1",
     "Bacteriocin produced by Streptomyces spp.", False),
    ("phyllomycin",         "phyllomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("grisamine",           "grisamine",
     "Antibiotic produced by Streptomyces spp.", False),
    ("carcinomycin",        "carcinomycin",
     "Anthracycline antitumor antibiotic produced by Streptomyces spp.", False),
    ("exfoliatin",          "exfoliatin",
     "Exfoliative toxin (serine protease) produced by Staphylococcus aureus", False),
    ("tertiomycin B",       "tertiomycin_b",
     "Antibiotic produced by Streptomyces spp.", False),
    ("tertiomycin A",       "tertiomycin_a",
     "Antibiotic produced by Streptomyces spp.", False),
    ("congocidin",          "congocidin",
     "Antibiotic produced by Streptomyces ambofaciens (synonym: distamycin-related compound)", False),
    ("ketomycin",           "ketomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("actinomycin A",       "actinomycin_a",
     "Chromodepsipeptide antibiotic (actinomycin family, less active than actinomycin D) produced by Streptomyces spp.", False),
    ("flavensomycin",       "flavensomycin",
     "Polyene antifungal antibiotic produced by Streptomyces spp.", False),
    ("cellostatin",         "cellostatin",
     "Antifungal antibiotic produced by Streptomyces spp.", False),
    ("tuberactinamine A",   "tuberactinamine_a",
     "Cyclic peptide antibiotic component (tuberactinomycin family) produced by Streptomyces spp.", False),
    ("azacolutin",          "azacolutin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("tuberactinomycin",    "tuberactinomycin",
     "Cyclic peptide antibiotic produced by Streptomyces spp.", False),
    ("collinomycin",        "collinomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("etamycin",            "etamycin",
     "Thiodepsipeptide antibiotic produced by Streptomyces griseoviridus", False),
    ("destomycin",          "destomycin",
     "Aminoglycoside antibiotic produced by Streptomyces spp.", False),
    ("candimycin",          "candimycin",
     "Polyene macrolide antifungal produced by Streptomyces viridoflavus", False),
    ("caryomycin",          "caryomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("ferroverdin",         "ferroverdin",
     "Iron-containing green pigment antibiotic produced by Streptomyces spp.", False),
    ("racemomycin E",       "racemomycin_e",
     "Aminoglycoside antibiotic component produced by Streptomyces spp.", False),
    ("alboverticillin",     "alboverticillin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("adenomycin",          "adenomycin",
     "Nucleoside antibiotic produced by Streptomyces spp.", False),
    ("griseolutein A",      "griseolutein_a",
     "Pyridazine antibiotic produced by Streptomyces griseoluteus", False),
    ("griseolutein B",      "griseolutein_b",
     "Pyridazine antibiotic produced by Streptomyces griseoluteus", False),
    ("viridogrisein",       "viridogrisein",
     "Streptogramin B-type antibiotic produced by Streptomyces spp.", False),
    ("noformicin",          "noformicin",
     "Antibiotic produced by Nocardia spp.", False),
    ("danubomycin",         "danubomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("cladomycin",          "cladomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("grasseriomycin",      "grasseriomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("levorin",             "levorin",
     "Polyene macrolide antifungal produced by Streptomyces levoris", False),
    ("bafilomycin",         "bafilomycin",
     "Macrolide antibiotic and V-ATPase inhibitor produced by Streptomyces spp.", False),
    ("lydimycin",           "lydimycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("chaninin",            "chaninin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("miharamycin A",       "miharamycin_a",
     "Nucleoside antibiotic produced by Streptomyces miharaensis", False),
    ("stallimycin",         "stallimycin",
     "Oligopeptide antibiotic produced by Streptomyces spp.", False),
    ("cytovirin",           "cytovirin",
     "Antitumor antibiotic produced by Streptomyces spp.", False),
    ("pactamycin",          "pactamycin",
     "Aminocyclitol antibiotic and translation inhibitor produced by Streptomyces pactum", False),
    ("etabetacin",          "etabetacin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("cephamycin A",        "cephamycin_a",
     "Beta-lactam cephamycin antibiotic produced by Streptomyces clavuligerus and related species", False),
    ("plumbemycin A",       "plumbemycin_a",
     "Phosphonate antibiotic produced by Streptomyces plumbeus", False),
    ("plumbemycin B",       "plumbemycin_b",
     "Phosphonate antibiotic produced by Streptomyces plumbeus", False),
    ("O-carbamyl-D-serine", "o_carbamyl_d_serine",
     "Amino acid analogue secondary metabolite produced by Streptomyces spp.", False),
    ("steffimycin",         "steffimycin",
     "Anthracycline antibiotic produced by Streptomyces steffisburgensis", False),
    ("beta-Lipomycin",      "beta_lipomycin",
     "Lipophilic antibiotic (lipomycin family) produced by Streptomyces aureofaciens", False),
    ("kanchanomycin",       "kanchanomycin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("(E)-4-Aminostyryl acetate", "e_4_aminostyryl_acetate",
     "Aromatic amine secondary metabolite produced by Streptomyces spp.", False),
    ("hortesin",            "hortesin",
     "Antibiotic produced by Streptomyces spp.", False),
    ("piericidin",          "piericidin",
     "Pyridine-quinone electron transport inhibitor produced by Streptomyces mobaraensis", False),
]

# ── 1. Load existing custom_curies.yaml ──────────────────────────────────────
cc_file = HERE / "kg_microbe/transform_utils/custom_curies.yaml"
with open(cc_file) as f:
    original_yaml = f.read()

# Find the end of the KGM section (last entry before EOF)
# We'll append new entries to the KGM: section
import yaml
cc = yaml.safe_load(original_yaml)
existing_kgm = set(cc.get("KGM", {}).keys())

new_kgm_entries = []
for trait_compound, slug, description, existing in COMPOUNDS:
    if existing or slug in existing_kgm:
        continue  # skip already-defined
    new_kgm_entries.append((slug, trait_compound, description))

print(f"New KGM entries to add: {len(new_kgm_entries)}")

# Append to YAML file
kgm_yaml_lines = []
for slug, label, description in new_kgm_entries:
    kgm_yaml_lines.append(f"\n  {slug}:")
    kgm_yaml_lines.append(f'    label: "{label}"')
    kgm_yaml_lines.append(f'    description: "{description}"')
    kgm_yaml_lines.append(f'    category: "biolink:ChemicalEntity"')

with open(cc_file, "a") as f:
    f.write("\n".join(kgm_yaml_lines) + "\n")

print(f"  Appended {len(new_kgm_entries)} entries to custom_curies.yaml")

# ── 2. Add to special_chemical_mappings.tsv ──────────────────────────────────
scm_file = HERE / "kg_microbe/transform_utils/metatraits/mappings/special_chemical_mappings.tsv"
TAG = "metatraits_unmapped[2026-04-09]"

scm_lines = []
for trait_compound, slug, description, _ in COMPOUNDS:
    # Skip Ethylenediamine — "produces:" version: trait is "produces: Ethylenediamine..."
    # The actual trait uses the compound name as-is
    kgm_curie = f"KGM:{slug}"
    trait_pattern = f"produces: {trait_compound}"
    notes = f"Secondary metabolite/antibiotic; no public CHEBI ID; {TAG}"
    scm_lines.append(
        f"{trait_pattern}\t{trait_compound}\t{kgm_curie}\t{trait_compound}\t"
        f"METPO:2000202\tbiolink:ChemicalEntity\t{notes}"
    )

# Special: produces: casein (2 obs) — casein already handled, add alias
# produces: casein → FOODON:03420180 (it's producing casein protein)
scm_lines.append(
    "produces: casein\tcasein\tFOODON:03420180\tcasein\t"
    "METPO:2000202\tbiolink:Food\tProducing casein protein; FOODON:03420180"
)

# blasticidin is handled via unified_chemical_mappings (CHEBI:22905)

with open(scm_file, "a") as f:
    f.write("\n".join(scm_lines) + "\n")

print(f"  Appended {len(scm_lines)} entries to special_chemical_mappings.tsv")

# ── 3. Add blasticidin to unified_chemical_mappings ──────────────────────────
um_file = HERE / "mappings/unified_chemical_mappings.tsv.gz"
with gzip.open(um_file, "at", encoding="utf-8") as f:
    f.write("CHEBI:22905\tblasticidin\t\tblasticidin\t\tmetatraits_unmapped[2026-04-09]\n")
print("  Added CHEBI:22905 (blasticidin) to unified_chemical_mappings.tsv.gz")

print("\nDone.")
