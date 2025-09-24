#!/usr/bin/env python3
"""
Combine chemical mapping files into a unified chemical_mappings.tsv file.
"""

import pandas as pd
import json
import re
from pathlib import Path
import difflib


def normalize_chebi_id(chebi_id):
    """Normalize CHEBI ID format to CHEBI:XXXXXX"""
    if not chebi_id or pd.isna(chebi_id):
        return None
    
    chebi_str = str(chebi_id).strip()
    
    # Handle different formats
    if chebi_str.startswith('CHEBI:'):
        return chebi_str
    elif chebi_str.startswith('chebi:'):
        return 'CHEBI:' + chebi_str[6:]
    elif chebi_str.isdigit():
        return f'CHEBI:{chebi_str}'
    else:
        # Try to extract number from string
        match = re.search(r'(\d+)', chebi_str)
        if match:
            return f'CHEBI:{match.group(1)}'
    
    return None



def process_chemicals_sssom(file_path):
    """Process chemicals SSSOM mappings"""
    # Skip header comments
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    # Find the start of actual data
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith('subject_id\t'):
            start_idx = i
            break
    
    # Read the TSV data
    df = pd.read_csv(file_path, sep='\t', skiprows=start_idx)
    
    mappings = []
    for _, row in df.iterrows():
        chebi_id = normalize_chebi_id(row['object_id'])
        if chebi_id:
            # Extract original term from subject_label
            original_term = str(row['subject_label']).strip().strip('"\'')
            
            mappings.append({
                'original_term': original_term,
                'term_source': 'chemicals_sssom',
                'chebi_id': chebi_id,
                'chebi_label': row.get('object_label'),
                'chebi_formula': None,
                'mapping_quality': 'medium' if row.get('confidence', 0) < 0.8 else 'high'
            })
    
    return pd.DataFrame(mappings)


def process_kegg_chebi(file_path):
    """Process KEGG-CHEBI mappings"""
    df = pd.read_csv(file_path, sep='\t', header=None, names=['kegg_id', 'chebi_id'])
    
    mappings = []
    for _, row in df.iterrows():
        chebi_id = normalize_chebi_id(row['chebi_id'])
        if chebi_id:
            mappings.append({
                'original_term': row['kegg_id'],
                'term_source': 'kegg_compound',
                'chebi_id': chebi_id,
                'chebi_label': None,
                'chebi_formula': None,
                'mapping_quality': 'high'
            })
    
    return pd.DataFrame(mappings)


def process_metabolite_mapping_json(file_path):
    """Process BacDive metabolite mapping JSON"""
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    mappings = []
    for chebi_id, term in data.items():
        normalized_chebi = normalize_chebi_id(chebi_id)
        if normalized_chebi:
            mappings.append({
                'original_term': term,
                'term_source': 'bacdive_metabolite',
                'chebi_id': normalized_chebi,
                'chebi_label': None,
                'chebi_formula': None,
                'mapping_quality': 'high'
            })
    
    return pd.DataFrame(mappings)


def process_chebi_manual_annotation(file_path):
    """Process manual CHEBI annotations"""
    df = pd.read_csv(file_path, sep='\t')
    
    mappings = []
    for _, row in df.iterrows():
        chebi_id = normalize_chebi_id(row['object_id'])
        if chebi_id:
            mappings.append({
                'original_term': row['traits_dataset_term'],
                'term_source': 'madin_etal_manual',
                'chebi_id': chebi_id,
                'chebi_label': row.get('object_label'),
                'chebi_formula': None,
                'mapping_quality': 'high'
            })
    
    return pd.DataFrame(mappings)


