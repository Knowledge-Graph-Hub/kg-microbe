duckdb


create or replace table raw_nodes as select * from read_csv('data/duckdb/merged-kg_nodes.tsv.gz', filename=true, union_by_name=true); 


create or replace table raw_nodes as select * from read_csv('data/duckdb/*_nodes.tsv.gz', filename=true, union_by_name=true); 
create or replace table raw_edges as select * from read_csv('data/duckdb/*_edges.tsv.gz', filename=true, union_by_name=true);



select split_part(id, ':', 1) as prefix, count(id) as duplicates
  from
  (
      select id, count(*) as duplicate_count
      from raw_nodes
      group by id
      having(duplicate_count > 1 )
  )
  group by prefix;


┌───────────┬────────────┐
│  prefix   │ duplicates │
│  varchar  │   int64    │
├───────────┼────────────┤
│ RHEA      │       4328 │
│ UniprotKB │       3079 │
│ GO        │       7815 │
│ EC        │       3893 │
│ NCBITaxon │       7031 │
│ CHEBI     │        510 │
└───────────┴────────────┘


  WITH DuplicateIDs AS (
    SELECT id
    FROM raw_nodes
    GROUP BY id
    HAVING COUNT(*) > 1
),
ExamplesOfDuplicates AS (
    SELECT 
        rn.id, rn.name, rn.description, rn.category, rn.xref, rn.provided_by,
        rn.synonym, rn.deprecated, rn.iri, rn.object, rn.predicate, rn.relation,
        rn.same_as, rn.subject, rn.subsets, rn.filename
    FROM raw_nodes rn
    INNER JOIN DuplicateIDs did ON rn.id = did.id
),
PrefixCount AS (
    SELECT 
        split_part(id, ':', 1) as prefix, 
        id,
        COUNT(*) as example_count
    FROM ExamplesOfDuplicates
    GROUP BY prefix, id
    HAVING COUNT(*) >= 2
)
SELECT 
    p.prefix,
    e.id,
    e.name,
    e.description,
    e.category,
    e.xref,
    e.provided_by,
    e.synonym,
    e.deprecated,
    e.iri,
    e.object,
    e.predicate,
    e.relation,
    e.same_as,
    e.subject,
    e.subsets,
    e.filename
FROM PrefixCount p
JOIN ExamplesOfDuplicates e ON p.id = e.id
ORDER BY p.prefix, e.id
LIMIT 2;

┌─────────┬──────────────┬──────────────────────┬──────────────────────┬───┬──────────┬─────────┬─────────┬─────────┬──────────────────────┐
│ prefix  │      id      │         name         │     description      │ … │ relation │ same_as │ subject │ subsets │       filename       │
│ varchar │   varchar    │       varchar        │       varchar        │   │ varchar  │ varchar │ varchar │ varchar │       varchar        │
├─────────┼──────────────┼──────────────────────┼──────────────────────┼───┼──────────┼─────────┼─────────┼─────────┼──────────────────────┤
│ CHEBI   │ CHEBI:111503 │ validamine 7-phosp…  │ An organophosphate…  │ … │          │         │         │ 3_STAR  │ data/duckdb/merged…  │
│ CHEBI   │ CHEBI:111503 │                      │                      │ … │          │         │         │         │ data/duckdb/unipro…  │
├─────────┴──────────────┴──────────────────────┴──────────────────────┴───┴──────────┴─────────┴─────────┴─────────┴──────────────────────┤
│ 2 rows                                                                                                              17 columns (9 shown) 



CREATE OR REPLACE TABLE nodes AS
SELECT *
FROM (
    SELECT *,
        -- Using a window function to assign a rank; rows with 'data/duckdb/merged' in filename are given higher priority
        ROW_NUMBER() OVER (
            PARTITION BY id
            ORDER BY CASE WHEN filename LIKE 'data/duckdb/merged%' THEN 1 ELSE 2 END
        ) as rn
    FROM raw_nodes
) sub
WHERE sub.rn = 1;


SELECT COUNT(*) AS total_entries
FROM nodes;


┌───────────────┐
│ total_entries │
│     int64     │
├───────────────┤
│      21675436 │
└───────────────┘


COPY (
    SELECT id, category, name, description, xref, provided_by, synonym, deprecated, iri, object, predicate, relation, same_as, subject, subsets
    FROM nodes
) TO 'merged-kg_uniprot_nodes.tsv' WITH (FORMAT 'csv', DELIMITER '\t', HEADER true);





D SELECT 
      split_part(subject, ':', 1) AS subject_prefix, 
      split_part(object, ':', 1) AS object_prefix, 
      COUNT(*) AS duplicates
  FROM (
      SELECT 
          subject, 
          object, 
          COUNT(*) AS duplicate_count
      FROM raw_edges
      GROUP BY subject, object
      HAVING COUNT(*) > 1
  ) sub
  GROUP BY subject_prefix, object_prefix;
