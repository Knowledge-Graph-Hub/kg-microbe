import rdflib
from rdflib import Namespace, URIRef
import re
import csv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define the namespaces used in the OWL file
NCBITAXON_NAMESPACE = "http://purl.obolibrary.org/obo/NCBITaxon_"
NCBITAXON_PREFIX = "NCBITaxon:"

# Initialize the graph
g = rdflib.Graph()

# Parse the OWL file
owl_file_path = '/global/cfs/cdirs/m4689/master/kg-microbe/data/raw/ncbitaxon.owl'  # Replace with your actual file path
try:
    logging.info(f"Parsing OWL file: {owl_file_path}")
    g.parse(owl_file_path, format='xml')
    logging.info("OWL file parsed successfully.")
except Exception as e:
    logging.error(f"Failed to parse OWL file: {e}")
    exit(1)

# Prepare a list to hold the results
results = []

# Iterate over all owl:Class instances
for cls in g.subjects(rdflib.RDF.type, rdflib.OWL.Class):
    try:
        # Get the rdf:about attribute
        about = cls
        about_str = str(about)
        
        # Extract the identifier (e.g., NCBITaxon_100000)
        match = re.search(r'NCBITaxon_(\d+)', about_str)
        if not match:
            logging.warning(f"Identifier pattern not found in: {about_str}")
            continue  # Skip if pattern does not match
        taxon_id = match.group(1)
        identifier = f"{NCBITAXON_PREFIX}{taxon_id}"
        
        # Get the has_rank property
        has_rank = g.value(cls, rdflib.URIRef("http://purl.obolibrary.org/obo/ncbitaxon#has_rank"))
        if has_rank:
            has_rank_str = str(has_rank)
            # Extract the rank name from the IRI (e.g., species)
            rank_match = re.search(r'NCBITaxon_(\w+)', has_rank_str)
            if rank_match:
                rank = rank_match.group(1).lower()  # Convert to lowercase for consistency
            else:
                rank = "unknown"
        else:
            rank = "unknown"
        
        # Append the result
        results.append({'identifier': identifier, 'rank': rank})
        logging.info(f"Processed identifier: {identifier}, rank: {rank}")
        
    except Exception as e:
        logging.error(f"Error processing class {cls}: {e}")

# Define the output TSV file path
output_tsv_path = 'NCBITaxon_rank.tsv'  # Replace with your desired output path

# Write the results to a TSV file
try:
    with open(output_tsv_path, 'w', newline='', encoding='utf-8') as tsvfile:
        fieldnames = ['identifier', 'rank']
        writer = csv.DictWriter(tsvfile, fieldnames=fieldnames, delimiter='\t')
        
        # Write the header
        writer.writeheader()
        
        # Write each row
        for row in results:
            writer.writerow(row)
    logging.info(f"Extraction complete. Results saved to {output_tsv_path}")
except Exception as e:
    logging.error(f"Failed to write to TSV file: {e}")