def process_bacdive_mappings(file_path):
    """Process BacDive API mappings"""
    df = pd.read_csv(file_path, sep='\t')
    
    mappings = []
    for _, row in df.iterrows():
        chebi_id = normalize_chebi_id(row['CHEBI_ID'])
        if chebi_id and pd.notna(row['substrate']):
            mappings.append({
                'original_term': row['substrate'],
                'term_source': 'bacdive_api',
                'chebi_id': chebi_id,
                'chebi_label': None,
                'chebi_formula': None,
                'mapping_quality': 'high'
            })
    
    return pd.DataFrame(mappings)


def load_chebi_labels(file_path):
    """Load CHEBI labels from chebi_nodes.tsv"""
    print("Loading CHEBI labels...")
    df = pd.read_csv(file_path, sep='\t')
    
    # Create mapping from CHEBI ID to name
    chebi_labels = {}
    for _, row in df.iterrows():
        if pd.notna(row['name']) and row['name'].strip():
            chebi_labels[row['id']] = row['name']
    
    print(f"  Loaded {len(chebi_labels)} CHEBI labels")
    return chebi_labels


def normalize_for_comparison(text):
    """Normalize text for comparison by removing special chars, lowercasing, etc."""
    if pd.isna(text) or not text:
        return ""
    
    # Convert to string and lowercase
    text = str(text).lower().strip()
    
    # Remove common prefixes/suffixes and special characters
    text = re.sub(r'^(l-|d-|dl-|n-|o-|p-|m-|alpha-|beta-|gamma-|delta-)', '', text)
    text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation
    text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
    text = text.strip()
    
    return text


def is_known_trade_name_mapping(original_term, chebi_label):
    """Check if this is a known valid trade name to chemical name mapping"""
    original_lower = str(original_term).lower().strip()
    chebi_lower = str(chebi_label).lower().strip()
    
    # Known trade name mappings
    trade_name_mappings = {
        'tween 20': 'polysorbate 20',
        'tween 40': 'polysorbate 40', 
        'tween 60': 'polysorbate 60',
        'tween 80': 'polysorbate 80',
        'niaproof': 'sodium tetradecyl sulfate',
        'tergitol': 'nonylphenol ethoxylate',
        'triton': 'octylphenol ethoxylate',
        'brij': 'polyoxyethylene',
        'span': 'sorbitan',
        'tergitol np-10': '4-nonylphenyl-polyethylene glycol',
        'triton x-100': '4-octylphenol polyethoxylate'
    }
    
    # Check if original term matches a trade name and CHEBI matches the chemical
    for trade_name, chemical_name in trade_name_mappings.items():
        if trade_name in original_lower and chemical_name in chebi_lower:
            return True
    
    return False


def is_valid_synonym_mapping(original_term, chebi_label):
    """Check for valid synonym mappings (common name vs systematic name)"""
    original_lower = str(original_term).lower().strip()
    chebi_lower = str(chebi_label).lower().strip()
    
    # Known synonym mappings
    synonym_mappings = {
        'adonitol': 'ribitol',
        'sorbitol': 'glucitol', 
        'malate': 'malic acid',
        'putrescine': 'butanediamine',
        'alpha-ketovaleric acid': '2-oxopentanoic acid',
        'pyruvic acid methyl ester': 'methyl pyruvate',
        '2-aminethanol': 'ethanolamine',
        'd-trehalose': 'alpha,alpha-trehalose',
        'trehalose': 'alpha,alpha-trehalose',
        '5-ketogluconate': '5-dehydro-d-gluconic acid',
        '5-dehydro-d-gluconate': '5-dehydro-d-gluconic acid',
        'vibriostat': '2,4-diamino-6,7-diisopropylpteridine'
    }
    
    # Check direct synonyms
    for common_name, systematic_name in synonym_mappings.items():
        if common_name in original_lower and systematic_name in chebi_lower:
            return True
    
    return False


