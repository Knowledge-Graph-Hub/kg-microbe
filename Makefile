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
	echo "ingredient:"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'ingredient:' | wc -l
	echo "solution:"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'solution:' | wc -l
	echo "medium:"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'medium:' | wc -l
	echo "traits"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'carbon_substrate' | wc -l
	echo "traits.pathways"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'pathways' | wc -l
	echo "traits.cell_shape_enum"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'traits.' | wc -l
	echo "carbon_substrate"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'carbon_substrate' | wc -l
	echo "pathways"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'pathways' | wc -l
	echo "cell_shape"
	cut -f1 data/merged/merged-kg_nodes.tsv |grep 'cell_shape' | wc -l

	echo "EDGES"
	wc -l data/merged/merged-kg_edges.tsv
	echo "taxon -> medium"
	grep 'medium:' data/merged/merged-kg_edges.tsv | grep 'NCBITaxon:' | wc -l
	echo "medium-> ingredient"
	grep 'medium:' data/merged/merged-kg_edges.tsv | grep 'ingredient:' | wc -l
	echo "medium-> solution"
	grep 'medium:' data/merged/merged-kg_edges.tsv | grep 'solution:' | wc -l
	echo "ingredient -> CHEBI"
	grep 'ingredient:' data/merged/merged-kg_edges.tsv | grep 'CHEBI' | wc -l
	echo "solution -> CHEBI"
	grep 'solution:' data/merged/merged-kg_edges.tsv | grep 'CHEBI' | wc -l
	echo "ingredient -> solution"
	grep 'ingredient:' data/merged/merged-kg_edges.tsv | grep 'solution:' | wc -l
	echo "taxon -> CHEBI"
	grep 'CHEBI:' data/merged/merged-kg_edges.tsv | grep 'NCBITaxon:' | wc -l
	echo "taxon -> GO"
	grep 'GO:' data/merged/merged-kg_edges.tsv | grep 'NCBITaxon:' | wc -l

	grep 'oxygen:' data/merged/merged-kg_edges.tsv  |wc -l
	echo "taxon -> oxygen"
	grep 'salinity:' data/merged/merged-kg_edges.tsv  |wc -l
	echo "taxon -> salinity"
	grep 'pH:' data/merged/merged-kg_edges.tsv  |wc -l
	echo "taxon -> pH"
	grep 'temperature:' data/merged/merged-kg_edges.tsv  |wc -l
	echo "taxon -> temperature"
	grep 'pathways:' data/merged/merged-kg_edges.tsv  |wc -l
	echo "taxon -> pathways"
	grep 'pathogen:' data/merged/merged-kg_edges.tsv  |wc -l
	echo "taxon -> pathogen"


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


