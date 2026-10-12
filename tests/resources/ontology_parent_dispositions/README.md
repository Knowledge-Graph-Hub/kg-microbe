# Finite native-parent evidence

These are immutable **excerpts**, not complete source ontology releases. The
associated policy covers exactly fourteen named parent claims: thirteen from
FOODON and one imported PCO claim from ENVO. The older FOODON kernel policy,
its twenty-two category decisions, and its one quarantine remain separate.

`origin.json` records the original full-source hashes and coordinates. The
FOODON JSON/OWL excerpts retain complete selected class declarations, named
ancestry, equivalent/restriction expressions, and annotated axioms. The ENVO
excerpt retains the full selected OBO Graph declarations and relationships.
Parsed XML structure is conserved; the excerpt is not asserted to be a
byte-identical slice of the original RDF/XML document.

The parent policy pins 103 incident source assertions, preserving their
multiplicity and full scientific/provenance payloads: fourteen are quarantined
and eighty-nine retained. It also pins descendant/context boundaries and six
explicit uncertain meat-classification controls. None of these new decisions
changes a node category. Existing native OWL intersections are preserved and
described in the audit; deleting a named TSV parent is not a claimed upstream
OWL logical repair.

`lifecycle/` adds genuine native declarations/ancestry and a PO excerpt needed
to exercise ordinary producer finalization offline. These extra declarations
do not expand the quarantine or category policy. Its separate origin file
records complete source coordinates and before/after input pins; no required
PO declaration was absent from the selected native source.

Tests use the complete locally pinned model and predicate-map fixtures already
under `tests/resources/ingredient_bundle/native/`. No remote fallback is
allowed. A KGX-generated UUID is preserved only as converter trace: its exact
original row is bound to a hash-addressed producer input receipt, and every
scientific/provenance field is independently compared with native evidence.
The UUID is not claimed as a recomputable primary-ontology assertion identifier.
