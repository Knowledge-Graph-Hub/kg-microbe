SET temp_directory='/Users/marcin/Documents/tmp/duckdb';

create or replace table edges as select * from read_csv('./data/merged/uniprot_bacdive/merged_uniprot_bacdive/merged-kg_uniprot_bacdive_edges.tsv.gz', filename=true, union_by_name=true); 

#NERSC
create or replace table edges as select * from read_csv('data/merged/merged_uniprot_bacdive/merged-kg_uniprot_bacdive_edges.tsv', filename=true, union_by_name=true);
SET temp_directory='$SCRATCH/TMP/';


SELECT DISTINCT
      split_part(subject, ':', 1) AS subject_prefix,
      split_part(object, ':', 1) AS object_prefix
  FROM edges
  WHERE split_part(subject, ':', 1) NOT LIKE 'API_%'
    AND split_part(object, ':', 1) NOT LIKE 'API_%';



###GIVES OUT OF MEME!!!
CREATE TABLE final_relationships AS
  SELECT DISTINCT
      e1.subject AS NCBITaxon_subject,
      e4.object AS final_object
  FROM
      edges e1
  JOIN edges e2 ON e1.object = e2.subject
  JOIN edges e3 ON e2.object = e3.subject
  JOIN edges e4 ON e3.object = e4.subject
  WHERE
      e1.subject LIKE 'NCBITaxon:%'
      AND e2.subject LIKE 'UniprotKB:%'
      AND e3.subject LIKE 'Proteomes:%'
      AND e4.subject LIKE 'NCBITaxon:%'
      AND (
          e4.object LIKE 'EC:%'
          OR e4.object LIKE 'GO:%'
          OR e4.object LIKE 'CHEBI:%'
          OR e4.object LIKE 'RHEA:%'
      );



drop table final_relationships;
drop view step1;
drop view step2;
drop view step3;



-- Create indexes on the columns used in joins and where clauses (if not already indexed)
-- For DuckDB, you might skip this step as it does not support traditional indexing like other RDBMS but understanding its data skipping and partitioning can be beneficial

-- Step 1: Filter Proteomes to NCBITaxon directly into a temporary table
CREATE TEMPORARY TABLE Step1 AS
SELECT e1.subject AS Proteomes, e1.object AS NCBITaxon
FROM edges e1
WHERE e1.subject LIKE 'Proteomes:%'
  AND e1.object LIKE 'NCBITaxon:%';

-- Step 2: Join UniprotKB to Proteomes, carry NCBITaxon forward
CREATE TEMPORARY TABLE Step2 AS
SELECT e2.subject AS UniprotKB, e2.object AS Proteomes, s1.NCBITaxon
FROM edges e2
JOIN Step1 s1 ON e2.object = s1.Proteomes
WHERE e2.subject LIKE 'UniprotKB:%';

DROP TABLE Step1; -- Drop as soon as it's no longer needed

-- Create a temporary table for filtered edges data
CREATE TEMPORARY TABLE FilteredEdges AS
SELECT subject, object
FROM edges
WHERE object LIKE 'EC:%'
   OR object LIKE 'GO:%'
   OR object LIKE 'RHEA:%';

-- Reduce the size of data to be joined by filtering necessary objects first
CREATE TEMPORARY TABLE Step3 AS
SELECT s2.NCBITaxon, fe.subject AS UniprotKB, fe.object AS FinalObject
FROM FilteredEdges fe
JOIN Step2 s2 ON fe.subject = s2.UniprotKB;

-- Drop the intermediate filtered table as it's no longer needed
DROP TABLE FilteredEdges;

DROP TABLE Step2; -- Drop as soon as it's no longer needed

-- Step 4: Final Table Creation
CREATE TABLE final_relationships AS
SELECT DISTINCT
    NCBITaxon,
    FinalObject
FROM Step3;

DROP TABLE Step3; -- Drop to free up memory


COPY final_relationships TO 'uniprot_bacdive_taxa_genome_feat.tsv' (FORMAT CSV, DELIMITER '\t', HEADER);



select * from final_relationships;


