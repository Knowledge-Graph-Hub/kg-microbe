grep location_of data/merged/merged-kg_edges.tsv | grep NCBITaxon | cut -f4 | sort | uniq -c 