def is_acceptable_broader_mapping(original_term, chebi_label):
    """Check for mappings that are broader but still acceptable"""
    original_lower = str(original_term).lower().strip()
    chebi_lower = str(chebi_label).lower().strip()
    
    # Cases where broader mapping is acceptable for biological contexts
    broader_mappings = {
        'antibiotic_compound': 'antibacterial drug',
        'antibiotic compound': 'antibacterial drug',
        'pigmented': 'biological pigment',
        'adipate': 'adipic acid'  # Close enough for many biological contexts
    }
    
    for specific_term, broader_term in broader_mappings.items():
        if specific_term in original_lower and broader_term in chebi_lower:
            return True
    
    return False


def handle_mixture_mappings(original_term, chebi_labels_dict):
    """Handle mixture terms by splitting and mapping individual components"""
    original_lower = str(original_term).lower().strip()
    
    # Handle underscore-separated mixtures
    if '_' in original_term:
        components = original_term.split('_')
        mappings = []
        
        for component in components:
            component = component.strip()
            if not component:
                continue
                
            # Map common component abbreviations to CHEBI IDs
            component_mappings = {
                'h2': 'CHEBI:18276',  # dihydrogen
                'co2': 'CHEBI:16526',  # carbon dioxide
                'methanol': 'CHEBI:17790'  # methanol
            }
            
            component_lower = component.lower()
            if component_lower in component_mappings:
                chebi_id = component_mappings[component_lower]
                chebi_label = chebi_labels_dict.get(chebi_id, '')
                mappings.append({
                    'original_term': component,
                    'chebi_id': chebi_id,
                    'chebi_label': chebi_label
                })
        
        return mappings
    
    return []


def apply_manual_corrections(original_term, chebi_id):
    """Apply manual corrections for specific problematic mappings"""
    corrections = {
        # putrescine: correct to neutral form CHEBI:17148
        ('putrescine', 'CHEBI:326268'): 'CHEBI:17148'
    }
    
    key = (str(original_term).lower().strip(), str(chebi_id).strip())
    return corrections.get(key, chebi_id)


def terms_match(original_term, chebi_label, similarity_threshold=0.6):
    """Check if original term and CHEBI label are similar enough"""
    if pd.isna(original_term) or pd.isna(chebi_label):
        return True  # Skip comparison if either is missing
    
    # Skip ID-based terms (like cpd:C12345, CAS numbers, etc.)
    if re.match(r'^(cpd:|cas-rn:|kegg:|c\d+)', str(original_term).lower()):
        return True
    
    # Handle exact matches for simple chemical names (H2, CO2, etc.)
    original_clean = str(original_term).strip().lower()
    chebi_clean = str(chebi_label).strip().lower()
    
    if original_clean == chebi_clean:
        return True
    
    # Special cases for simple chemicals
    simple_matches = {
        'h2': 'dihydrogen',
        'co2': 'carbon dioxide', 
        'methanol': 'methanol'
    }
    
    if original_clean in simple_matches and simple_matches[original_clean] in chebi_clean:
        return True
    
    # Check for known valid trade name mappings
    if is_known_trade_name_mapping(original_term, chebi_label):
        return True
    
    # Check for known valid synonym mappings  
    if is_valid_synonym_mapping(original_term, chebi_label):
        return True
    
    # Check for acceptable broader mappings
    if is_acceptable_broader_mapping(original_term, chebi_label):
        return True
    
    norm_original = normalize_for_comparison(original_term)
    norm_chebi = normalize_for_comparison(chebi_label)
    
    if not norm_original or not norm_chebi:
        return True
    
    # Exact match after normalization
    if norm_original == norm_chebi:
        return True
    
    # Check if one is contained in the other
    if norm_original in norm_chebi or norm_chebi in norm_original:
        return True
    
    # Use sequence similarity
    similarity = difflib.SequenceMatcher(None, norm_original, norm_chebi).ratio()
    return similarity >= similarity_threshold


