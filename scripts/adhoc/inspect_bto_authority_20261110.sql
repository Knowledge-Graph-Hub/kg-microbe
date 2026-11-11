-- Purpose: inspect existing declared BTO SemSQL label authority for EdgeMech #36.
-- Input: KG-Microbe data/raw/bto.db opened sqlite3 -readonly. Output: stdout only.
-- Date: 2026-11-10.
SELECT subject,predicate,object,value FROM statements
WHERE subject IN ('BTO:0001481','BTO:0001253','BTO:0000545','BTO:0000763')
AND predicate IN ('rdf:type','rdfs:label','owl:deprecated');
SELECT count(DISTINCT subject) AS named_bto_classes FROM statements
WHERE predicate='rdfs:label' AND subject LIKE 'BTO:%';
SELECT subject,predicate,object,value FROM statements
WHERE predicate IN ('owl:versionIRI','owl:versionInfo');
