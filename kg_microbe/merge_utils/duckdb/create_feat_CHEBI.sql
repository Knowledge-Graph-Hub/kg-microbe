-- Setting up environment
SET temp_directory='/Users/marcin/Documents/tmp/duckdb';
PRAGMA memory_limit='40GB'; 

-- Load edges with relevant filters, including RHEA to CHEBI
CREATE OR REPLACE TABLE edges AS
SELECT subject, object
FROM read_csv('data/merged/uniprot_bacdive/merged-kg_uniprot_bacdive_edges.tsv', filename=true, union_by_name=true)
WHERE (subject LIKE 'Proteomes:%' AND object LIKE 'NCBITaxon:%')
   OR (subject LIKE 'UniprotKB:%' AND object LIKE 'Proteomes:%')
   OR (subject LIKE 'UniprotKB:%' AND object LIKE 'RHEA:%')
   OR (subject LIKE 'RHEA:%' AND object LIKE 'CHEBI:%');  -- Include RHEA to CHEBI


-- Create Step1: Proteomes to NCBITaxon
CREATE TEMPORARY TABLE Step1 AS
SELECT subject AS Proteomes, object AS NCBITaxon
FROM edges
WHERE subject LIKE 'Proteomes:%' AND object LIKE 'NCBITaxon:%';


-- Create FilteredUniprotKB: Subset of edges for UniprotKB
CREATE TEMPORARY TABLE FilteredUniprotKB AS
SELECT subject AS UniprotKB, object AS Proteomes
FROM edges
WHERE subject LIKE 'UniprotKB:%';


-- Create Step2: Linking UniprotKB with NCBITaxon through Proteomes
CREATE TEMPORARY TABLE Step2 AS
SELECT f.UniprotKB, f.Proteomes, s1.NCBITaxon
FROM FilteredUniprotKB f
JOIN Step1 s1 ON f.Proteomes = s1.Proteomes;

DROP TABLE Step1;


-- Prepare RHEA_Edges
CREATE TEMPORARY TABLE RHEA_Edges AS
SELECT subject, object AS RHEA
FROM edges
WHERE object LIKE 'RHEA:%' AND subject IN (SELECT UniprotKB FROM FilteredUniprotKB);

DROP TABLE FilteredUniprotKB;


-- Prepare CHEBI_Edges
CREATE TEMPORARY TABLE CHEBI_Edges AS
SELECT subject AS RHEA, object AS CHEBI
FROM edges
WHERE object LIKE 'CHEBI:%' AND subject IN (SELECT RHEA FROM RHEA_Edges);


-- Join RHEA with CHEBI to create CHEBI_Joined
CREATE TEMPORARY TABLE CHEBI_Joined AS
SELECT DISTINCT s2.NCBITaxon, chebi.CHEBI
FROM CHEBI_Edges chebi
JOIN RHEA_Edges rhea ON chebi.RHEA = rhea.RHEA
JOIN Step2 s2 ON rhea.subject = s2.UniprotKB;


-- Split CHEBI_Joined into two parts and save each to TSV
-- Part 1: Even hash of NCBITaxon
CREATE TEMPORARY TABLE CHEBI_Joined_Part1 AS
SELECT DISTINCT NCBITaxon, CHEBI
FROM CHEBI_Joined
WHERE abs(hash(NCBITaxon) % 2) = 0;

COPY CHEBI_Joined_Part1 TO 'NCBITaxon_to_CHEBI_Part1.tsv' (FORMAT CSV, DELIMITER '\t', HEADER);

DROP TABLE CHEBI_Joined_Part1;


-- Part 2: Odd hash of NCBITaxon
CREATE TEMPORARY TABLE CHEBI_Joined_Part2 AS
SELECT DISTINCT NCBITaxon, CHEBI
FROM CHEBI_Joined
WHERE abs(hash(NCBITaxon) % 2) = 1;

COPY CHEBI_Joined_Part2 TO 'NCBITaxon_to_CHEBI_Part2.tsv' (FORMAT CSV, DELIMITER '\t', HEADER);


-- Clean up
DROP TABLE CHEBI_Joined_Part2;
DROP TABLE CHEBI_Joined;
DROP TABLE CHEBI_Edges;
DROP TABLE RHEA_Edges;
DROP TABLE Step2;