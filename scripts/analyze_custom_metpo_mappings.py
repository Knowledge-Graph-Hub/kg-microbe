#!/usr/bin/env python3
"""
Analyze custom metatraits mappings vs METPO ontology.

This script:
1. Loads METPO ontology mappings (classes and properties)
2. Loads Tier 1 manual mappings from TSV files
3. Extracts Tier 1.5-2.0 pattern-based mappings from code
4. Compares custom mappings against METPO
5. Outputs TSV and markdown reports
"""

import csv
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import requests

# URLs for METPO ontology
METPO_CLASSES_URL = (
    "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2025-12-12/src/templates/metpo_sheet.tsv"
)
METPO_PROPERTIES_URL = (
    "https://raw.githubusercontent.com/berkeleybop/metpo/refs/tags/2025-12-12/src/templates/metpo-properties.tsv"
)

# Base paths
BASE_DIR = Path(__file__).parent.parent
MAPPINGS_DIR = BASE_DIR / "kg_microbe" / "transform_utils" / "metatraits" / "mappings"
OUTPUT_DIR = BASE_DIR / "mappings"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_metpo_classes() -> Dict[str, Dict]:
    """Load METPO classes from remote ROBOT template."""
    print("Loading METPO classes...")
    response = requests.get(METPO_CLASSES_URL, timeout=30)
    response.raise_for_status()

    lines = response.text.splitlines()
    reader = csv.DictReader(lines[2:], fieldnames=lines[0].split("\t"), delimiter="\t")

    classes = {}
    for row in reader:
        curie = row.get("ID", "").strip()
        label = row.get("label", "").strip()
        madin_synonym = row.get("madin synonym or field", "").strip()
        bacdive_synonym = row.get("bacdive keyword synonym", "").strip()
        biolink_equiv = row.get("biolink equivalent", "").strip()

        if curie and label:
            synonyms = []
            if madin_synonym:
                synonyms.extend([s.strip() for s in madin_synonym.split("|") if s.strip()])
            if bacdive_synonym:
                for item in bacdive_synonym.split("|"):
                    item = item.strip()
                    if item and "." not in item:  # Exclude JSON paths
                        synonyms.append(item)

            classes[curie] = {
                "label": label,
                "synonyms": synonyms,
                "biolink_equivalent": biolink_equiv,
            }

    print(f"  Loaded {len(classes)} METPO classes")
    return classes


def load_metpo_properties() -> Dict[str, Dict]:
    """Load METPO properties from remote ROBOT template."""
    print("Loading METPO properties...")
    response = requests.get(METPO_PROPERTIES_URL, timeout=30)
    response.raise_for_status()

    lines = response.text.splitlines()
    # Properties file has header on line 0, ROBOT instructions on line 1, data from line 2
    # Need to strip whitespace from header column names
    headers = [h.strip() for h in lines[0].split("\t")]
    reader = csv.DictReader(lines[2:], fieldnames=headers, delimiter="\t")

    properties = {}
    for row in reader:
        curie = row.get("ID", "").strip()
        label = row.get("label", "").strip()

        # Skip header rows and annotation properties
        if curie and label and curie.startswith("METPO:"):
            properties[curie] = {
                "label": label,
            }

    print(f"  Loaded {len(properties)} METPO properties")
    return properties


