# Independent pin-upgrade audit for the active m5 rebuild

Read-only audit on 2026-11-05; implementation remains owned by the native m5 KG-Microbe session. Treat these as upgrade dependencies and review findings to triage in the KG-Microbe branch. Retain evidence and file issues for actionable review findings. The final local graph merge remains conditional on the new pins and their reviewed bindings passing admission.

Official latest versions were independently confirmed: Biolink v4.4.6 (2026-10-09), ROBOT v1.9.11 (2026-10-01), Rhea 143 (2026-11-04).

## Biolink

- Update pyproject.toml, poetry.lock, and all three download.yaml artifacts: biolink-model.yaml, attributes.yaml, predicate_mapping.yaml. Biolink 4.4.6 requires linkml-runtime >=1.11.1,<2; existing lock has 1.10.0. Python 3.10 is supported. Use the isolated environment, preserving the original shared environment.
- mappings/ncit_eight_categories.json and mesh_finite_category_dispositions.json bind the complete model SHA, version, and selected definitions, with canonical policy digest guards. Compare the actual selected classes before updating bindings and fixtures.
- Review finite_envo_po_category_dispositions.json, native_ro_predicate_dispositions.json, ontology_parent_dispositions.json, UBERON temporal rationale, and kg_microbe/profiles/ingredient_kgx_v1.yaml. Native RO also hardcodes a reviewed model identity. Preserve historical evidence with an explicit carry-forward assessment; avoid global version replacement.
- mappings/kgxval_dispositions_v1.json and kgxval_reference_dispositions_v1.json describe a historical graph/schema/predicate-map epoch. kgm_validation_profile.py explicitly requires 4.4.2; new 4.4.6 diagnostics need their own reviewed profile and cannot inherit the historical assessments.
- Relevant checks: schema/hierarchy, NCIT/MeSH, native RO, finite categories, ontology parent, ingredient KGX; an actual 4.4.6 class comparison is essential beyond synthetic fixtures.

## ROBOT

- Upgrade both jar and wrapper URLs. Keep the native JAXP/offline-catalog handling; Java 27 satisfies the new Java 11 minimum.
- `_derived_json_is_stale()` compares ontology release stamps but not ROBOT identity. A jar upgrade alone may silently reuse old converted JSON. Preserve old evidence and explicitly regenerate staged derived inputs under 1.9.11. Address or document this cache invalidation gap.
- Use UPA for one conversion canary before the conversion batch. The reviewed policy binds upa.json bytes (`cff92938a092dcc2e4e2e1a17266417edeacba8e7b9f51b3f183066a80fdb8bd`). Compare native records, order-dependent witnesses, GO routes and exclusions. Separate serialization changes from semantic changes before any policy repin. ROBOT 1.9.9 changed OBOGraphs to 0.3.2; 1.9.11 changed Jackson/catalog handling.
- The changed jar invalidates strict GO toolchain evidence: rebuild GO rather than restamp the record.
- Relevant checks: pin/atomic output, SemSQL toolchain, derived JSON refresh, UPA route/public scope, release preflight. Follow with complete ontology canary and admission before downstream producers.

## Rhea

- Official old_releases/143.tar.bz2 exists (~404 MB). Release notes report 19,005 reactions. The announced pH-7.3 mapping change is for 144, not 143.
- Update download.yaml quarantine URL/local filename and mappings/rhea_release.json using the actual archive members' measured hashes and sizes. Preserve raw/rhea 142; the stager rejects differing existing files, so admit 143 into a fresh generation.
- Revalidate mappings/rhea_legacy_xref_dispositions.json against actual 143 native evidence before changing its selected snapshot binding. Preserve all six historical exclusions and seven directional GO annotations, unless explicit evidence supports a reviewed scientific change. Do not use the synthetic `empty_legacy_policy` or zero-exclusion waiver.
- Excluded subjects: RHEA:15929, 19441, 22140, 28338, 47152, 58872. Check exact focal/related labels, Approved status, required EC/GO assertions, absence of both original and separately normalized excluded assertions on the original subject, and all seven exact directional variants/master/LR-RL substrate-product roles.
- Preserve historical 141 evidence and separate GO:0018581 -> GO:0047074 normalization evidence. Do not relabel those historical facts as new validation against rebuilt GO bytes. Review selected-context prose that names 142.
- legacy_xrefs.py's hardcoded 142 ID/hash protect against zero-count history waivers; they do not prohibit a valid six-row 143 policy. Extend protection to 143 while retaining 142 coverage.
- stage_snapshot._validate_pair checks native structural joins but DOES NOT run the legacy audit. A staging receipt alone is not release admission. Require load_legacy_xref_audit on consumed 143 RDF and the full producer's reaction/legacy audits.
- Compare native families, statuses, participation routes and exact-subject EC/GO assertions using a retained candidate-review helper. Changed witnesses, restored excluded assertions, unhandled participant structures, or missing labels must be surfaced rather than suppressed.
- Relevant checks: snapshot staging, native inputs/RDF/transform, reaction families, legacy xrefs, label inputs, scalar transport, emitter review; then normal final gates.

## Sources

- https://github.com/biolink/biolink-model/releases/tag/v4.4.6
- https://raw.githubusercontent.com/biolink/biolink-model/v4.4.6/pyproject.toml
- https://github.com/ontodev/robot/releases/tag/v1.9.11
- https://github.com/ontodev/robot/releases/tag/v1.9.9
- https://ftp.expasy.org/databases/rhea/rhea-release.properties
- https://ftp.expasy.org/databases/rhea/old_releases/
- https://ftp.expasy.org/databases/rhea/rhea_news.html#2026/11/04/release
