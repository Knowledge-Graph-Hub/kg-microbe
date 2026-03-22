#!/usr/bin/env bash
#
# Cleanup script for old chemical mapping files after migration to unified mappings
#
# This script removes obsolete mapping files that have been replaced by
# mappings/unified_chemical_mappings.tsv.gz
#
# Run this AFTER verifying that all transforms work correctly with the unified mappings.
#

set -e  # Exit on error

echo "Chemical Mapping Cleanup Script"
echo "================================"
echo ""
echo "This will remove old mapping files that have been replaced by:"
echo "  mappings/unified_chemical_mappings.tsv.gz"
echo ""

# List files to be removed
echo "Files to be removed:"
echo "  1. data/raw/compound_mappings_strict.tsv (MediaDive)"
echo "  2. data/raw/compound_mappings_strict_hydrate.tsv (MediaDive)"
echo "  3. kg_microbe/transform_utils/bacdive/metabolite_mapping.json (BacDive)"
echo "  4. kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv (CTD/Ontologies)"
echo ""

# Confirm with user
read -p "Proceed with removal? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Removing files..."

# MediaDive compound mappings
if [ -f "data/raw/compound_mappings_strict.tsv" ]; then
    echo "  Removing data/raw/compound_mappings_strict.tsv"
    rm "data/raw/compound_mappings_strict.tsv"
else
    echo "  (data/raw/compound_mappings_strict.tsv not found - already removed?)"
fi

if [ -f "data/raw/compound_mappings_strict_hydrate.tsv" ]; then
    echo "  Removing data/raw/compound_mappings_strict_hydrate.tsv"
    rm "data/raw/compound_mappings_strict_hydrate.tsv"
else
    echo "  (data/raw/compound_mappings_strict_hydrate.tsv not found - already removed?)"
fi

# BacDive metabolite mapping
if [ -f "kg_microbe/transform_utils/bacdive/metabolite_mapping.json" ]; then
    echo "  Removing kg_microbe/transform_utils/bacdive/metabolite_mapping.json"
    rm "kg_microbe/transform_utils/bacdive/metabolite_mapping.json"
else
    echo "  (kg_microbe/transform_utils/bacdive/metabolite_mapping.json not found - already removed?)"
fi

# ChEBI xrefs (generated file)
if [ -f "kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv" ]; then
    echo "  Removing kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv"
    rm "kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv"
else
    echo "  (kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv not found - already removed?)"
fi

echo ""
echo "Cleanup complete!"
echo ""
echo "KEEP these files:"
echo "  - mappings/unified_chemical_mappings.tsv.gz (consolidated mappings)"
echo "  - scripts/consolidate_chemical_mappings.py (regenerates unified file)"
echo ""
echo "All transforms now use kg_microbe.utils.chemical_mapping_utils.ChemicalMappingLoader"