┌────────────────┬───────────────┬────────────┐
│ subject_prefix │ object_prefix │ duplicates │
│    varchar     │    varchar    │   int64    │
├────────────────┼───────────────┼────────────┤
│ RHEA           │ RHEA          │      48330 │
│ NCBITaxon      │ oxygen        │       4871 │
│ UBERON         │ UBERON        │         12 │
│ RHEA           │ CHEBI         │       5082 │
│ RHEA           │ GO            │       4393 │
│ NCBITaxon      │ CHEBI         │      25597 │
│ GO             │ GO            │         10 │
│ CHEBI          │ CHEBI         │       1064 │
│ ENVO           │ ENVO          │         10 │
└────────────────┴───────────────┴────────────┘



WITH DuplicateEdges AS (
      SELECT 
          subject, 
          object, 
          COUNT(*) AS duplicate_count
      FROM raw_edges
      WHERE 
          subject LIKE 'RHEA:%' AND 
          object LIKE 'GO:%'
      GROUP BY subject, object
      HAVING COUNT(*) > 1
  )
  SELECT 
      re.subject, 
      re.object,
      re.predicate,  -- Assuming you might also be interested in seeing the predicate connecting the subject and object
      re.relation,   -- Including relation if its relevant
      re.filename    -- Including filename to see where the data is coming from
  FROM 
      raw_edges re
  INNER JOIN DuplicateEdges de ON re.subject = de.subject AND re.object = de.object;


SELECT subject, predicate, object
  FROM raw_edges
  WHERE subject LIKE 'ENVO:%' AND object LIKE 'ENVO:%'
LIMIT 10;


  SELECT subject, predicate, object
FROM raw_edges
WHERE subject LIKE 'ENVO:%' 
  AND object LIKE 'ENVO:%' 
  AND (predicate LIKE '%type%' OR predicate LIKE '%related_to%' OR predicate LIKE '%subclass_of%');



WITH DuplicatedPairs AS (
      SELECT
          split_part(subject, ':', 1) AS subject_prefix,
          split_part(object, ':', 1) AS object_prefix,
          subject,
          object
      FROM raw_edges
      GROUP BY subject, object
      HAVING COUNT(*) > 1
  ),
  AggregatedPredicates AS (
      SELECT
          split_part(subject, ':', 1) AS subject_prefix,
          split_part(object, ':', 1) AS object_prefix,
          array_agg(DISTINCT predicate) AS predicates
      FROM raw_edges
      WHERE EXISTS (
          SELECT 1
          FROM DuplicatedPairs dp
          WHERE dp.subject = raw_edges.subject AND dp.object = raw_edges.object
      )
      GROUP BY subject, object
  ),
  PrefixGroupedPredicates AS (
      SELECT
          subject_prefix,
          object_prefix,
          array_agg(DISTINCT predicates) AS grouped_predicates
      FROM AggregatedPredicates
      GROUP BY subject_prefix, object_prefix
  )
  SELECT
      subject_prefix,
      object_prefix,
      grouped_predicates
  FROM PrefixGroupedPredicates
  ORDER BY subject_prefix, object_prefix;









CREATE OR REPLACE TABLE edges AS
SELECT
    raw_edges.*,
    ROW_NUMBER() OVER (
        PARTITION BY subject, object
        ORDER BY
            CASE
                WHEN predicate = 'biolink:has_chemical_role' THEN 1
                WHEN predicate = 'biolink:subclass_of' THEN 2
                WHEN predicate = 'biolink:capable_of' THEN 3
                WHEN predicate = 'biolink:can_be_carried_out_by' THEN 4
                WHEN predicate = 'biolink:superclass_of' THEN 5
                ELSE 6
            END
    ) AS rn
FROM raw_edges
QUALIFY (
    rn = 1
    AND NOT (
        (split_part(subject, ':', 1) = 'NCBITaxon' AND split_part(object, ':', 1) = 'CHEBI')
        OR (split_part(subject, ':', 1) = 'RHEA' AND split_part(object, ':', 1) = 'CHEBI')
    )
)
OR (
    (split_part(subject, ':', 1) = 'NCBITaxon' AND split_part(object, ':', 1) = 'CHEBI')
    OR (split_part(subject, ':', 1) = 'RHEA' AND split_part(object, ':', 1) = 'CHEBI')
);


DELETE FROM edges
WHERE subject LIKE 'UniprotKB:%'
  AND object LIKE 'NCBITaxon:%';



COPY (
    SELECT
        id,
        subject,
        predicate,
        object,
        relation,
        knowledge_source,
        meta,
        primary_knowledge_source
    FROM edges
) TO 'merged-kg_uniprot_bacdive_edges.tsv' WITH (FORMAT 'csv', DELIMITER '\t', HEADER true);





