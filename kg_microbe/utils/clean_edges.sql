
create or replace table edges as select * from read_csv('./merged-kg_edges.tsv.gz', filename=true, union_by_name=true);

-- 93325273
DELETE FROM edges
WHERE subject LIKE 'UniprotKB:%'
  AND object LIKE 'NCBITaxon:%';

-- 73453980

DELETE FROM edges
WHERE id NOT IN (
    SELECT id
    FROM (
        SELECT
            id,
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
        FROM edges
    ) sub
    WHERE rn = 1
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
) TO 'merged-kg_edges_new.tsv' WITH (FORMAT 'csv', DELIMITER '\t', HEADER true);
