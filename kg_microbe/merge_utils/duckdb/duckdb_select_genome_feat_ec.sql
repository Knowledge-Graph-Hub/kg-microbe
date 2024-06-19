-- CREATE OR REPLACE TABLE edges AS
-- SELECT * FROM read_csv('data/merged/merged_uniprot_bacdive/merged-kg_uniprot_bacdive_edges.tsv', filename=true, union_by_name=true);
SET temp_directory='$SCRATCH/TMP/';
PRAGMA memory_limit='100GB'; 

CREATE OR REPLACE TABLE edges AS
SELECT subject, object  -- Include predicate if it's used in filtering
-- NERSC
-- FROM read_csv('data/merged/merged_uniprot_bacdive/merged-kg_uniprot_bacdive_edges.tsv', filename=true, union_by_name=true)
FROM read_csv('data/merged/wuniprot_12k/merged-kg_edges.tsv', filename=true, union_by_name=true)
WHERE (subject LIKE 'Proteomes:%' AND object LIKE 'NCBITaxon:%')
   OR (subject LIKE 'UniprotKB:%'
   AND object LIKE 'Proteomes:%')
   OR (subject LIKE 'UniprotKB:%'
   AND object LIKE 'EC:%');

-- Step 1: Filter Proteomes to NCBITaxon directly into a temporary table
CREATE TEMPORARY TABLE Step1 AS
SELECT e1.subject AS Proteomes, e1.object AS NCBITaxon
FROM edges e1
WHERE e1.subject LIKE 'Proteomes:%'
  AND e1.object LIKE 'NCBITaxon:%';

-- Creating a subset of `edges` that only includes relevant 'UniprotKB' entries that have a corresponding match in `Step1`
CREATE TEMPORARY TABLE FilteredUniprotKB AS
SELECT subject AS UniprotKB, object AS Proteomes
FROM edges
WHERE subject LIKE 'UniprotKB:%';

-- Add an index on `Proteomes` if possible to speed up the join
CREATE INDEX IF NOT EXISTS idx_proteomes ON FilteredUniprotKB(Proteomes);

-- Perform the join only on pre-filtered and indexed data
CREATE TEMPORARY TABLE Step2 AS
SELECT 
    f.UniprotKB, 
    f.Proteomes, 
    s1.NCBITaxon
FROM 
    FilteredUniprotKB f
JOIN 
    Step1 s1 ON f.Proteomes = s1.Proteomes;


-- Drop the filtered table if not needed anymore
DROP TABLE FilteredUniprotKB;


-- CREATE TEMPORARY TABLE Step2 AS
-- SELECT e2.subject AS UniprotKB, e2.object AS Proteomes, s1.NCBITaxon
-- FROM edges e2
-- JOIN Step1 s1 ON e2.object = s1.Proteomes
-- WHERE e2.subject LIKE 'UniprotKB:%';

DROP TABLE Step1;

CREATE TEMPORARY TABLE EC_Edges AS
SELECT subject, object
FROM edges
WHERE object LIKE 'EC:%';

-- Handling EC Edges
CREATE TEMPORARY TABLE EC_Joined AS
SELECT s2.NCBITaxon, ec.subject AS UniprotKB, ec.object AS EC
FROM EC_Edges ec
JOIN Step2 s2 ON ec.subject = s2.UniprotKB;

-- Output EC results to a TSV file and drop temporary tables
COPY EC_Joined TO 'NCBITaxon_to_EC.tsv' (FORMAT CSV, DELIMITER '\t', HEADER);
DROP TABLE EC_Joined;
DROP TABLE EC_Edges;

-- As Step2 is no longer needed after processing all types, it can be dropped
DROP TABLE Step2;
