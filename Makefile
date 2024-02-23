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
	echo "traits.cell_shape"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'traits.cell_shape' | wc -l

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


neo4j-upload:
	kgx neo4j-upload --uri bolt://localhost:7687 \
                     --username neo4j \
                     --password 12345678 \
                     --input-format tsv \
                     data/merged/merged-kg/merged-kg_nodes.tsv data/merged/merged-kg/merged-kg_edges.tsv

feba-schema-diagram:
	CURRENT_DIR=$(shell pwd) && docker run --mount type=bind,source="$$CURRENT_DIR",target=/home/schcrwlr \
	--rm -it schemacrawler/schemacrawler /opt/schemacrawler/bin/schemacrawler.sh \
	--server=sqlite --database=notebooks/feba.db \
	--info-level=maximum  \
	--command=schema   \
	--children=1 \
	--parents=1 \
	--weak-associations \
	--infer-extension-tables  \
	--output-file notebooks/schema.pdf


