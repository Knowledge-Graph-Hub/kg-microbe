# Evidence for the 2026-11-05 M5 input upgrades

These are unchanged copies of compact review artifacts from the isolated rebuild's
`data/rebuild-evidence/20261105/` directory. `copied-evidence-manifest.json` records
each original relative path, byte count and SHA-256. The complete acquisition,
conversion, comparison, process and admission evidence remains in that run
location; large files are not copied into Git.

- The supplied independent audit identifies the required Biolink, ROBOT and Rhea
  review boundaries. Its original bytes are preserved.
- The independent Biolink audit verifies the current NCIT/MeSH bindings and the
  unchanged historical policy decisions. The fuller portable model and runtime
  comparison is `mappings/biolink_4_4_6_category_review.json`; immutable official
  schema fixtures are under `tests/resources/biolink_4_4_6/`.
- The Rhea assessment and selected-context comparison retain the actual six
  exclusions and seven directional witnesses. The current-policy check runs
  consumed-input readers against the actual candidate bytes. Its flags explicitly
  distinguish this review from a complete Rhea producer run. The label-gap delta
  records the missing labels tracked in issue #1733.
- The UBERON disposition and its independent audit bind the single unchanged DOI
  omission tracked in issue #1737. Complete-source annotation equality remains
  false; all new annotations must be source-backed and new omissions are refused.
- The activation audit records resolved helper findings. It is a code review,
  not a producer-completion receipt. Actual activation, canary and persisted
  admission outcomes are reported separately in the run report.

The FOODON cold-conversion comparison and complete retirement witnesses record
issue #1745's repair: all 607 retirements and 28 incident edges are source-backed,
and the existing category map and organism closure are unchanged. The copied
failed-admission receipt records the first canary's rejection; it must not be
read as successful completion. The failed fixture extraction and its later
source-derived correction are separately retained in the large run evidence.

Historical attributions, timestamps, candidate path names and status fields are
preserved as recorded. In particular, none of these documents converts a
historical kgxval v1 assessment into a Biolink 4.4.6 graph-validation profile.
No artifact here waives the unresolved MediaDive responses in issue #1734.

The successful retry is recorded separately in `ontology-admission.json`: all
28 nonempty ontology graph files and 194 admitted artifacts passed current
production verification. This establishes ontology-source admission only; the
dependent rebuild and final graph remain held by MediaDive issue #1734.
