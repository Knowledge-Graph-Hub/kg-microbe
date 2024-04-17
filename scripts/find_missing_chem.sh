grep '^ingredient:' data/merged/merged-kg_nodes.tsv > missing_chem.txt
grep '^KEGG:' data/merged/merged-kg_nodes.tsv >> missing_chem.txt
grep '^PubChem:' data/merged/merged-kg_nodes.tsv >> missing_chem.txt
grep '^CAS-RN:' data/merged/merged-kg_nodes.tsv >> missing_chem.txt


grep CAS-RN kg_microbe/transform_utils/ontology/xrefs/chebi_xrefs.tsv > cas-rn_map.txt
grep '^CAS-RN:' data/merged/merged-kg_nodes.tsv | cut -f1 > missing_chem_casrn.txt
# Step 1: Sort the second column of the first file and the second file
cut -d' ' -f2 cas-rn_map.txt | sort -u > sorted_first.txt
sort -u missing_chem_casrn.txt > sorted_second.txt

# Step 2: Use comm to find entries in the second file not in the first file's second column
comm -13 sorted_first.txt sorted_second.txt > missing_chem_casrn.txt
