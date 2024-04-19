
create or replace table edges as select * from read_csv('./merged-kg_edges.tsv.gz', filename=true, union_by_name=true);

DELETE FROM edges
WHERE subject LIKE 'UniprotKB:%'
  AND object LIKE 'NCBITaxon:%';


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
) TO 'merged-kg_edges_new.tsv WITH (FORMAT 'csv', DELIMITER '\t', HEADER true);
