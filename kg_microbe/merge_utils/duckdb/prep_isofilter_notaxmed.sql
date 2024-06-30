create or replace table edges as select * from read_csv('./merged-kg_edges.tsv', filename=true, union_by_name=true);

WITH isolation_sources AS (
	    SELECT object
	    FROM edges
	    WHERE object LIKE 'isolation_source:%'
),
isolation_counts AS (
	    SELECT object, COUNT(*) as count
	    FROM isolation_sources
	    GROUP BY object
),
objects_to_remove AS (
	    SELECT object
	    FROM isolation_counts
	    WHERE count < 3
)
DELETE FROM edges
WHERE object IN (SELECT object FROM objects_to_remove);


COPY edges TO 'merged-kg_edges_filteriso.tsv' (HEADER, DELIMITER '\t');


-- Step 2: Delete rows with medium: objects and biolink:occurs_in predicate
DELETE FROM edges
WHERE object LIKE 'medium:%' AND predicate = 'biolink:occurs_in';

-- Step 3: Save the updated table to a new file
COPY edges TO 'merged-kg_edges_filteriso_notaxmed.tsv' (HEADER, DELIMITER '\t');



-- Step 1: Identify unique subjects and objects in the edges table
CREATE TEMP TABLE subjects_and_objects AS
SELECT DISTINCT subject AS node FROM edges
UNION
SELECT DISTINCT object AS node FROM edges;

-- Step 2: Create a table for filtered nodes
CREATE TEMP TABLE filtered_raw_nodes AS
SELECT *
FROM raw_nodes
WHERE id IN (SELECT node FROM subjects_and_objects);

-- Step 2: Save the updated raw_nodes table to a new file
COPY filtered_raw_nodes TO 'merged-kg_nodes_filteriso.tsv' (HEADER, DELIMITER '\t');
