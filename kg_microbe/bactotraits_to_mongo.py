#!/usr/bin/env python3

import csv
import json
import argparse
import re
from typing import List, Dict, Any

def clean_field_name(name: str) -> str:
    """Convert field name to MongoDB-compatible format"""
    # Remove special characters and normalize
    cleaned = re.sub(r'[^\w\s]', '_', name)
    cleaned = re.sub(r'\s+', '_', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned)
    cleaned = cleaned.strip('_').lower()
    return cleaned

def forward_fill_headers(header_row: List[str]) -> List[str]:
    """Forward fill empty cells in header row"""
    filled = []
    last_value = ""
    
    for cell in header_row:
        cell = cell.strip()
        if cell:
            last_value = cell
        filled.append(last_value)
    
    return filled

def create_field_path(category: str, field_name: str) -> str:
    """Create hierarchical field path from category and field name"""
    # Clean both parts
    category_clean = clean_field_name(category) if category else ""
    field_clean = clean_field_name(field_name.strip())  # Remove leading/trailing spaces
    
    # Handle special naming patterns
    # Check for strain number field directly (handles encoding issues)
    if "strain_n" in field_name.lower() or field_name.strip().startswith("strain n"):
        return "strain_number"
    
    if category_clean == "strain_name":
        return "strain.name"
    
    if category_clean == "taxonomy":
        return f"taxonomy.{field_clean}"
    
    # Handle pH patterns
    if "ph" in category_clean:
        # Convert pHO_0_to_6 -> 0_to_6
        if field_clean.startswith("pho_"):
            range_part = field_clean[4:]  # Remove "pho_"
            return f"ph.optimum.{range_part}"
        elif field_clean.startswith("phr_"):
            range_part = field_clean[4:]  # Remove "phr_"
            return f"ph.range.{range_part}"
        elif field_clean.startswith("phd_"):
            range_part = field_clean[4:]  # Remove "phd_"
            return f"ph.delta.{range_part}"
    
    # Handle NaCl patterns
    if "nacl" in category_clean:
        if field_clean.startswith("nao_"):
            range_part = field_clean[4:]
            return f"nacl.optimum.{range_part}"
        elif field_clean.startswith("nar_"):
            range_part = field_clean[4:]
            return f"nacl.range.{range_part}"
        elif field_clean.startswith("nad_"):
            range_part = field_clean[4:]
            return f"nacl.delta.{range_part}"
    
    # Handle temperature patterns
    if "temp" in category_clean:
        if field_clean.startswith("to_"):
            range_part = field_clean[3:]
            return f"temperature.optimum.{range_part}"
        elif field_clean.startswith("tr_"):
            range_part = field_clean[3:]
            return f"temperature.range.{range_part}"
        elif field_clean.startswith("td_"):
            range_part = field_clean[3:]
            return f"temperature.delta.{range_part}"
    
    # Handle Oxygen
    if category_clean == "oxygen":
        if field_clean.startswith("ox_"):
            trait = field_clean[3:]
            return f"oxygen.{trait}"
    
    # Handle Gram staining
    if category_clean == "gram":
        if field_clean.startswith("g_"):
            trait = field_clean[2:]
            return f"gram_stain.{trait}"
    
    # Handle Motility
    if category_clean == "motility":
        if field_clean == "non_motile":
            return "motility.non_motile"
        elif field_clean == "motile":
            return "motility.motile"
    
    # Handle Spore formation
    if category_clean == "spore":
        if field_clean == "no_spore":
            return "spore_formation.no_spore"
        elif field_clean == "spore":
            return "spore_formation.spore_forming"
    
    # Handle GC content - preserve original range names with better formatting
    if "gc" in category_clean or field_clean.startswith("gc_"):
        # Extract the range part from field name - preserve the original format
        if field_clean.startswith("gc_"):
            range_part = field_name.strip()[3:]  # Use original field name, remove "GC_" prefix
        else:
            range_part = field_name.strip()  # Use original field name as-is
        
        # Replace comparison operators for MongoDB 
        range_clean = range_part.replace('<=', 'lte_').replace('>=', 'gte_').replace('>', 'gt_').replace('<', 'lt_')
        # Replace underscores between numbers with "to" to indicate ranges
        range_clean = re.sub(r'(\d+\.\d+)_(\d+\.\d+)', r'\1_to_\2', range_clean)
        # Replace periods with "dot" to avoid MongoDB nesting issues
        range_clean = range_clean.replace('.', 'dot')
        return f"gc_content.{range_clean}"
    
    # Handle width/length
    if category_clean == "width":
        if field_clean.startswith("w_"):
            range_part = field_clean[2:]
            return f"cell_width.{range_part}"
    
    if category_clean == "length":
        if field_clean.startswith("l_"):
            range_part = field_clean[2:]
            return f"cell_length.{range_part}"
    
    # Handle shape
    if category_clean == "shape":
        if field_clean.startswith("s_"):
            shape_type = field_clean[2:]
            return f"cell_shape.{shape_type}"
    
    # Handle trophic type
    if "trophic" in category_clean:
        if field_clean.startswith("tt_"):
            trait = field_clean[3:]
            return f"trophic_type.{trait}"
    
    # Handle pigment
    if category_clean == "pigment":
        if field_clean.startswith("pigment_"):
            color = field_clean[8:]
            return f"pigment.{color}"
    
    # Default: combine category and field
    if category_clean:
        return f"{category_clean}.{field_clean}"
    else:
        return field_clean

