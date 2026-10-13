# Finite imported native class authorities (#1291)

These are immutable excerpts of the selected native FOODON, UBERON, PATO and
ENVO snapshots. Every retained node and edge object is a verbatim UTF-8 fragment
of its native source, including definitions, comments and spelling. Only the
outer graph wrapper is newly assembled. `origin.json` distinguishes each full
native file SHA-256 from the excerpt SHA-256. Since policy version 2 (#1420),
production binds each converted JSON to the SHA-256 of the OWL release file it
was converted from, to the release it declares (`meta.version`), and to a
canonical digest of the reviewed decisions computed from its native content. The
excerpts declare the reviewed release and yield the reviewed decisions, so tests
substitute only the release-file binding, letting each excerpt stand for its own
release file.

The exact reviewed cohort is 75 GAZ geographic classes from FOODON, three
`OBO:COB_*` material classes from UBERON, and two PCO population/community
qualities from PATO: 80 identifiers, 150 historical diagnostic endpoint sides.
Every named asserted ancestor and each complete native declaration is retained.
Thirteen actual native negative controls test finite scope. ENVO is a negative
control authority, not the selected source for PCO:0000003/4.

The policy preserves graph IDs and all assertions. It neither equates COB with
ChEBI nor promotes an ontology class to an individual material instance. The
two PCO qualities project to Attribute's property/characteristic semantics;
Biolink 4.4.2 still requires `has attribute type`. No arbitrary type, self-type,
schema modification or strict-conformance claim is supplied here. Incident
edge validation and ontology-class representation remain separate questions.

Native extraction was independently checked against the unchanged local full
files before implementation: 100 evidence tests, 328 verified native fragments.
The preparation script, byte offsets and full native evidence are retained in
the review artifact `resolve93-20260930.2qMze1/import-authority-1291-candidate/`.
Repository tests use these offline fixtures and never depend on that artifact.