def create_mismatch_report(df, output_dir):
    """Create a report of term/label mismatches"""
    mismatches = []
    
    for _, row in df.iterrows():
        if pd.notna(row['chebi_label']):
            if not terms_match(row['original_term'], row['chebi_label']):
                mismatches.append({
                    'original_term': row['original_term'],
                    'term_source': row['term_source'],
                    'chebi_id': row['chebi_id'],
                    'chebi_label': row['chebi_label'],
                    'mapping_quality': row['mapping_quality'],
                    'normalized_original': normalize_for_comparison(row['original_term']),
                    'normalized_chebi': normalize_for_comparison(row['chebi_label'])
                })
    
    if mismatches:
        mismatch_df = pd.DataFrame(mismatches)
        report_path = output_dir / 'chemical_mappings_mismatches.tsv'
        mismatch_df.to_csv(report_path, sep='\t', index=False)
        print(f"  Created mismatch report: {report_path}")
        print(f"  Found {len(mismatches)} potential mismatches")
        
        # Show some examples
        print("  Example mismatches:")
        for i, mismatch in enumerate(mismatches[:5]):
            print(f"    {mismatch['original_term']} -> {mismatch['chebi_label']} ({mismatch['chebi_id']})")
        
        return mismatch_df
    else:
        print("  No mismatches found")
        return pd.DataFrame()


