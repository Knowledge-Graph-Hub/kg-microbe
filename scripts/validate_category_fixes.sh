#!/bin/bash
# Validation script for category fixes implementation
# Run after ontologies transform completes

set -e

echo "================================================================================"
echo "Category Fixes Validation Report"
echo "================================================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ONTOLOGIES_DIR="data/transformed/ontologies"

echo "1. CHEBI: Macromolecule → MacromolecularComplex"
echo "--------------------------------------------------------------------------------"

# Count invalid Macromolecule categories
MACRO_COUNT=$(grep -c "biolink:Macromolecule" "$ONTOLOGIES_DIR/chebi_nodes.tsv" 2>/dev/null || echo "0")
# Count valid MacromolecularComplex categories
MACRO_COMPLEX_COUNT=$(grep -c "biolink:MacromolecularComplex" "$ONTOLOGIES_DIR/chebi_nodes.tsv" 2>/dev/null || echo "0")

echo "  Invalid biolink:Macromolecule: $MACRO_COUNT"
echo "  Valid biolink:MacromolecularComplex: $MACRO_COMPLEX_COUNT"

if [ "$MACRO_COUNT" -eq 0 ] && [ "$MACRO_COMPLEX_COUNT" -gt 4000 ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: Macromolecule successfully replaced"
else
    echo -e "  ${RED}✗ FAIL${NC}: Macromolecule still present or MacromolecularComplex missing"
fi

echo ""
echo "2. GO: RO/BFO Filtering"
echo "--------------------------------------------------------------------------------"

# Count RO/BFO terms in GO output
RO_BFO_COUNT=$(grep -cE "^(RO|BFO):" "$ONTOLOGIES_DIR/go_nodes.tsv" 2>/dev/null || echo "0")
GO_COUNT=$(grep -c "^GO:" "$ONTOLOGIES_DIR/go_nodes.tsv" 2>/dev/null || echo "0")

echo "  RO/BFO terms in GO output: $RO_BFO_COUNT"
echo "  GO terms in GO output: $GO_COUNT"

if [ "$RO_BFO_COUNT" -eq 0 ] && [ "$GO_COUNT" -gt 40000 ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: RO/BFO terms successfully filtered"
else
    echo -e "  ${RED}✗ FAIL${NC}: RO/BFO terms still present in GO output"
fi

echo ""
echo "3. METPO: Category Diversity"
echo "--------------------------------------------------------------------------------"

# Count METPO category distribution
echo "  METPO category distribution:"
cut -f2 "$ONTOLOGIES_DIR/metpo_nodes.tsv" 2>/dev/null | grep "^biolink:" | sort | uniq -c | while read count cat; do
    echo "    $cat: $count"
done

ONTOLOGY_CLASS_COUNT=$(grep "^METPO:" "$ONTOLOGIES_DIR/metpo_nodes.tsv" | grep "biolink:OntologyClass" | wc -l | tr -d ' ')
PHENOTYPIC_COUNT=$(grep "^METPO:" "$ONTOLOGIES_DIR/metpo_nodes.tsv" | grep "biolink:PhenotypicQuality" | wc -l | tr -d ' ')
TOTAL_METPO=$(grep -c "^METPO:" "$ONTOLOGIES_DIR/metpo_nodes.tsv" 2>/dev/null || echo "0")

PERCENTAGE=$((100 * ONTOLOGY_CLASS_COUNT / (TOTAL_METPO + 1)))

echo ""
echo "  OntologyClass: $ONTOLOGY_CLASS_COUNT / $TOTAL_METPO ($PERCENTAGE%)"
echo "  PhenotypicQuality: $PHENOTYPIC_COUNT"

if [ "$PHENOTYPIC_COUNT" -gt 100 ] && [ "$PERCENTAGE" -lt 50 ]; then
    echo -e "  ${GREEN}✓ PASS${NC}: METPO shows category diversity"
else
    echo -e "  ${YELLOW}⚠ WARNING${NC}: Most METPO terms still OntologyClass"
fi

echo ""
echo "4. ChEBI: Category Distribution"
echo "--------------------------------------------------------------------------------"

echo "  ChEBI category distribution (top 5):"
cut -f2 "$ONTOLOGIES_DIR/chebi_nodes.tsv" 2>/dev/null | grep "^biolink:" | sort | uniq -c | sort -rn | head -5 | while read count cat; do
    echo "    $cat: $count"
done

echo ""
echo "================================================================================"
echo "Validation Complete"
echo "================================================================================"
