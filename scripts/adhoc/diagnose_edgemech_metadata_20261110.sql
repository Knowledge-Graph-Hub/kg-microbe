-- Purpose: diagnose EdgeMech #36 endpoint labels against local producer outputs.
-- Inputs: pinned EdgeMech node gap Parquet and existing KG-Microbe TSV outputs.
-- Outputs: read-only query results on stdout; no source files or databases changed.
-- Date: 2026-11-10. Run with duckdb < this file.
CREATE TEMP VIEW gaps AS SELECT * FROM read_parquet(
  '/Users/marcin/Documents/VIMSS/ontology/Mechs/EdgeMech/workspace/node-metadata-full-v2-20261110/nodes.parquet');
SELECT 'bacdive' AS scope, * FROM gaps WHERE list_contains(sources, 'infores:bacdive')
ORDER BY affected_occurrences DESC, id;
SELECT 'envo' AS scope, * FROM gaps WHERE starts_with(id, 'ENVO:')
ORDER BY affected_occurrences DESC, id;
SELECT 'ec_top' AS scope, * FROM gaps WHERE starts_with(id, 'EC:')
ORDER BY affected_occurrences DESC, id LIMIT 25;
SELECT 'bto_top' AS scope, * FROM gaps WHERE starts_with(id, 'BTO:')
ORDER BY affected_occurrences DESC, id LIMIT 20;
CREATE TEMP VIEW ontology_nodes AS SELECT * FROM read_csv(
  '/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe/data/transformed/ontologies/*_nodes.tsv',
  delim='\t', header=true, all_varchar=true, quote='', filename=true, union_by_name=true);
SELECT 'existing_ontology_output' AS scope, g.id, g.affected_occurrences, o.name, o.category, o.filename
FROM gaps g LEFT JOIN ontology_nodes o USING(id)
WHERE starts_with(g.id, 'EC:') OR starts_with(g.id, 'ENVO:')
ORDER BY g.affected_occurrences DESC, g.id;
