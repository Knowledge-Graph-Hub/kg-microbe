.PHONY: run-summary process-metatraits-unmapped \
        validate-isolation-source-schema validate-ingredient-schema
.SILENT:

run-summary:
	poetry run python scripts/graph_summary.py data/merged


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

process-metatraits-unmapped:
	@echo "Processing metatraits unmapped data..."
	@if [ ! -f data/transformed/metatraits/unmapped_traits.tsv ]; then \
		echo "Error: data/transformed/metatraits/unmapped_traits.tsv not found"; \
		exit 1; \
	fi
	@echo "Extracting unique trait IDs..."
	cut -f1 data/transformed/metatraits/unmapped_traits.tsv | sort | uniq > data/transformed/metatraits/unmapped_traits_unique.tsv
	@echo "Extracting unique relation prefixes..."
	cut -f1 -d ':' data/transformed/metatraits/unmapped_traits_unique.tsv | sort | uniq > data/transformed/metatraits/unmapped_traits_unique_relations.tsv
	@echo "Metatraits unmapped data processing complete"
	@echo "Generated files:"
	@wc -l data/transformed/metatraits/unmapped_traits_unique.tsv
	@wc -l data/transformed/metatraits/unmapped_traits_unique_relations.tsv

# Schema/category validation gates for SSSOM-shaped mapping TSVs.
# Complements mappings/validate_isolation_source_mappings.py (runtime
# family-mismatch check) — this one validates CURIE shape, predicate
# vocab, ontology category allowlists, and lexical drift.
# Exit codes: 2 = errors, 1 = warnings (with --strict), 0 = clean.
validate-isolation-source-schema:
	@echo "Validating mappings/isolation_source_to_ontology.tsv (schema)..."
	python3 mappings/validate_mapping_schema.py

validate-ingredient-schema:
	@echo "Validating mappings/ingredient_mappings.sssom.tsv (schema)..."
	python3 mappings/validate_mapping_schema.py --profile ingredient

# MediaDive recipe coverage vs the committed baseline. Upstream thinned these
# recipes by 48% between the 2024-12 and 2026-08 builds and nothing noticed for
# ~20 months (#728); this is the check that would have caught it.
# Exit codes: 1 = coverage moved beyond tolerance, 0 = clean.
validate-mediadive-coverage:
	@echo "Validating MediaDive recipe coverage against the committed baseline..."
	python3 scripts/mediadive_coverage_check.py

include kg-microbe.Makefile
