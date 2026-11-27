# Private final-combined MIM compatibility

The final-combined consumer is an additional admission check on an actual
`StableSourceCandidate`. It requires all three native capabilities:
`reviewed-source-bindings-v1`, `culturemech-intake-v3-replay-v1` and
`cm-v3-kgm-source-conservation-v1`. The selected native `consumer_claims`
executes `validate_candidate`, including inverse source reconstruction, before
KGM consumes its claims. There is no new manifest proof object or trusted
success flag. An amended capability list cannot replace native validation.

This contract is implemented against MIM commit
`68bba8a68c79049e7602e4b10a12b1baf700d840` (PR1556). Its genuine small fixtures
exercise actual native producers and the archived CM producer. Their scientific
judgments are synthetic test controls, never certification of the real campaign.

## Explicit selection

Keep the existing exact native candidate selection: product root/revision,
producer root/revision and file hashes, maintained runtime identity, source
review/output hashes, stable KGX profile, and explicitly `required/v1` or
`absent/v1` companion policy. Never infer absent from missing companion files.

The separate final integration selection uses:

- `contract`: `kg-microbe-stable-source-integration/v2`;
- `mode`: `final_combined_candidate`;
- `culturemech`: the four exact path/SHA256 declarations `source_manifest`,
  `prepared_intake`, `reviewed_intake`, `binding_review`;
- `kgm_source_receipt`, `current_kgm`, `reconciliation`, `expected_counts`:
  exact selected historical receipt/root/full revision, complete CM row ledger
  and all five accepted CM counts;
- `native_occurrence_payload_column`: `original_occurrence_json`;
- `combined_source_scope`: the native profile's exact 13 authority declarations
  and 11 artifact paths, independently selected and joined to the same source;
- `combined_source_declaration`: the path/hash of canonical native declaration
  bytes containing that exact `original_source_scope`;
- `owner_transitions`: `null` when nothing changed, or the explicitly selected
  reviewed transition ledger described below.

The 13 authority roles are `culturemech_package`, `kg_source_selection`,
`kg_source_manifest`, `kg_row_reconciliation`, `kg_full_node_ledger`,
`kg_full_row_ledger_json`, `kg_full_row_ledger_tsv`, `kg_transport_manifest`,
`kg_nodes`, `kg_occurrences`, `original_case_ledger`, `original_origin_ledger`
and `original_eligibility_intake`. The 11 artifact roles are `cm_nodes`,
`cm_occurrences`, `cm_raw_row_map`, `cm_case_crosswalk`, `combined_nodes`,
`combined_occurrences`, `combined_position_map`, `cm_reconciliation`,
`kg_provider_cases`, `historical_obligations` and `obligation_crosswalk`.

Both actual native scientific YAML/Markdown report pairs must select the whole
CM package and KG receipt closure, authority/declaration/artifact inputs, current
owner/registry/lifecycle inputs and additional review inputs. Native report
`source.inputs` entries retain their actual `path`, `sha256`, `role` schema.
Only the actual report pairs are excluded from their own required hash union to
avoid cycles. Original and newly emitted physical coordinates remain distinct;
all occurrence multiplicities and converse coverage are checked.

The existing v1 `diagnostic_only` route remains available for historical checks.
`verify_final_combined` refuses it. Neither route changes
`PRIVATE_NOT_KG_ACCEPTED`, unresolved lineage, unsupported assertions, P3556 or
other scientific holds. Inventory membership, supported identity, REMOVE,
displacement, zero concentration or experimental stage cannot create positive
medium-presence edges. Reloading a persisted candidate requires an explicit
repeat of final integration admission.

## Reviewed binding transitions

KGM's `kg-microbe-cm-binding-transitions/v1` ledger is a consumer extension; it is
not an upstream approval already supplied by PR1556. A real changed owner or
disposition requires actual primary and independent skeptical review. Do not
manufacture those judgments from this format or from synthetic fixtures.