def load_tier1_mappings() -> List[Dict]:
    """Load Tier 1 manual mappings from TSV files."""
    print("Loading Tier 1 manual mappings...")

    tier1_files = [
        "chemical_mappings.tsv",
        "enzyme_mappings.tsv",
        "pathway_mappings.tsv",
        "phenotype_mappings.tsv",
    ]

    mappings = []
    for filename in tier1_files:
        filepath = MAPPINGS_DIR / filename
        if not filepath.exists():
            print(f"  WARNING: {filepath} not found")
            continue

        with open(filepath, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                mappings.append({
                    "source_tier": "Tier 1 (manual)",
                    "source_file": filename,
                    "trait_pattern": row.get("subject_label", ""),
                    "object_id": row.get("object_id", ""),
                    "object_label": row.get("object_label", ""),
                    "object_source": row.get("object_source", ""),
                    "predicate_id": row.get("predicate_id", ""),
                    "notes": row.get("notes", ""),
                })

    print(f"  Loaded {len(mappings)} Tier 1 mappings")
    return mappings


def extract_tier15_chemical_patterns() -> List[Dict]:
    """Extract Tier 1.5 chemical pattern mappings from code."""
    print("Extracting Tier 1.5 chemical patterns...")

    # Hardcoded from _resolve_chemical_trait
    patterns = [
        ("carbon source: *", "METPO:2000006", "uses as carbon source", "ChEBI lookup"),
        ("produces: *", "METPO:2000202", "produces", "ChEBI lookup"),
        ("ferments: *", "METPO:2000011", "ferments", "ChEBI lookup"),
        ("hydrolyzes: *", "METPO:2000013", "hydrolyzes", "ChEBI lookup"),
        ("oxidizes: *", "METPO:2000016", "oxidizes", "ChEBI lookup"),
        ("reduces: *", "METPO:2000017", "reduces", "ChEBI lookup"),
        ("degrades: *", "METPO:2000007", "degrades", "ChEBI lookup"),
        ("utilizes: *", "METPO:2000001", "organism interacts with chemical", "ChEBI lookup"),
    ]

    mappings = []
    for pattern, predicate, label, note in patterns:
        mappings.append({
            "source_tier": "Tier 1.5 (chemical)",
            "trait_pattern": pattern,
            "metpo_curie": predicate,
            "predicate": predicate,
            "notes": f"{label}; {note}",
        })

    print(f"  Extracted {len(mappings)} Tier 1.5 patterns")
    return mappings


def extract_tier16_metabolic_patterns() -> List[Dict]:
    """Extract Tier 1.6 metabolic pattern mappings from code."""
    print("Extracting Tier 1.6 metabolic patterns...")

    # Hardcoded from _resolve_metabolic_trait
    patterns = [
        ("electron acceptor: *", "METPO:2000008", "uses as electron acceptor", "ChEBI lookup"),
        ("respiration: *", "METPO:2000008", "respiration uses electron acceptor", "ChEBI lookup"),
        ("reduction: *", "METPO:2000017", "reduces", "ChEBI lookup"),
        ("oxidation: *", "METPO:2000016", "oxidizes", "ChEBI lookup"),
        ("oxidation in darkness: *", "METPO:2000016", "oxidizes", "ChEBI lookup"),
        ("denitrification: *", "METPO:2000017", "reduces nitrate/nitrite/N2O", "ChEBI lookup"),
        ("ammonification: *", "METPO:2000014", "uses as nitrogen source", "ChEBI lookup"),
        ("degradation: *", "METPO:2000007", "degrades", "ChEBI or ENVO lookup"),
        ("hydrolysis: *", "METPO:2000013", "hydrolyzes", "ChEBI or ENVO lookup"),
    ]

    mappings = []
    for pattern, predicate, label, note in patterns:
        mappings.append({
            "source_tier": "Tier 1.6 (metabolic)",
            "trait_pattern": pattern,
            "metpo_curie": predicate,
            "predicate": predicate,
            "notes": f"{label}; {note}",
        })

    print(f"  Extracted {len(mappings)} Tier 1.6 patterns")
    return mappings


def extract_tier17_growth_patterns() -> List[Dict]:
    """Extract Tier 1.7 growth substrate pattern mappings from code."""
    print("Extracting Tier 1.7 growth patterns...")

    # Hardcoded from _resolve_growth_substrate
    patterns = [
        ("growth: *", "METPO:2000012", "uses for growth", "ChEBI lookup (excludes trophic modes)"),
        ("builds acid from: *", "METPO:2000003", "builds acid from", "ChEBI lookup"),
    ]

    mappings = []
    for pattern, predicate, label, note in patterns:
        mappings.append({
            "source_tier": "Tier 1.7 (growth)",
            "trait_pattern": pattern,
            "metpo_curie": predicate,
            "predicate": predicate,
            "notes": f"{label}; {note}",
        })

    print(f"  Extracted {len(mappings)} Tier 1.7 patterns")
    return mappings


def extract_tier18_trophic_patterns() -> List[Dict]:
    """Extract Tier 1.8 trophic mode pattern mappings from code."""
    print("Extracting Tier 1.8 trophic patterns...")

    # Hardcoded from _resolve_trophic_mode
    trophic_modes = [
        ("growth: phototrophy", "GO:0009579", "phototrophic process", "METPO:2000103", "GO BP"),
        ("growth: chemoheterotrophy", "GO:0044281", "small molecule metabolic process", "METPO:2000103", "GO BP"),
        ("growth: photoautotrophy", "GO:0009541", "photoautotrophic process", "METPO:2000103", "GO BP"),
        ("growth: photoheterotrophy", "GO:0009581", "photoheterotrophic process", "METPO:2000103", "GO BP"),
        ("growth: anoxygenic photoautotrophy", "GO:0019685", "photosynthesis, anoxygenic", "METPO:2000103", "GO BP"),
        ("growth: anoxygenic phototrophy", "GO:0019685", "photosynthesis, anoxygenic", "METPO:2000103", "GO BP"),
        ("aerobic growth: *", "METPO:1001003", "aerobe", "METPO:2000102", "METPO phenotype"),
        ("anaerobic growth: *", "METPO:1001004", "anaerobe", "METPO:2000102", "METPO phenotype"),
    ]

    mappings = []
    for pattern, curie, label, predicate, note in trophic_modes:
        mappings.append({
            "source_tier": "Tier 1.8 (trophic)",
            "trait_pattern": pattern,
            "metpo_curie": curie,
            "predicate": predicate,
            "notes": f"{label}; {note}",
        })

    print(f"  Extracted {len(mappings)} Tier 1.8 patterns")
    return mappings


def extract_tier19_enzyme_patterns() -> List[Dict]:
    """Extract Tier 1.9 enzyme activity pattern mappings from code."""
    print("Extracting Tier 1.9 enzyme patterns...")

    # Hardcoded from _resolve_enzyme_activity
    patterns = [
        ("enzyme activity: * (EC*)", "EC:*", "EC number extraction", "METPO:2000302"),
    ]

    mappings = []
    for pattern, curie, label, predicate in patterns:
        mappings.append({
            "source_tier": "Tier 1.9 (enzyme)",
            "trait_pattern": pattern,
            "metpo_curie": curie,
            "predicate": predicate,
            "notes": f"{label}; shows activity of",
        })

    print(f"  Extracted {len(mappings)} Tier 1.9 patterns")
    return mappings


def extract_tier20_phenotype_patterns() -> List[Dict]:
    """Extract Tier 2.0 simple phenotype pattern mappings from code."""
    print("Extracting Tier 2.0 phenotype patterns...")

    # Hardcoded from _resolve_phenotype_trait
    phenotypes = [
        ("aerotolerant", "METPO:1001025", "aerotolerant", "METPO:2000102"),
        ("facultative anaerobe", "METPO:1001026", "facultative anaerobe", "METPO:2000102"),
        ("acidophilic", "METPO:1001015", "acidophile", "METPO:2000102"),
        ("capnophilic", "KGM:capnophilic", "capnophilic", "METPO:2000102"),
    ]

    mappings = []
    for pattern, curie, label, predicate in phenotypes:
        mappings.append({
            "source_tier": "Tier 2.0 (phenotype)",
            "trait_pattern": pattern,
            "metpo_curie": curie,
            "predicate": predicate,
            "notes": f"{label}; has phenotype",
        })

    print(f"  Extracted {len(mappings)} Tier 2.0 patterns")
    return mappings


def check_in_metpo(curie: str, metpo_classes: Dict, metpo_properties: Dict) -> Tuple[bool, str]:
    """Check if a CURIE exists in METPO ontology."""
    if curie.startswith("METPO:"):
        if curie in metpo_classes:
            return True, f"Class: {metpo_classes[curie]['label']}"
        elif curie in metpo_properties:
            return True, f"Property: {metpo_properties[curie]['label']}"
        else:
            return False, "Not found in METPO"
    else:
        return False, f"External ontology: {curie.split(':')[0]}"


def analyze_mappings():
    """Main analysis function."""
    print("=" * 80)
    print("Analyzing custom metatraits mappings vs METPO ontology")
    print("=" * 80)

    # Load METPO ontology
    metpo_classes = load_metpo_classes()
    metpo_properties = load_metpo_properties()

    # Load all custom mappings
    tier1_mappings = load_tier1_mappings()
    tier15_mappings = extract_tier15_chemical_patterns()
    tier16_mappings = extract_tier16_metabolic_patterns()
    tier17_mappings = extract_tier17_growth_patterns()
    tier18_mappings = extract_tier18_trophic_patterns()
    tier19_mappings = extract_tier19_enzyme_patterns()
    tier20_mappings = extract_tier20_phenotype_patterns()

    # Consolidate all mappings
    all_mappings = []

    # Process Tier 1 manual mappings
    for m in tier1_mappings:
        object_curie = m["object_id"]
        in_metpo, metpo_info = check_in_metpo(object_curie, metpo_classes, metpo_properties)

        all_mappings.append({
            "source_tier": m["source_tier"],
            "trait_pattern": m["trait_pattern"],
            "metpo_curie": object_curie,
            "predicate": m["predicate_id"],
            "in_metpo": "TRUE" if in_metpo else "FALSE",
            "metpo_info": metpo_info,
            "notes": m["notes"],
        })

    # Process Tier 1.5-2.0 pattern mappings
    for tier_mappings in [tier15_mappings, tier16_mappings, tier17_mappings,
                          tier18_mappings, tier19_mappings, tier20_mappings]:
        for m in tier_mappings:
            curie = m["metpo_curie"]
            predicate = m["predicate"]

            # Check both object curie and predicate in METPO
            curie_in_metpo, curie_info = check_in_metpo(curie, metpo_classes, metpo_properties)
            pred_in_metpo, pred_info = check_in_metpo(predicate, metpo_classes, metpo_properties)

            all_mappings.append({
                "source_tier": m["source_tier"],
                "trait_pattern": m["trait_pattern"],
                "metpo_curie": curie,
                "predicate": predicate,
                "in_metpo": "TRUE" if curie_in_metpo or pred_in_metpo else "FALSE",
                "metpo_info": f"Object: {curie_info}; Predicate: {pred_info}",
                "notes": m["notes"],
            })

    # Write TSV output
    output_tsv = OUTPUT_DIR / "custom_mappings_not_in_metpo.tsv"
    print(f"\nWriting output to {output_tsv}")

    with open(output_tsv, "w", newline="") as f:
        writer = csv.DictWriter(f,
            fieldnames=["source_tier", "trait_pattern", "metpo_curie", "predicate",
                       "in_metpo", "metpo_info", "notes"],
            delimiter="\t")
        writer.writeheader()
        writer.writerows(all_mappings)

    # Generate statistics
    total_mappings = len(all_mappings)
    in_metpo_count = sum(1 for m in all_mappings if m["in_metpo"] == "TRUE")
    not_in_metpo_count = sum(1 for m in all_mappings if m["in_metpo"] == "FALSE")

    tier1_count = sum(1 for m in all_mappings if m["source_tier"] == "Tier 1 (manual)")
    tier1_in_metpo = sum(1 for m in all_mappings if m["source_tier"] == "Tier 1 (manual)" and m["in_metpo"] == "TRUE")
    tier1_not_in_metpo = sum(1 for m in all_mappings if m["source_tier"] == "Tier 1 (manual)" and m["in_metpo"] == "FALSE")

    # Count by object source for Tier 1
    tier1_by_source = {}
    for m in tier1_mappings:
        source = m["object_source"]
        if source not in tier1_by_source:
            tier1_by_source[source] = {"total": 0, "in_metpo": 0, "not_in_metpo": 0}
        tier1_by_source[source]["total"] += 1

        object_curie = m["object_id"]
        in_metpo, _ = check_in_metpo(object_curie, metpo_classes, metpo_properties)
        if in_metpo:
            tier1_by_source[source]["in_metpo"] += 1
        else:
            tier1_by_source[source]["not_in_metpo"] += 1

    # Generate markdown report
    output_md = OUTPUT_DIR / "CUSTOM_MAPPINGS_ANALYSIS.md"
    print(f"Writing analysis to {output_md}")

    with open(output_md, "w") as f:
        f.write("# Custom Metatraits Mappings Analysis\n\n")
        f.write("## Overview\n\n")
        f.write("This document analyzes all custom metatraits mappings (manual + pattern-based) ")
        f.write("against the METPO ontology to identify which mappings are already in METPO ")
        f.write("and which are unique custom extensions.\n\n")

        f.write("## Summary Statistics\n\n")
        f.write(f"- **Total custom mappings**: {total_mappings}\n")
        f.write(f"- **Mappings using METPO terms**: {in_metpo_count} ({in_metpo_count/total_mappings*100:.1f}%)\n")
        f.write(f"- **Mappings NOT in METPO**: {not_in_metpo_count} ({not_in_metpo_count/total_mappings*100:.1f}%)\n\n")

        f.write("### Tier 1 Manual Mappings\n\n")
        f.write(f"- **Total Tier 1 mappings**: {tier1_count}\n")
        f.write(f"- **Using METPO terms**: {tier1_in_metpo} ({tier1_in_metpo/tier1_count*100:.1f}%)\n")
        f.write(f"- **NOT in METPO**: {tier1_not_in_metpo} ({tier1_not_in_metpo/tier1_count*100:.1f}%)\n\n")

        f.write("#### Tier 1 Mappings by Object Source\n\n")
        f.write("| Source | Total | In METPO | Not in METPO | % External |\n")
        f.write("|--------|-------|----------|--------------|------------|\n")
        for source in sorted(tier1_by_source.keys()):
            stats = tier1_by_source[source]
            pct_external = stats["not_in_metpo"] / stats["total"] * 100 if stats["total"] > 0 else 0
            f.write(f"| {source} | {stats['total']} | {stats['in_metpo']} | ")
            f.write(f"{stats['not_in_metpo']} | {pct_external:.1f}% |\n")

        f.write("\n### Pattern-Based Mappings (Tier 1.5-2.0)\n\n")

        for tier_name in ["Tier 1.5 (chemical)", "Tier 1.6 (metabolic)", "Tier 1.7 (growth)",
                         "Tier 1.8 (trophic)", "Tier 1.9 (enzyme)", "Tier 2.0 (phenotype)"]:
            tier_mappings = [m for m in all_mappings if m["source_tier"] == tier_name]
            if tier_mappings:
                tier_total = len(tier_mappings)
                tier_in_metpo = sum(1 for m in tier_mappings if m["in_metpo"] == "TRUE")
                f.write(f"- **{tier_name}**: {tier_total} patterns, ")
                f.write(f"{tier_in_metpo} use METPO predicates\n")

        f.write("\n## Key Findings\n\n")

        f.write("### 1. METPO Predicate Usage\n\n")
        f.write("All pattern-based resolvers (Tier 1.5-2.0) use METPO predicates correctly:\n\n")
        f.write("- `METPO:2000001` - organism interacts with chemical\n")
        f.write("- `METPO:2000002-2000020` - specific chemical interactions (produces, ferments, etc.)\n")
        f.write("- `METPO:2000103` - capable of (for biological processes)\n")
        f.write("- `METPO:2000102` - has phenotype\n")
        f.write("- `METPO:2000302` - shows activity of (for enzymes)\n\n")

        f.write("### 2. External Ontology References\n\n")
        f.write("Custom mappings correctly delegate to external ontologies when appropriate:\n\n")
        f.write("- **ChEBI**: Chemical substances (carbon source, electron acceptor patterns)\n")
        f.write("- **GO**: Biological processes (trophic modes, pathways)\n")
        f.write("- **EC**: Enzyme classification (enzyme activity with EC numbers)\n\n")

        f.write("### 3. Tier 1 Manual Mappings Analysis\n\n")

        # Identify METPO duplicates
        tier1_metpo = [m for m in all_mappings if m["source_tier"] == "Tier 1 (manual)" and m["in_metpo"] == "TRUE"]
        if tier1_metpo:
            f.write(f"**{len(tier1_metpo)} Tier 1 mappings use METPO terms:**\n\n")
            for m in tier1_metpo:
                f.write(f"- `{m['trait_pattern']}` → `{m['metpo_curie']}` ({m['metpo_info']})\n")
            f.write("\n**Recommendation**: These can potentially be removed after METPO priority change, ")
            f.write("as they should be resolved automatically by METPO synonym matching.\n\n")

        # Identify external ontology mappings
        tier1_external = [m for m in all_mappings if m["source_tier"] == "Tier 1 (manual)" and m["in_metpo"] == "FALSE"]
        if tier1_external:
            f.write(f"**{len(tier1_external)} Tier 1 mappings use external ontologies:**\n\n")
            by_source = {}
            for m in tier1_external:
                prefix = m["metpo_curie"].split(":")[0]
                if prefix not in by_source:
                    by_source[prefix] = []
                by_source[prefix].append(m)

            for prefix in sorted(by_source.keys()):
                mappings = by_source[prefix]
                f.write(f"\n**{prefix} ({len(mappings)} mappings):**\n\n")
                for m in mappings[:10]:  # Show first 10
                    f.write(f"- `{m['trait_pattern']}` → `{m['metpo_curie']}`\n")
                if len(mappings) > 10:
                    f.write(f"- ... and {len(mappings) - 10} more\n")

            f.write("\n**Recommendation**: These should remain as Tier 1 mappings as they provide ")
            f.write("specific chemical/pathway/enzyme mappings not in METPO.\n\n")

        f.write("## Impact of METPO Priority Change\n\n")
        f.write("### Current Resolution Order\n\n")
        f.write("1. Tier 1: Manual mappings (4 TSV files)\n")
        f.write("2. Tier 1.5-2.0: Pattern-based resolvers\n")
        f.write("3. Tier 3: METPO synonym matching\n")
        f.write("4. Tier 4: OAK adapter search\n\n")

        f.write("### Proposed Resolution Order\n\n")
        f.write("1. Tier 1: METPO synonym matching (classes + properties)\n")
        f.write("2. Tier 2: Manual mappings (external ontologies only)\n")
        f.write("3. Tier 3: Pattern-based resolvers\n")
        f.write("4. Tier 4: OAK adapter search\n\n")

        f.write("### Expected Benefits\n\n")
        f.write(f"1. **Reduced manual mapping maintenance**: {tier1_in_metpo} Tier 1 METPO mappings ")
        f.write("can be removed, reducing manual TSV file maintenance.\n\n")
        f.write("2. **Improved consistency**: All METPO terms will use official METPO labels ")
        f.write("and predicates from the ontology.\n\n")
        f.write("3. **Automatic updates**: New METPO terms and synonyms will be available ")
        f.write("immediately without code changes.\n\n")
        f.write("4. **Clearer separation**: Tier 1 manual mappings will focus exclusively on ")
        f.write("external ontology bridges (ChEBI, GO, EC).\n\n")

        f.write("### Migration Steps\n\n")
        f.write("1. Test METPO-first resolution with current test suite\n")
        f.write("2. Remove Tier 1 mappings that duplicate METPO synonyms\n")
        f.write("3. Keep Tier 1 mappings for external ontologies (ChEBI, GO, EC)\n")
        f.write("4. Update documentation to reflect new priority order\n")
        f.write("5. Monitor edge counts to ensure no regressions\n\n")

        f.write("## Recommendations\n\n")
        f.write("### Short-term\n\n")
        f.write("1. Implement METPO-first resolution order\n")
        f.write("2. Keep all current mappings during transition\n")
        f.write("3. Add logging to track which tier resolves each trait\n\n")

        f.write("### Medium-term\n\n")
        f.write("1. Remove redundant Tier 1 METPO mappings after validation\n")
        f.write("2. Propose missing terms to METPO ontology:\n")
        f.write("   - Pattern-based mappings that should be METPO classes\n")
        f.write("   - Common chemical/pathway mappings from Tier 1\n\n")

        f.write("### Long-term\n\n")
        f.write("1. Contribute back to METPO ontology development\n")
        f.write("2. Align KG-Microbe trait patterns with METPO structure\n")
        f.write("3. Develop METPO-based validation for data quality\n\n")

    print("\n" + "=" * 80)
    print("Analysis complete!")
    print(f"  TSV output: {output_tsv}")
    print(f"  Markdown analysis: {output_md}")
    print("=" * 80)


if __name__ == "__main__":
    analyze_mappings()
