#!/usr/bin/env python3
"""Convert KGX TSV files to N-Triples format using KGX."""

import pandas as pd
from urllib.parse import quote
from kgx.transformer import Transformer
import tempfile
import os

def clean_uri(uri_string):
    """Clean and encode URI string to make it valid."""
    if pd.isna(uri_string):
        return uri_string
    
    uri_string = str(uri_string)
    # Handle problematic characters
    uri_string = uri_string.replace('°', 'deg')
    uri_string = uri_string.replace('→', '_to_')
    uri_string = uri_string.replace('->', '_to_')
    uri_string = uri_string.replace('>', '_gt_')
    uri_string = uri_string.replace('<', '_lt_')
    
    # URL encode any remaining problematic characters in the fragment part
    if ':' in uri_string and '/' in uri_string:
        # Split on the last slash and only encode the fragment part
        parts = uri_string.rsplit('/', 1)
        if len(parts) == 2:
            return parts[0] + '/' + quote(parts[1], safe=':_-.')
    elif ':' in uri_string:
        # Handle cases like "isolation_source:thermophilic->45°c"
        parts = uri_string.split(':', 1)
        if len(parts) == 2:
            return parts[0] + ':' + quote(parts[1], safe='_-.')
    
    return quote(uri_string, safe=':/_-.')

def clean_tsv_files(nodes_file, edges_file):
    """Clean URI strings in TSV files and return cleaned temporary files."""
    
    # Clean nodes file
    print("Cleaning nodes file...")
    nodes_df = pd.read_csv(nodes_file, sep='\t', low_memory=False)
    if 'id' in nodes_df.columns:
        nodes_df['id'] = nodes_df['id'].apply(clean_uri)
    
    # Clean edges file  
    print("Cleaning edges file...")
    edges_df = pd.read_csv(edges_file, sep='\t', low_memory=False)
    if 'subject' in edges_df.columns:
        edges_df['subject'] = edges_df['subject'].apply(clean_uri)
    if 'object' in edges_df.columns:
        edges_df['object'] = edges_df['object'].apply(clean_uri)
    if 'predicate' in edges_df.columns:
        edges_df['predicate'] = edges_df['predicate'].apply(clean_uri)
    
    # Save to temporary files
    temp_nodes = tempfile.NamedTemporaryFile(mode='w', suffix='_nodes.tsv', delete=False)
    temp_edges = tempfile.NamedTemporaryFile(mode='w', suffix='_edges.tsv', delete=False)
    
    nodes_df.to_csv(temp_nodes.name, sep='\t', index=False)
    edges_df.to_csv(temp_edges.name, sep='\t', index=False)
    
    temp_nodes.close()
    temp_edges.close()
    
    return temp_nodes.name, temp_edges.name

def convert_to_nt(nodes_file, edges_file, output_file):
    """Convert KGX TSV files to N-Triples format using KGX."""
    
    print(f"Converting {nodes_file} and {edges_file} to {output_file}")
    
    # Clean the TSV files first
    clean_nodes_file, clean_edges_file = clean_tsv_files(nodes_file, edges_file)
    
    try:
        transformer = Transformer()
        transformer.transform(
            input_args={
                'filename': [clean_nodes_file, clean_edges_file],
                'format': 'tsv'
            },
            output_args={
                'filename': output_file,
                'format': 'nt'
            }
        )
        
        print(f"Successfully converted to {output_file}")
        
    finally:
        # Clean up temporary files
        os.unlink(clean_nodes_file)
        os.unlink(clean_edges_file)

if __name__ == "__main__":
    nodes_file = "data/merged/20250802_newbacdive/merged-kg_nodes.tsv"
    edges_file = "data/merged/20250802_newbacdive/merged-kg_edges.tsv" 
    output_file = "data/merged/20250802_newbacdive/kg-microbe.nt"
    
    convert_to_nt(nodes_file, edges_file, output_file)