The ledger has exactly `contract`, `culturemech`, `native_source` and `entries`.
`culturemech` repeats the four selected declarations. `native_source` declares
current combined `nodes` and `occurrences` by path/hash. Each entry contains:

- `case_id`;
- `before`: full historical `binding_row_sha256`, `binding_decision_sha256`,
  `disposition`, `owner_record`, `owner_record_sha256`;
- `after`: actual current `source_id`, integer `source_position`, full
  `payload_sha256`, `disposition`, `owner_record`, `owner_record_sha256`;
- `evidence`: nonempty distinct path/hash declarations of captured substantive
  source evidence supporting this precise transition.

Put ledger and evidence into the native request's generic `inputs`, not its
closed `ledger_inputs` registry/lifecycle dictionary. Both genuine scientific
reports include these files in `source.inputs`. Each actual identity assessment
must include a `cm_binding_transition_sha256` dimension whose value is the
canonical SHA256 of that complete entry, a nonempty definition, and evidence IDs
binding the ledger plus every captured substantive source. Evidence must support
the claim and be primary source, database or authority material; copied owner,
ledger or current review bytes do not qualify, even under a different filename.
The two reports must use distinct reviewer identities and an independent skeptic.
The ledger contains no report hashes, avoiding a circular dependency.

Exact historical owners are read through the accepted CM package; current owners
are read through the selected native record inputs. Ownerless destinations must
remain WITHHOLD. Native support requires both reviews and retains actual holds
and mapping status. Every changed binding, including a case with zero
occurrences, requires one consumed entry. Extra, unchanged, duplicate, stale or
unreviewed entries fail. No shared identifier alone authorizes a transition.

## Isolated final-bundle command

After the owner provides certified current products and scientific reviews,
prepare and independently inspect the two selection JSON files above, then run:

```bash
poetry run python scripts/check_stable_mim_final_bundle.py \
  --consumer-head FULL_REVIEWED_KGM_COMMIT \
  --selection /durable/run/native-selection.json \
  --selection-sha256 ACTUAL_NATIVE_SELECTION_SHA256 \
  --integration-selection /durable/run/final-integration-selection.json \
  --integration-sha256 ACTUAL_INTEGRATION_SELECTION_SHA256 \
  --output /durable/run/new-final-bundle-canary
```

The command checks the imported module origin and clean committed head, executes
native admission, persists/reloads/re-admits, verifies complete candidate TSV and
archive projection, and retains both native executions and semantic audit. It
requires a new output outside selected source/producer/KG checkouts. It does not
install mappings, run transforms, merge a graph, or certify a release. The private
projection archive is not a finalized canonical graph archive. Subsequent model,
producer rebuild, canonical merge and release gates still require their own
approved stage. Preserve actual failed and successful command logs externally;
a stored result alone does not certify an execution.

## Validation and remaining upstream prerequisite

Use focused controls while editing. Before final PR validation, format and
commit the candidate, then use the repository's single-suite gate:

```bash
MIM_STABLE_TEST_PRODUCTS=/durable/native-baseline \
MIM_STABLE_TEST_PRODUCER=/durable/pinned-native-code \
MIM_STABLE_TEST_PYTHON=/maintained/native-python \
poetry run python scripts/run_pr_gates.py final-combined --require-stable-mim
```

Required mode must run the complete `tests` root with both historical native
source and new native combined groups; skips, xfails, collection filtering or
missing prerequisites do not count as acceptance. Ordinary CI may skip native
controls when those explicitly selected prerequisites are unavailable. Avoid a
separate full pytest run.

The intentionally historical f10 KGM receipt and previously consumed MIM
`0dac278466699129a083343a921c2e0ca18a9ab4` remain historical evidence, not current
master inputs. Actual final selection must preserve the accepted CM source,
prepared/reviewed intake and binding-review pins separately from its package
hash. Code compatibility and tiny native controls do not replace the one real
final-artifact canary. That canary waits for certified current MIM artifacts,
complete captured closure and any genuinely reviewed owner transitions.
