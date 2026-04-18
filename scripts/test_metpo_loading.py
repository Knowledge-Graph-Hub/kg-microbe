#!/usr/bin/env python3
"""Test METPO ontology loading for metatraits transform validation."""

from kg_microbe.utils.mapping_file_utils import load_metpo_mappings

# Test critical traits
test_traits = {
    "gram positive": "METPO:1000698",
    "gram negative": "METPO:1000699",
    "obligate aerobic": "METPO:1000606",
    "thermophilic": "METPO:1000616",
}

print("=== METPO Loading Validation ===\n")

# Test with "metatraits synonym" (correct for metatraits transform)
print("Using 'metatraits synonym' column (CORRECT for metatraits):")
mappings_metatraits = load_metpo_mappings("metatraits synonym")
for trait, expected_curie in test_traits.items():
    result = mappings_metatraits.get(trait.lower())
    if result:
        actual_curie = result["curie"]
        status = "✓" if actual_curie == expected_curie else "✗"
        print(f"  {status} {trait}: {actual_curie} (expected {expected_curie})")
    else:
        print(f"  ✗ {trait}: NOT FOUND")
print(f"  Total mappings: {len(mappings_metatraits)}\n")

# Test with "madin synonym or field" (wrong for metatraits, correct for madin_etal)
print("Using 'madin synonym or field' column (WRONG for metatraits):")
mappings_madin = load_metpo_mappings("madin synonym or field")
for trait, expected_curie in test_traits.items():
    result = mappings_madin.get(trait.lower())
    if result:
        actual_curie = result["curie"]
        status = "✓" if actual_curie == expected_curie else "✗"
        print(f"  {status} {trait}: {actual_curie} (expected {expected_curie})")
    else:
        print(f"  ✗ {trait}: NOT FOUND")
print(f"  Total mappings: {len(mappings_madin)}")
