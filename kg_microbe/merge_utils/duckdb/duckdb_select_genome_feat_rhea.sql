-- NERSC
-- CREATE OR REPLACE TABLE edges AS
-- SELECT * FROM read_csv('data/merged/merged_uniprot_bacdive/merged-kg_uniprot_bacdive_edges.tsv', filename=true, union_by_name=true);
SET temp_directory='$SCRATCH/TMP/';
PRAGMA memory_limit='220GB'; 

CREATE OR REPLACE TABLE edges AS
SELECT subject, object, predicate  -- Include predicate if it's used in filtering
FROM read_csv('data/merged/merged_uniprot_bacdive/merged-kg_uniprot_bacdive_edges.tsv', filename=true, union_by_name=true)
WHERE (subject LIKE 'Proteomes:%' AND object LIKE 'NCBITaxon:%')
   OR (subject LIKE 'UniprotKB:%'
   AND object LIKE 'Proteomes:%')
   OR (subject LIKE 'UniprotKB:%'
   AND object LIKE 'RHEA:%');


-- Step 1: Filter Proteomes to NCBITaxon directly into a temporary table
CREATE TEMPORARY TABLE Step1 AS
SELECT e1.subject AS Proteomes, e1.object AS NCBITaxon
FROM edges e1
WHERE e1.subject LIKE 'Proteomes:%'
  AND e1.object LIKE 'NCBITaxon:%';

-- Step 2: Join UniprotKB to Proteomes, carry NCBITaxon forward
CREATE TEMPORARY TABLE Step2 AS
SELECT 
    e2.subject AS UniprotKB, 
    e2.object AS Proteomes, 
    s1.NCBITaxon
FROM 
    (SELECT subject, object FROM edges WHERE subject LIKE 'UniprotKB:%') e2
JOIN 
    Step1 s1 ON e2.object = s1.Proteomes;


DROP TABLE Step1;


CREATE TEMPORARY TABLE RHEA_Edges AS
SELECT subject, object
FROM edges
WHERE object LIKE 'RHEA:%';

-- Handling RHEA Edges
CREATE TEMPORARY TABLE RHEA_Joined AS
SELECT s2.NCBITaxon, ec.subject AS UniprotKB, ec.object AS RHEA
FROM RHEA_Edges ec
JOIN Step2 s2 ON ec.subject = s2.UniprotKB;

-- Output RHEA results to a TSV file and drop temporary tables
COPY RHEA_Joined TO 'NCBITaxon_to_RHEA.tsv' (FORMAT CSV, DELIMITER '\t', HEADER);
DROP TABLE RHEA_Joined;
DROP TABLE RHEA_Edges;

-- As Step2 is no longer needed after processing all types, it can be dropped
DROP TABLE Step2;