def main():
    """Main function to combine all mapping files"""
    base_path = Path('/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe')
    
    # File paths (excluding chebi_xrefs.tsv as requested)
    files = {
        'chemicals_sssom': base_path / 'schemas/chemicals.sssom.tsv',
        'kegg_chebi': base_path / 'data/raw_last_local/PRE_20240627/kegg-cpd-chebi.tsv',
        'metabolite_json': base_path / 'kg_microbe/transform_utils/bacdive/metabolite_mapping.json',
        'manual_annotation': base_path / 'kg_microbe/transform_utils/madin_etal/chebi_manual_annotation.tsv',
        'bacdive_mappings': base_path / 'kg_microbe/transform_utils/bacdive/tmp/bacdive_mappings.tsv',
        'chebi_nodes': base_path / 'data/transformed/ontologies/chebi_nodes.tsv'
    }
    
    # Load CHEBI labels
    chebi_labels = {}
    if files['chebi_nodes'].exists():
        chebi_labels = load_chebi_labels(files['chebi_nodes'])
    else:
        print("Warning: chebi_nodes.tsv not found, labels will be empty")
    
    all_mappings = []
    
    print("Processing chemicals SSSOM...")
    if files['chemicals_sssom'].exists():
        df = process_chemicals_sssom(files['chemicals_sssom'])
        all_mappings.append(df)
        print(f"  Added {len(df)} mappings from chemicals SSSOM")
    
    print("Processing KEGG-CHEBI mappings...")
    if files['kegg_chebi'].exists():
        df = process_kegg_chebi(files['kegg_chebi'])
        all_mappings.append(df)
        print(f"  Added {len(df)} mappings from KEGG-CHEBI")
    
    print("Processing BacDive metabolite JSON...")
    if files['metabolite_json'].exists():
        df = process_metabolite_mapping_json(files['metabolite_json'])
        all_mappings.append(df)
        print(f"  Added {len(df)} mappings from BacDive metabolite JSON")
    
    print("Processing manual annotations...")
    if files['manual_annotation'].exists():
        df = process_chebi_manual_annotation(files['manual_annotation'])
        all_mappings.append(df)
        print(f"  Added {len(df)} mappings from manual annotations")
    
    print("Processing BacDive API mappings...")
    if files['bacdive_mappings'].exists():
        df = process_bacdive_mappings(files['bacdive_mappings'])
        all_mappings.append(df)
        print(f"  Added {len(df)} mappings from BacDive API")
    
    # Combine all mappings
    if all_mappings:
        combined_df = pd.concat(all_mappings, ignore_index=True)
        
        # Apply manual corrections
        print("Applying manual corrections...")
        combined_df['chebi_id'] = combined_df.apply(
            lambda row: apply_manual_corrections(row['original_term'], row['chebi_id']), 
            axis=1
        )
        
        # Handle mixture mappings (split H2_CO2, H2_methanol, etc.)
        print("Processing mixture mappings...")
        mixture_mappings = []
        rows_to_remove = []
        
        for idx, row in combined_df.iterrows():
            if '_' in str(row['original_term']) and any(x in str(row['original_term']).lower() for x in ['h2_', '_co2', '_methanol']):
                # This is a mixture term, split it
                mixture_maps = handle_mixture_mappings(row['original_term'], chebi_labels)
                for mapping in mixture_maps:
                    new_row = row.copy()
                    new_row['original_term'] = mapping['original_term']
                    new_row['chebi_id'] = mapping['chebi_id']
                    new_row['chebi_label'] = mapping['chebi_label']
                    mixture_mappings.append(new_row)
                rows_to_remove.append(idx)
        
        # Remove original mixture rows and add split mappings
        if rows_to_remove:
            combined_df = combined_df.drop(rows_to_remove)
            if mixture_mappings:
                mixture_df = pd.DataFrame(mixture_mappings)
                combined_df = pd.concat([combined_df, mixture_df], ignore_index=True)
                print(f"  Split {len(rows_to_remove)} mixture terms into {len(mixture_mappings)} individual mappings")
        
        # Add CHEBI labels
        print("Adding CHEBI labels...")
        combined_df['chebi_label'] = combined_df['chebi_id'].map(chebi_labels)
        
        # Remove duplicates (same original_term, term_source, chebi_id)
        combined_df = combined_df.drop_duplicates(
            subset=['original_term', 'term_source', 'chebi_id'], 
            keep='first'
        )
        
        # Create mismatch report and filter out mismatches
        print("Checking for term/label mismatches...")
        output_dir = base_path / 'mappings'
        mismatch_df = create_mismatch_report(combined_df, output_dir)
        
        # Filter out mismatches from the final output
        if not mismatch_df.empty:
            # Create a set of (original_term, chebi_id) tuples to exclude
            mismatch_keys = set(zip(mismatch_df['original_term'], mismatch_df['chebi_id']))
            print(f"  Mismatch keys to filter: {list(mismatch_keys)[:5]}...")  # Debug
            
            # Filter the combined_df - more robust filtering
            before_count = len(combined_df)
            
            # Create a mask for rows to keep
            mask = combined_df.apply(
                lambda row: (row['original_term'], row['chebi_id']) not in mismatch_keys,
                axis=1
            )
            combined_df = combined_df[mask]
            
            after_count = len(combined_df)
            print(f"  Filtered out {before_count - after_count} mismatched mappings")
            
            # Double-check: verify no mismatches remain
            remaining_keys = set(zip(combined_df['original_term'], combined_df['chebi_id']))
            overlap = mismatch_keys.intersection(remaining_keys)
            if overlap:
                print(f"  WARNING: {len(overlap)} mismatches still present: {list(overlap)[:3]}...")
            else:
                print(f"  ✓ All mismatches successfully removed")
        
        # Sort by CHEBI ID and original term
        combined_df = combined_df.sort_values(['chebi_id', 'original_term'])
        
        # Save to output file
        output_path = base_path / 'mappings/chemical_mappings.tsv'
        combined_df.to_csv(output_path, sep='\t', index=False)
        
        print(f"\nCombined {len(combined_df)} unique mappings")
        print(f"Output saved to: {output_path}")
        
        # Print summary statistics
        print("\nSummary by source:")
        print(combined_df['term_source'].value_counts())
        
        print("\nSummary by mapping quality:")
        print(combined_df['mapping_quality'].value_counts())
        
        print(f"\nUnique CHEBI IDs: {combined_df['chebi_id'].nunique()}")
        print(f"Unique original terms: {combined_df['original_term'].nunique()}")
    
    else:
        print("No mapping files found!")


if __name__ == '__main__':
    main()