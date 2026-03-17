#!/usr/bin/env python3
"""
Consolidate all chemical mapping files into a unified mapping resource.

Consolidates:
1. mappings/chemical_mappings.tsv - KEGG/BacDive to ChEBI
2. data/raw/compound_mappings_strict.tsv - MediaDive ingredients
3. data/raw/compound_mappings_strict_hydrate.tsv - Hydrated compounds
4. kg_microbe/transform_utils/bacdive/metabolite_mapping.json - BacDive metabolites
5. kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv - ChEBI xrefs
6. kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv - Manual annotations

Output: mappings/unified_chemical_mappings.tsv
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

import pandas as pd


def normalize_name(name: str) -> str:
    """Normalize chemical name for comparison."""
    if pd.isna(name) or not name:
        return ""
    # Convert to lowercase, remove extra spaces, punctuation
    normalized = str(name).lower().strip()
    normalized = re.sub(r'[^\w\s-]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


def extract_chebi_id(value: str) -> str:
    """Extract ChEBI ID from various formats."""
    if pd.isna(value) or not value:
        return ""
    value = str(value)
    if value.startswith("CHEBI:"):
        return value
    if value.startswith("chebi:"):
        return "CHEBI:" + value[6:]
    # Try to extract number
    match = re.search(r'(\d+)', value)
    if match:
        return f"CHEBI:{match.group(1)}"
    return ""


class ChemicalMappingConsolidator:
    """Consolidate chemical mappings from multiple sources."""

    def __init__(self):
        """Initialize consolidator."""
        self.chemicals: Dict[str, Dict] = {}  # chebi_id -> chemical data
        self.name_index: Dict[str, str] = {}  # normalized_name -> chebi_id
        self.formula_index: Dict[str, Set[str]] = defaultdict(set)  # formula -> set of chebi_ids
        self.chebi_adapter = None  # Will be initialized when needed

    def add_chemical(
        self,
        chebi_id: str,
        canonical_name: str = "",
        formula: str = "",
        synonyms: List[str] = None,
        xrefs: List[str] = None,
        source: str = "",
    ):
        """Add or update a chemical entry."""
        if not chebi_id or not chebi_id.startswith("CHEBI:"):
            return

        if chebi_id not in self.chemicals:
            self.chemicals[chebi_id] = {
                "chebi_id": chebi_id,
                "canonical_name": "",
                "formula": "",
                "synonyms": set(),
                "xrefs": set(),
                "sources": set(),
            }

        chem = self.chemicals[chebi_id]

        # Update canonical name (prefer non-empty, shorter names)
        if canonical_name and not pd.isna(canonical_name):
            canonical_name = str(canonical_name)
            if not chem["canonical_name"] or len(canonical_name) < len(chem["canonical_name"]):
                chem["canonical_name"] = canonical_name

        # Update formula (prefer non-empty)
        if formula and not pd.isna(formula) and not chem["formula"]:
            chem["formula"] = str(formula)

        # Add synonyms
        if synonyms:
            chem["synonyms"].update([s for s in synonyms if s])

        # Add xrefs
        if xrefs:
            chem["xrefs"].update([x for x in xrefs if x])

        # Track source
        if source:
            chem["sources"].add(source)

        # Update indices
        if canonical_name:
            norm_name = normalize_name(canonical_name)
            if norm_name and norm_name not in self.name_index:
                self.name_index[norm_name] = chebi_id

        if formula:
            self.formula_index[formula].add(chebi_id)

    def load_primary_mappings(self, filepath: Path):
        """Load mappings/chemical_mappings.tsv."""
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t")

        for _, row in df.iterrows():
            chebi_id = extract_chebi_id(row.get("chebi_id", ""))
            if not chebi_id:
                continue

            canonical_name = row.get("chebi_label", "")
            formula = row.get("chebi_formula", "")
            original_term = row.get("original_term", "")
            term_source = row.get("term_source", "")

            # Collect synonyms and xrefs
            synonyms = []
            xrefs = []

            if original_term and not pd.isna(original_term):
                original_term = str(original_term)
                # Check if it's an external reference
                if original_term.startswith("cpd:"):
                    xrefs.append(f"kegg.compound:{original_term}")
                else:
                    synonyms.append(original_term)

            self.add_chemical(
                chebi_id=chebi_id,
                canonical_name=canonical_name,
                formula=formula,
                synonyms=synonyms,
                xrefs=xrefs,
                source=f"primary_mappings[{term_source}]",
            )

        print(f"  Loaded {len(df)} entries")

    def load_compound_mappings(self, filepath: Path):
        """Load data/raw/compound_mappings_strict*.tsv."""
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t")

        for _, row in df.iterrows():
            # Try multiple ChEBI ID columns
            chebi_id = extract_chebi_id(row.get("chebi_id", "")) or extract_chebi_id(
                row.get("mapped", "")
            )
            if not chebi_id:
                # Try base_chebi_id
                chebi_id = extract_chebi_id(row.get("base_chebi_id", ""))
            if not chebi_id:
                continue

            canonical_name = row.get("chebi_label", "")
            formula = row.get("chebi_formula", "")
            original = row.get("original", "")
            base_compound = row.get("base_compound", "")

            synonyms = []
            if original:
                synonyms.append(original)
            if base_compound and base_compound != original:
                synonyms.append(base_compound)

            # Hydrate-specific data
            xrefs = []
            if "hydrate" in str(filepath):
                hydrated_chebi = extract_chebi_id(row.get("hydrated_chebi_id", ""))
                if hydrated_chebi and hydrated_chebi != chebi_id:
                    xrefs.append(f"CHEBI:{hydrated_chebi}")

            self.add_chemical(
                chebi_id=chebi_id,
                canonical_name=canonical_name,
                formula=formula,
                synonyms=synonyms,
                xrefs=xrefs,
                source="mediadive_compounds",
            )

        print(f"  Loaded {len(df)} entries")

    def load_metabolite_json(self, filepath: Path):
        """Load kg_microbe/transform_utils/bacdive/metabolite_mapping.json."""
        print(f"Loading {filepath}...")
        with open(filepath) as f:
            data = json.load(f)

        for chebi_id, name in data.items():
            chebi_id = extract_chebi_id(chebi_id)
            if not chebi_id:
                continue

            self.add_chemical(
                chebi_id=chebi_id,
                canonical_name=name,
                synonyms=[name],
                source="bacdive_metabolites",
            )

        print(f"  Loaded {len(data)} entries")

    def load_chebi_xrefs(self, filepath: Path):
        """Load kg_microbe/transform_utils/ontologies/xrefs/chebi_xrefs.tsv."""
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t")

        # Group by ChEBI ID
        grouped = df.groupby("id")["xref"].apply(list).to_dict()

        for chebi_id, xref_list in grouped.items():
            chebi_id = extract_chebi_id(chebi_id)
            if not chebi_id:
                continue

            self.add_chemical(
                chebi_id=chebi_id, xrefs=xref_list, source="chebi_xrefs"
            )

        print(f"  Loaded {len(grouped)} ChEBI IDs with xrefs")

    def load_manual_annotations(self, filepath: Path):
        """Load kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv."""
        print(f"Loading {filepath}...")
        df = pd.read_csv(filepath, sep="\t")

        for _, row in df.iterrows():
            chebi_id = extract_chebi_id(row.get("object_id", ""))
            if not chebi_id:
                continue

            canonical_name = row.get("object_label", "")
            traits_term = row.get("traits_dataset_term", "")
            action = row.get("action", "")

            synonyms = []
            if traits_term:
                synonyms.append(traits_term)

            self.add_chemical(
                chebi_id=chebi_id,
                canonical_name=canonical_name,
                synonyms=synonyms,
                source=f"manual_annotation[{action}]",
            )

        print(f"  Loaded {len(df)} entries")

    def _get_chebi_adapter(self):
        """Get or create ChEBI adapter."""
        if self.chebi_adapter is None:
            try:
                from oaklib import get_adapter
                from kg_microbe.transform_utils.constants import CHEBI_SOURCE
                self.chebi_adapter = get_adapter(f"sqlite:{CHEBI_SOURCE}")
                print("  Initialized ChEBI adapter")
            except Exception as e:
                print(f"  Warning: Could not initialize ChEBI adapter: {e}")
                print("  ChEBI synonyms will not be added")
        return self.chebi_adapter

    def enrich_with_chebi_synonyms(self):
        """Add ChEBI ontology synonyms to each chemical."""
        print("\nEnriching with ChEBI synonyms...")
        adapter = self._get_chebi_adapter()

        if not adapter:
            print("  Skipped - ChEBI adapter not available")
            return

        enriched_count = 0
        synonym_count = 0

        for chebi_id, chem in self.chemicals.items():
            try:
                # Get ChEBI label
                label = adapter.label(chebi_id)
                if label and not chem["canonical_name"]:
                    chem["canonical_name"] = label

                # Get synonyms from ChEBI
                synonyms = list(adapter.entity_aliases(chebi_id))
                if synonyms:
                    # Filter out None values
                    valid_synonyms = [s for s in synonyms if s is not None]
                    chem["synonyms"].update(valid_synonyms)
                    synonym_count += len(valid_synonyms)
                    enriched_count += 1

            except Exception as e:
                # Skip entries that don't exist in ChEBI
                pass

        print(f"  Enriched {enriched_count} chemicals with {synonym_count} ChEBI synonyms")

    def merge_duplicates_by_name(self):
        """Merge chemicals with same normalized name but different ChEBI IDs."""
        print("\nMerging duplicates by name...")
        # Find duplicates
        name_to_ids = defaultdict(set)
        for chebi_id, chem in self.chemicals.items():
            if chem["canonical_name"]:
                norm_name = normalize_name(chem["canonical_name"])
                if norm_name:
                    name_to_ids[norm_name].add(chebi_id)

        merged_count = 0
        for norm_name, chebi_ids in name_to_ids.items():
            if len(chebi_ids) > 1:
                # Keep the one with lowest ChEBI ID (usually more established)
                sorted_ids = sorted(chebi_ids, key=lambda x: int(x.split(":")[1]))
                primary_id = sorted_ids[0]

                # Merge others into primary
                for other_id in sorted_ids[1:]:
                    primary = self.chemicals[primary_id]
                    other = self.chemicals[other_id]

                    # Merge synonyms, xrefs, sources
                    primary["synonyms"].update(other["synonyms"])
                    primary["xrefs"].update(other["xrefs"])
                    primary["sources"].update(other["sources"])

                    # Add other ChEBI ID as xref
                    primary["xrefs"].add(other_id)

                    merged_count += 1

        print(f"  Merged {merged_count} duplicate entries")

    def export_unified_mapping(self, output_path: Path):
        """Export unified mapping to TSV."""
        print(f"\nExporting unified mapping to {output_path}...")

        records = []
        for chebi_id in sorted(self.chemicals.keys(), key=lambda x: int(x.split(":")[1])):
            chem = self.chemicals[chebi_id]

            # Sort and join synonyms (filter out None values)
            synonyms_list = sorted([s for s in chem["synonyms"] if s is not None])
            synonyms_str = "|".join(synonyms_list) if synonyms_list else ""

            # Sort and join xrefs
            xrefs_list = sorted(chem["xrefs"])
            xrefs_str = "|".join(xrefs_list) if xrefs_list else ""

            # Sort and join sources
            sources_list = sorted(chem["sources"])
            sources_str = "|".join(sources_list) if sources_list else ""

            records.append(
                {
                    "chebi_id": chebi_id,
                    "canonical_name": chem["canonical_name"],
                    "formula": chem["formula"],
                    "synonyms": synonyms_str,
                    "xrefs": xrefs_str,
                    "sources": sources_str,
                }
            )

        df = pd.DataFrame(records)
        df.to_csv(output_path, sep="\t", index=False)

        print(f"  Exported {len(records)} unique chemicals")
        print(f"  Total synonyms: {sum(len(r['synonyms'].split('|')) for r in records if r['synonyms'])}")
        print(f"  Total xrefs: {sum(len(r['xrefs'].split('|')) for r in records if r['xrefs'])}")


def main():
    """Main consolidation workflow."""
    base_dir = Path(__file__).parent.parent
    consolidator = ChemicalMappingConsolidator()

    # Load all mapping sources
    consolidator.load_primary_mappings(base_dir / "mappings" / "chemical_mappings.tsv")
    consolidator.load_compound_mappings(base_dir / "data" / "raw" / "compound_mappings_strict.tsv")
    consolidator.load_compound_mappings(
        base_dir / "data" / "raw" / "compound_mappings_strict_hydrate.tsv"
    )
    consolidator.load_metabolite_json(
        base_dir / "kg_microbe" / "transform_utils" / "bacdive" / "metabolite_mapping.json"
    )
    consolidator.load_chebi_xrefs(
        base_dir / "kg_microbe" / "transform_utils" / "ontologies" / "xrefs" / "chebi_xrefs.tsv"
    )
    consolidator.load_manual_annotations(
        base_dir / "kg_microbe" / "transform_utils" / "madin_etal" / "chebi_manual_annotation.tsv"
    )

    # Enrich with ChEBI synonyms
    consolidator.enrich_with_chebi_synonyms()

    # Merge duplicates
    consolidator.merge_duplicates_by_name()

    # Export unified mapping
    output_path = base_dir / "mappings" / "unified_chemical_mappings.tsv"
    consolidator.export_unified_mapping(output_path)

    print(f"\n✓ Unified chemical mapping created: {output_path}")


if __name__ == "__main__":
    main()
