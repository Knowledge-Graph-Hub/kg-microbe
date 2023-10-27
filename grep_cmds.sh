echo "CHEBI"
grep 'CHEBI' data/merged/merged-kg/merged-kg_nodes.tsv  | wc
echo "PubChem"
grep 'PubChem' data/merged/merged-kg/merged-kg_nodes.tsv  | wc
echo "KEGG"
grep 'KEGG' data/merged/merged-kg/merged-kg_nodes.tsv  | wc
echo "CAS-RN"
grep 'CAS-RN' data/merged/merged-kg/merged-kg_nodes.tsv  | wc
echo "mediadive"
grep 'mediadive' data/merged/merged-kg/merged-kg_nodes.tsv  | wc
echo "mediadive.ingredient"
grep 'mediadive.ingredient' data/merged/merged-kg/merged-kg_nodes.tsv  | wc
echo "mediadive.solution"
grep 'mediadive.solution' data/merged/merged-kg/merged-kg_nodes.tsv  | wc
echo "mediadive.medium"
grep 'mediadive.medium' data/merged/merged-kg/merged-kg_nodes.tsv  | wc

echo "EDGES"
echo "taxon -> medium"
grep 'mediadive.medium'  data/merged/merged-kg/merged-kg_edges.tsv  | grep NCBITaxon | wc

