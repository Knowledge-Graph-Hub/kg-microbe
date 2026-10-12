-- Synthetic SemSQL query fixture, not a biological NCBITaxon assertion.
CREATE TABLE statements (stanza TEXT, subject TEXT, predicate TEXT, object TEXT, value TEXT, datatype TEXT, language TEXT);
INSERT INTO statements VALUES ('obo:ncbitaxon.owl','obo:ncbitaxon.owl','owl:versionInfo',NULL,'fixture-2026-10-01',NULL,NULL);
CREATE TABLE entailed_edge (subject TEXT, predicate TEXT, object TEXT);
INSERT INTO entailed_edge VALUES ('NCBITaxon:20','rdfs:subClassOf','NCBITaxon:10');
INSERT INTO entailed_edge VALUES ('NCBITaxon:30','rdfs:subClassOf','NCBITaxon:999');

-- Synthetic literal declarations add native-eligibility context only.
-- Existing entailed_edge rows above are unchanged deposit-resolver controls.
CREATE INDEX statements_spv ON statements(subject,predicate,value);
CREATE INDEX statements_p ON statements(predicate);
INSERT INTO statements VALUES ('NCBITaxon:1','NCBITaxon:1','rdf:type','owl:Class',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:1','NCBITaxon:1','rdfs:label',NULL,'Fixture root',NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:2','NCBITaxon:2','rdf:type','owl:Class',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:2','NCBITaxon:2','rdfs:label',NULL,'Bacteria',NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:2','NCBITaxon:2','obo:ncbitaxon#has_rank','NCBITaxon:superkingdom',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:2','NCBITaxon:2','rdfs:subClassOf','NCBITaxon:1',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:10','NCBITaxon:10','rdf:type','owl:Class',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:10','NCBITaxon:10','rdfs:label',NULL,'Fixture ancestor',NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:10','NCBITaxon:10','obo:ncbitaxon#has_rank','NCBITaxon:genus',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:10','NCBITaxon:10','rdfs:subClassOf','NCBITaxon:2',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:20','NCBITaxon:20','rdf:type','owl:Class',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:20','NCBITaxon:20','rdfs:label',NULL,'Fixture child',NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:20','NCBITaxon:20','obo:ncbitaxon#has_rank','NCBITaxon:species',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:20','NCBITaxon:20','rdfs:subClassOf','NCBITaxon:10',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:30','NCBITaxon:30','rdf:type','owl:Class',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:30','NCBITaxon:30','rdfs:label',NULL,'Fixture other',NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:30','NCBITaxon:30','obo:ncbitaxon#has_rank','NCBITaxon:species',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:30','NCBITaxon:30','rdfs:subClassOf','NCBITaxon:999',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:99','NCBITaxon:99','rdf:type','owl:Class',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:99','NCBITaxon:99','rdfs:label',NULL,'Fixture special',NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:99','NCBITaxon:99','obo:ncbitaxon#has_rank','NCBITaxon:phylum',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:99','NCBITaxon:99','rdfs:subClassOf','NCBITaxon:2',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:99','NCBITaxon:99','oio:hasExactSynonym',NULL,'Actinobacteria',NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:999','NCBITaxon:999','rdf:type','owl:Class',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:999','NCBITaxon:999','rdfs:label',NULL,'Fixture other parent',NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:999','NCBITaxon:999','obo:ncbitaxon#has_rank','NCBITaxon:genus',NULL,NULL,NULL);
INSERT INTO statements VALUES ('NCBITaxon:999','NCBITaxon:999','rdfs:subClassOf','NCBITaxon:2',NULL,NULL,NULL);
