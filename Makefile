.PHONY: run-summary
.SILENT:

run-summary:
	echo "NODES"
	wc -l data/merged/merged-kg_nodes.tsv	
	echo "NCBITaxon:"
	cut -f1 data/merged/merged-kg_nodes.tsv | grep 'NCBITaxon:' | wc -l
	echo "CHEBI:"
	cut -f1 data/merged/merged-kg_nodes.tsv | grep 'CHEBI:' | wc -l
	echo "PubChem:"
	cut -f1 data/merged/merged-kg_nodes.tsv | grep 'PubChem:' | wc -l
	echo "KEGG:"
	cut -f1 data/merged/merged-kg_nodes.tsv | grep 'KEGG:' | wc -l
	echo "CAS-RN:"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'CAS-RN:' | wc -l
	echo "mediadive."
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'mediadive.' | wc -l
	echo "mediadive.ingredient:"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'mediadive.ingredient:' | wc -l
	echo "mediadive.solution:"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'mediadive.solution:' | wc -l
	echo "mediadive.medium:"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'mediadive.medium:' | wc -l
	echo "traits"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'traits.' | wc -l
	echo "traits.carbon_substrate"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'traits.carbon_substrate' | wc -l
	echo "traits.pathways"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'traits.pathways' | wc -l
	echo "traits.cell_shape_enum"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'traits.cell_shape_enum' | wc -l

	echo "EDGES"
	wc -l data/merged/merged-kg_edges.tsv
	echo "taxon -> medium"
	grep 'mediadive.medium:' data/merged/merged-kg_edges.tsv | grep 'NCBITaxon:' | wc -l
	echo "medium-> ingredient"
	grep 'mediadive.medium:' data/merged/merged-kg_edges.tsv | grep 'mediadive.ingredient' | wc -l
	echo "medium-> solution"
	grep 'mediadive.medium:' data/merged/merged-kg_edges.tsv | grep 'mediadive.solution' | wc -l
	echo "ingredient -> CHEBI"
	grep 'mediadive.ingredient:' data/merged/merged-kg_edges.tsv | grep 'CHEBI' | wc -l
	echo "solution -> CHEBI"
	grep 'mediadive.solution:' data/merged/merged-kg_edges.tsv | grep 'CHEBI' | wc -l
	echo "ingredient -> solution"
	grep 'mediadive.ingredient:' data/merged/merged-kg_edges.tsv | grep 'mediadive.solution' | wc -l
	echo "taxon -> CHEBI"
	grep 'CHEBI:' data/merged/merged-kg_edges.tsv | grep 'NCBITaxon:' | wc -l
	echo "taxon -> GO"
	grep 'GO:' data/merged/merged-kg_edges.tsv | grep 'NCBITaxon:' | wc -l
