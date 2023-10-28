echo "NODES"
wc -l data/merged/merged-kg/merged-kg_nodes.tsv
echo "NCBITaxon:"
grep 'NCBITaxon:' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "CHEBI:"
grep 'CHEBI:' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "PubChem:"
grep 'PubChem:' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "KEGG:"
grep 'KEGG:' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "CAS-RN:"
grep 'CAS-RN:' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "mediadive"
grep 'mediadive' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "mediadive."
grep 'mediadive.' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "mediadive.ingredient:"
grep 'mediadive.ingredient:' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "mediadive.solution:"
grep 'mediadive.solution:' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "mediadive.medium:"
grep 'mediadive.medium:' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l
echo "traits"
grep 'traits.' data/merged/merged-kg/merged-kg_nodes.tsv  | wc -l

echo "EDGES"
wc -l data/merged/merged-kg/merged-kg_edges.tsv
echo "taxon -> medium"
grep 'mediadive.medium:'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'NCBITaxon:' | wc -l
echo "medium-> ingredient"
grep 'mediadive.medium:'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'mediadive.ingredient' | wc -l
echo "medium-> solution"
grep 'mediadive.medium:'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'mediadive.solution' | wc -l
echo "ingredient -> CHEBI"
grep 'mediadive.ingredient:'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'CHEBI' | wc -l
echo "solution -> CHEBI"
grep 'mediadive.solution:'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'CHEBI' | wc -l
echo "ingredient -> solution"
grep 'mediadive.ingredient:'  data/merged/merged-kg/merged-kg_edges.tsv |  grep 'mediadive.solution' | wc -l
echo "taxon -> CHEBI"
grep 'CHEBI:'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'NCBITaxon:' | wc -l
echo "taxon -> GO"
grep 'GO:'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'NCBITaxon:' | wc -l
echo "trait -> CHEBI"
grep 'trait'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'CHEBI:' | wc -l

echo "traits.pathways -> CHEBI"
grep 'traits.pathways'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'CHEBI:' | wc -l

echo "traits.carbon_substrate-> CHEBI"
grep 'traits.carbon_substrate'  data/merged/merged-kg/merged-kg_edges.tsv  | grep 'CHEBI:' | wc -l