def split_list_values(value: str) -> Any:
    """Split comma-separated values into arrays where appropriate"""
    if not value or not isinstance(value, str):
        return value
    
    # Check if it looks like a list (contains commas)
    if ',' in value and not re.match(r'^\d+([.,]\d+)*$', value):  # Not just a number with decimals
        # Split and clean
        items = [item.strip() for item in value.split(',')]
        return [item for item in items if item]  # Remove empty items
    
    return value

def parse_value(value: str) -> Any:
    """Parse value, converting numbers and filtering out NA/empty"""
    if not value or value.strip() in ('NA', ''):
        return None
    
    value = value.strip()
    
    # Try numeric conversion
    try:
        if '.' in value:
            num_val = float(value)
            # Skip zero values in one-hot encoding
            return num_val if num_val != 0.0 else None
        else:
            num_val = int(value)
            # Skip zero values in one-hot encoding
            return num_val if num_val != 0 else None
    except ValueError:
        return value

def build_nested_dict(path_parts: List[str], value: Any) -> Dict:
    """Build nested dictionary from path parts"""
    if len(path_parts) == 1:
        return {path_parts[0]: value}
    
    return {path_parts[0]: build_nested_dict(path_parts[1:], value)}

def merge_dicts(dict1: Dict, dict2: Dict) -> Dict:
    """Deep merge two dictionaries"""
    result = dict1.copy()
    
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    
    return result

def parse_bactotraits_to_mongo(input_file: str) -> List[Dict[str, Any]]:
    """
    Parse BactoTraits CSV into MongoDB-compatible JSON.
    
    - Uses hierarchical header structure (category + field name)
    - Creates nested paths using forward-filled categories
    - Only includes non-zero, non-NA, non-empty values
    - Handles one-hot encoding by preserving all non-zero values
    - Splits comma-separated values into arrays
    """
    
    # Try multiple encodings
    encodings = ['utf-8', 'utf-8-sig', 'cp1252', 'latin1', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            with open(input_file, 'r', encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
    else:
        with open(input_file, 'r', encoding='latin1') as f:
            content = f.read()
    
    lines = content.splitlines()
    reader = csv.reader(lines, delimiter=';')
    
    # Read all three header rows
    categories = next(reader)  # Row 1: categories (forward-fill these)
    units = next(reader)       # Row 2: units (skip)
    field_names = next(reader) # Row 3: actual field names
    
    # Forward-fill the categories
    filled_categories = forward_fill_headers(categories)
    
    records = []
    
    for row in reader:
        record = {}
        
        for i, value in enumerate(row):
            if i >= len(field_names) or i >= len(filled_categories):
                continue
                
            field_name = field_names[i].strip()
            category = filled_categories[i].strip()
            
            # Skip empty field names
            if not field_name:
                continue
            
            # Parse and filter value
            parsed_value = parse_value(value)
            if parsed_value is None:
                continue
            
            # Split list values if appropriate
            parsed_value = split_list_values(parsed_value)
            
            # Create hierarchical field path
            field_path = create_field_path(category, field_name)
            
            # Build nested structure
            if '.' in field_path:
                path_parts = field_path.split('.')
                nested_dict = build_nested_dict(path_parts, parsed_value)
                record = merge_dicts(record, nested_dict)
            else:
                record[field_path] = parsed_value
        
        if record:  # Only add records with actual data
            records.append(record)
    
    return records

def main():
    parser = argparse.ArgumentParser(description='Convert BactoTraits CSV to MongoDB-compatible JSON')
    parser.add_argument('-i', '--input', required=True, help='Input CSV file')
    parser.add_argument('-o', '--output', required=True, help='Output JSON file')
    parser.add_argument('--pretty', action='store_true', help='Pretty print JSON')
    
    args = parser.parse_args()
    
    # Parse the CSV
    records = parse_bactotraits_to_mongo(args.input)
    
    # Output
    json_kwargs = {'indent': 2} if args.pretty else {}
    
    with open(args.output, 'w') as f:
        json.dump(records, f, **json_kwargs)
    
    print(f"Converted {len(records)} records to {args.output}")
    
    # Show sample structure
    if records:
        print(f"\nSample record structure:")
        print(json.dumps(records[0], indent=2)[:500] + "...")

if __name__ == '__main__':
    main()