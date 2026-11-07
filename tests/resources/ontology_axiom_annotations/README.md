# Native axiom annotation excerpts

These are literal selected OBOJSON records from the reviewed ROBOT 1.9.11
candidate conversions of the unchanged UBERON and FOODON OWL authorities.
`origin.json` binds the original OWL, conversion JAR/wrapper, complete candidate
JSON, and fixture bytes. All selected edge records and available endpoint node
records are copied intact; these are excerpts, not complete ontologies.

UBERON evidence annotations have five distinct literal values in the complete
candidate: `definitional` (64), `ISBN:0486692132` (1), `cjm` (1),
`PMID:3709965` (1), and `NAS` (1). The fixture includes one original assertion
for each. These heterogeneous oboInOwl annotations are carried as an ordered
JSON text array in `obo_axiom_evidence`, alongside unchanged original `meta`;
they do not establish Biolink InformationContentEntity objects. No citation is
fabricated or discarded. Other reviewed aliases remain source annotations;
`_annotations` uses an ordered JSON array of native KGX annotation strings.

The candidate inventories and review are retained under
`data/rebuild-evidence/20261105/upgrades/biolink/`. Historical ontology and
Biolink 4.4.2 fixtures are unchanged. See upgrade issues #1729, #1732, #1736.
