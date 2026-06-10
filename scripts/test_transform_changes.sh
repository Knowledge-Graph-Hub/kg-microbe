#!/bin/bash
# Test script for validating KG-Microbe transform changes (202512-release-fixes branch)
# Usage: ./scripts/test_transform_changes.sh [path_to_merged_kg_directory]
#
# This script validates:
# - Pigment production edges using METPO:2000202
# - Rhea mappings filter (no TrEMBL/UniProt nodes)
# - METPO predicate usage
# - Summary statistics

set -e

# Check if directory argument is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <path_to_merged_kg_directory>"
    echo "Example: $0 data/merged/"
    echo "         $0 20251217/"
    exit 1
fi

KG_DIR="$1"
NODES="${KG_DIR}/merged-kg_nodes.tsv"
EDGES="${KG_DIR}/merged-kg_edges.tsv"

# Check if files exist
if [ ! -f "$NODES" ]; then
    echo "Error: Nodes file not found: $NODES"
    exit 1
fi

if [ ! -f "$EDGES" ]; then
    echo "Error: Edges file not found: $EDGES"
    exit 1
fi

echo "Testing KG transform changes..."
echo "Nodes file: $NODES"
echo "Edges file: $EDGES"
echo "================================"
echo

# ============================================================================
# 1. Test Pigment Production (METPO:2000202)
# ============================================================================
echo "=== 1. PIGMENT PRODUCTION TESTS ==="
echo

echo "Sample pigment production edges (first 20):"
grep -E "pigment:" "$EDGES" | head -20 || echo "No pigment edges found"
echo

echo "Total METPO:2000202 (produces) edges:"
grep -c "METPO:2000202" "$EDGES" || echo "0"
echo

echo "Pigment nodes:"
grep -E "pigment:" "$NODES" || echo "No pigment nodes found"
echo
echo

# ============================================================================
# 2. Test Rhea Mappings Filter (No TrEMBL/UniProt)
# ============================================================================
echo "=== 2. RHEA MAPPINGS FILTER TESTS ==="
echo

echo "Checking for TrEMBL/UniProt in Rhea edges (should be NONE):"
RHEA_UNIPROT_COUNT=$(grep -E "UniProtKB|TrEMBL" "$EDGES" | grep -i rhea | wc -l || echo "0")
if [ "$RHEA_UNIPROT_COUNT" -eq 0 ]; then
    echo "✓ PASS: No TrEMBL/UniProt nodes found in Rhea edges"
else
    echo "✗ FAIL: Found $RHEA_UNIPROT_COUNT TrEMBL/UniProt entries in Rhea edges"
    grep -E "UniProtKB|TrEMBL" "$EDGES" | grep -i rhea | head -10
fi
echo

echo "Sample Rhea edges (first 20):"
grep "infores:rhea" "$EDGES" | head -20 || echo "No Rhea edges found"
echo

echo "Total Rhea-sourced edges:"
grep -c "infores:rhea" "$EDGES" || echo "0"
echo
echo

# ============================================================================
# 3. Test METPO Predicate Usage
# ============================================================================
echo "=== 3. METPO PREDICATE USAGE ==="
echo

echo "METPO predicate distribution (sorted by count):"
grep -oE "METPO:[0-9]+" "$EDGES" | sort | uniq -c | sort -rn || echo "No METPO predicates found"
echo

echo "Sample METPO:2000202 (produces) edges - Subject → Object (first 20):"
grep "METPO:2000202" "$EDGES" | cut -f1,3 | head -20 || echo "No METPO:2000202 edges found"
echo

echo "Total ChemicalSubstance nodes:"
grep -c "biolink:ChemicalSubstance" "$NODES" || echo "0"
echo
echo

# ============================================================================
# 4. Summary Statistics
# ============================================================================
echo "=== 4. SUMMARY STATISTICS ==="
echo

echo "Total counts:"
wc -l "$NODES" "$EDGES"
echo

echo "Top 20 node categories:"
cut -f2 "$NODES" | sort | uniq -c | sort -rn | head -20
echo

echo "Top 20 edge predicates:"
cut -f2 "$EDGES" | sort | uniq -c | sort -rn | head -20
echo

echo "================================"
echo "Testing complete!"
