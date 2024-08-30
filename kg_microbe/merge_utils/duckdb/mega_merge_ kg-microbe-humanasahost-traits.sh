duckdb



-- to merge that graph with the original merged graph

-- for nodes

create or replace table merged_nodes_subset as 
select
    id, name, description, category, xref, provided_by, synonym, object, predicate, relation, same_as, subject, subsets
from read_csv('merged-kg_kg-microbe-host_subset/merged-kg_nodes.tsv', filename=true, union_by_name=true);


create or replace table merged_nodes_base as 
select
    id, name, description, category, xref, provided_by, synonym, object, predicate, relation, same_as, subject, subsets
from read_csv('merged-kg_kg-microbe-base/merged-kg_nodes.tsv', filename=true, union_by_name=true); 

INSERT INTO merged_nodes_subset (id, name, description, category, xref, provided_by, synonym, object, predicate, relation, same_as, subject, subsets)
SELECT id, name, description, category, xref, provided_by, synonym, object, predicate, relation, same_as, subject, subsets
FROM merged_nodes_base;

SELECT COUNT(*) FROM merged_nodes_subset;

# SELECT id, name, description, category, xref, provided_by, synonym, object, predicate, relation, same_as, subject, subsets
# FROM merged_nodes_subset;

# COPY (
#     SELECT id, category, name, description, xref, provided_by, synonym, object, predicate, relation, same_as, subject, subsets
#     FROM merged_nodes_subset
# ) TO 'merged-kg_kg-microbe-humanasahost-traits_nodes_raw.tsv' WITH (FORMAT 'csv', DELIMITER '\t', HEADER true);


-- for edges

create or replace table merged_edges_subset as select * from read_csv('merged-kg_kg-microbe-host_subset/merged-kg_edges.tsv', filename=true, union_by_name=true);

create or replace table merged_edges_base as select * from read_csv('merged-kg_kg-microbe-base/merged-kg_edges.tsv', filename=true, union_by_name=true);

INSERT INTO merged_edges_subset (subject, predicate, object, relation, primary_knowledge_source)
SELECT subject, predicate, object, relation, primary_knowledge_source
FROM merged_edges_base;

SELECT COUNT(*) FROM merged_edges_subset;

# SELECT subject, predicate, object, relation, primary_knowledge_source
# FROM merged_edges_subset;

# COPY (
#     SELECT
#         subject,
#         predicate,
#         object,
#         relation,
#         primary_knowledge_source
#     FROM merged_edges_subset
# ) TO 'merged-kg_kg-microbe-humanasahost-traits_edges.tsv' WITH (FORMAT 'csv', DELIMITER '\t', HEADER true);


-------


-- get all duplicate nodes, and select only one of them where they will be ordered by ontology/prefix
select split_part(id, ':', 1) as prefix, count(id) as duplicates
  from
  (
      select id, count(*) as duplicate_count
      from merged_nodes_subset
      group by id
      having(duplicate_count > 1 )
  )
  group by prefix;



  WITH DuplicateIDs AS (
    SELECT id
    FROM merged_nodes_subset
    GROUP BY id
    HAVING COUNT(*) > 1
),
ExamplesOfDuplicates AS (
    SELECT 
        rn.id, rn.name, rn.description, rn.category, rn.xref, rn.provided_by,
        rn.synonym, rn.object, rn.predicate, rn.relation,
        rn.same_as, rn.subject, rn.subsets
    FROM merged_nodes_subset rn
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
    e.object,
    e.predicate,
    e.relation,
    e.same_as,
    e.subject,
    e.subsets
FROM PrefixCount p
JOIN ExamplesOfDuplicates e ON p.id = e.id
ORDER BY p.prefix, e.id
LIMIT 2;


-- create a new table nodes 
CREATE OR REPLACE TABLE nodes AS
SELECT *
FROM (
    SELECT *,
        -- Using a window function to assign a rank; rows with 'data/duckdb/merged' in filename are given higher priority
        ROW_NUMBER() OVER (
            PARTITION BY id
            -- ORDER BY CASE WHEN filename LIKE 'merged-kg_kg-microbe-host_subset/merged-kg_edges.tsv' THEN 1 ELSE 2 END
        ) as rn
    FROM merged_nodes_subset
) sub
WHERE sub.rn = 1;

SELECT COUNT(*) AS total_entries
FROM nodes;

COPY (
    SELECT id, category, name, description, xref, provided_by, synonym, object, predicate, relation, same_as, subject, subsets
    FROM nodes
) TO 'merged-kg_kg-microbe-humanasahost-traits_nodes.tsv' WITH (FORMAT 'csv', DELIMITER '\t', HEADER true);




-- get all duplicate edges by subject/object pairs just to evaluate
  SELECT 
      split_part(subject, ':', 1) AS subject_prefix, 
      split_part(object, ':', 1) AS object_prefix, 
      COUNT(*) AS duplicates
  FROM (
      SELECT 
          subject, 
          object, 
          COUNT(*) AS duplicate_count
      FROM merged_edges_subset
      GROUP BY subject, object
      HAVING COUNT(*) > 1
  ) sub
  GROUP BY subject_prefix, object_prefix;


-- get all duplicate edges by subject/object pairs from merged_edges_subset
WITH DuplicateEdges AS (
      SELECT 
          subject, 
          object, 
          COUNT(*) AS duplicate_count
      FROM merged_edges_subset
      -- WHERE 
          -- subject LIKE 'RHEA:%' AND 
          -- object LIKE 'GO:%'
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
      merged_edges_subset re
  INNER JOIN DuplicateEdges de ON re.subject = de.subject AND re.object = de.object;


WITH DuplicatedPairs AS (
      SELECT
          split_part(subject, ':', 1) AS subject_prefix,
          split_part(object, ':', 1) AS object_prefix,
          subject,
          object
      FROM merged_edges_subset
      GROUP BY subject, object
      HAVING COUNT(*) > 1
  ),
  AggregatedPredicates AS (
      SELECT
          split_part(subject, ':', 1) AS subject_prefix,
          split_part(object, ':', 1) AS object_prefix,
          array_agg(DISTINCT predicate) AS predicates
      FROM merged_edges_subset
      WHERE EXISTS (
          SELECT 1
          FROM DuplicatedPairs dp
          WHERE dp.subject = merged_edges_subset.subject AND dp.object = merged_edges_subset.object
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
    merged_edges_subset.*,
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
FROM merged_edges_subset
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

SELECT COUNT(*) FROM merged_edges_subset;
SELECT COUNT(*) FROM edges;


COPY (
    SELECT
        subject,
        predicate,
        object,
        relation,
        primary_knowledge_source
    FROM edges
) TO 'merged-kg_kg-microbe-humanasahost-traits_edges.tsv' WITH (FORMAT 'csv', DELIMITER '\t', HEADER true);






