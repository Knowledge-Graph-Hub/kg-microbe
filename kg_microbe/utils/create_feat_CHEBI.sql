-- SET temp_directory='/Users/marcin/Documents/tmp/duckdb';
-- PRAGMA memory_limit='30GB'; 

-- Extract only the necessary edges from the CSV including predicate information
CREATE OR REPLACE TABLE edges AS
SELECT subject, predicate, object
FROM read_csv('data/merged/uniprot_bacdive/merged-kg_uniprot_bacdive_edges.tsv', filename=true, union_by_name=true)
WHERE (subject LIKE 'Proteomes:%' AND object LIKE 'NCBITaxon:%')
   OR (subject LIKE 'UniprotKB:%' AND object LIKE 'Proteomes:%')
   OR (subject LIKE 'UniprotKB:%' AND object LIKE 'RHEA:%')
   OR (subject LIKE 'RHEA:%' AND object LIKE 'CHEBI:%' AND predicate = 'biolink:has_output');

-- Step 1: Filter Proteomes to NCBITaxon directly into a temporary table
CREATE TEMPORARY TABLE Step1 AS
SELECT subject AS Proteomes, object AS NCBITaxon
FROM edges
WHERE subject LIKE 'Proteomes:%' AND object LIKE 'NCBITaxon:%';

-- Create a subset of `edges` that only includes relevant 'UniprotKB' entries that have a corresponding match in `Step1`
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
DROP TABLE Step1;

-- Retrieve RHEA to CHEBI relationships where the predicate is 'biolink:has_output'
CREATE TEMPORARY TABLE CHEBI_Edges AS
SELECT subject, object
FROM edges
WHERE object LIKE 'CHEBI:%' AND predicate = 'biolink:has_output';

-- Handling RHEA to CHEBI edges
CREATE TEMPORARY TABLE CHEBI_Joined AS
SELECT DISTINCT s2.NCBITaxon, chebi.object AS CHEBI
FROM CHEBI_Edges chebi
JOIN Step2 s2 ON chebi.subject = s2.UniprotKB;

-- Output CHEBI results to a TSV file and drop temporary tables
COPY CHEBI_Joined TO 'NCBITaxon_to_CHEBI.tsv' (FORMAT CSV, DELIMITER '\t', HEADER);

DROP TABLE CHEBI_Joined;
DROP TABLE CHEBI_Edges;

-- As Step2 is no longer needed after processing all types, it can be dropped
DROP TABLE Step2;
