# Stable MIM source candidate contract

`kg_microbe.utils.stable_source_candidate.StableSourceCandidate` is an additive,
opt-in consumer for actual native MIM source-binding products, with an explicitly
selected required-companion or source-only capability.
Its status is `PRIVATE_NOT_KG_ACCEPTED`. It does not activate a production input,
run a transform or merge, change any existing mapping selection, or rebuild KG.
The existing filename-based ingredient profile and biomedical `MIM` namespace
remain unchanged.

## Admission and selection

Supply a selection JSON and its independently chosen SHA-256 to the constructor.
The selection has these exact fields:

| Field | Required value |
| --- | --- |
| `contract` | `kg-microbe-stable-source-candidate/v1` |
| `mode` | `candidate_only` |
| `companion_mode` | Exactly `required/v1` or `absent/v1` |
| `profile_sha256` | Exact selected `stable_source_kgx_v1.yaml` bytes |
| `mim_root`, `mim_revision` | Actual data root and full current Git revision |
| `producer_root`, `producer_revision` | Actual selected native MIM code root and full revision |
| `producer_files` | Complete package/resource and native auxiliary path/hash map returned by the documented `producer_members` inventory |
| `python` | Explicit interpreter `path`, resolved `realpath`, executable `sha256`, and native `runtime` Python/package-version declaration |
| `source_review` | Root-relative `path` and exact `sha256` |
| `companion_review` | Required mode: same declaration; absent mode: explicitly `null` |
| `source_output` | Root-relative directory `path` and exact `manifest_sha256` |
| `companion_output` | Required mode: same declaration; absent mode: explicitly `null` |
| `lineage` | `null`, or `manifest` and `postimages` declarations, each with a root-relative `path` and `sha256` for the native frozen identity migration |

Selection hashes do not grant scientific approval. The adapter starts the selected
maintained MIM interpreter in an isolated, bytecode-cache-independent first-party
import context. Actual native source admission reconstructs every product from
the current source rows, occurrences, complete owner/registry inventory, original
independent scientific report pairs, external mapping partition and captured
producer/runtime context. Native SSSOM schema validation remains part of that
entry point in every mode. When required, the companion validator reconstructs every companion artifact and
checks its complete source archive against current root bytes and the same
external review. The companion producer's code fingerprints must match the
selected executing code.

`absent/v1` explicitly selects no companion delivery for this candidate. It does
not assert that no companion evidence exists elsewhere and does not fabricate a
validated empty legacy bundle. It emits no companion-only mapping, identifier,
product, occurrence, xref or scope authorization. All source-required evidence
remains mandatory, including any input named or typed as companion material.
Unknown modes, contradictory supplied declarations, and missing or invalid
required companions fail; no exception handler falls back to absent mode.

All selected file bytes and identities, complete product and owner-record inventories, executable
locator, producer inventory, and both Git revisions remain live checks before
and after validation and subsequent use. Symlinks, physical aliases, omitted
products, rehashed invented output, and late input changes fail closed.
Quoted multiline TSV cells retain their exact CRLF and literal comment-like lines.
Fresh export destinations must not overlap either native product directory in
either direction, including case and physical ancestor aliases; refusal occurs
before writing. Unicode spelling normalization is not used as an identity proof. Native
warnings remain in captured stderr; the child emits one JSON result on stdout.
The runtime declaration uses the native Python and package-version contract;
it does not claim to fingerprint every installed third-party package file.

## Independent assertion lanes

`resolve_source` uses only a native-supported source decision and its explicit
occurrence positions. It has no name fallback and does not use companion
identity authorization or an external target as a source identity. A reviewed
unmapped owner can therefore return its stable MIM identity with no ontology row.
Held or ownerless source cases remain withheld even when an independent external
or companion assertion exists.

`payload()` retains every native source decision, supported and withheld external
row, full external disposition, companion mapping/identifier/product/occurrence,
exact current owner YAML text and parsed identity fields, registry and lifecycle,
selected reviews, manifests and original generation provenance. `legacy_identifier_owners`
returns all explicitly retained alias owners. It never chooses among ambiguous
aliases or collapses distinct owners sharing an external ID.

The KG adapter passes its own explicit companion capability set to the selected
native MIM validator (#1859); upgrading MIM cannot silently expand KG support.
Unknown required capabilities fail before the native child runs. The optional
`retained-companion-obligations-v1` capability transports the complete native
`retained_obligations` ledger, including historical/current envelopes, current
scientific decisions, cohort counts, partitions and blocking mapping claims.
The native validator remains the scientific and lineage authority. The KG layer
also checks that retained owner dependencies and emitted arrays agree.

The graph carries a ledger header and ordered complete entry information
assertions, linked by the complete native ledger digest, alongside the ordinary
emitted companion observations. This keeps each complete claim in its own scalar
cell without changing TSV limits. Entry indices preserve native ledger order
even if graph rows are reordered. Its retained claims never enter source
resolution or active identity, xref, product, occurrence or ontology-parent
indexes. A retained source observation may remain scientifically SUPPORTED;
retention does not rewrite that decision. `audit()` reports the emitted arrays
and the full retained-ledger census separately. Persistence and native replay
on reload preserve the ledger and its complete original native artifact.

`graph_rows()` produces the separate profile `mimprofile:stable-source-kgx/v1`.
Numeric `MIM:0000001` and `MIM.ingredient:0000001` expand to the same permanent URI:
`https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_0000001`.
Every assertion has a scalar JSON envelope preserving original IDs, predicates,
evidence, status and payload. Supported source identity and external assertions
are separate active SKOS edges; broad, close and narrow mappings retain their
direction and predicate. No mapping automatically becomes `subclass_of`.
Withheld decisions and companion claims remain information assertions. Companion
authorization cannot create another source identity edge.

`audit()` separates native from consumer-admitted coverage and reports held
owners/rows. Ontology counts use the established eight-prefix reporting scope:
BTO, CHEBI, ENVO, FOODON, MICRO, NCIT, UBERON, and mesh. CAS and local registry
targets do not become ontology matches. Counts distinguish exact external,
stable MIM plus inexact, and stable MIM only for the actually supported source
owners; complete external rows are also counted separately.

## Downstream P3556 hold and lineage

The unchanged, byte-pinned downstream hold, its identity policy, original fixture
and review document remain required inputs. A selected native migration proof
uses `identity_projection_frozen.decode_frozen` against the original fixed Git
preimages. It verifies the exact historical owner and full mapping row, the
complete administrative transition, and immutable registry prefix. Current
registry/lifecycle entries then locate that stable owner or its explicit terminal
successor. The scientific hold is retained as a separate consumer overlay; this
operation cannot release it.

Without that historical proof, an exact current retained legacy identifier or
historical path triggers `CONSUMER_LINEAGE_UNRESOLVED` for that owner. This is an
explicit consumer admission limit, not a new scientific judgment. Its raw native
rows and dispositions remain unchanged. If there is no current legacy binding,
the result says so and records the limitation: absence of an alias is not proof
that a renamed predecessor is absent. The adapter does not infer that any other
owner is P3556 because it shares `CHEBI:86658` or another target. A candidate with
that unresolved limitation is not evidence of full production compatibility.

## Persistence and the native KG boundary

`export_candidate(new_directory)` writes a new immutable candidate containing
the complete source products and required companion products, original assertions, selection, input receipt
and actual child execution. It preserves partial bytes and adds `FAILED.json` if
installation fails. `reload(directory, manifest_sha256=...)` checks exact members
and re-runs actual current native admission before accepting the persisted
assertions and products. It requires the selected native origins; it is not an
offline scientific-approval archive.

`bind_to_transform` registers the actual already-validated input bytes with the
existing native finalization mechanism. The focused fixtures write the projected
rows, invoke actual `Transform.finalize`, create an archive through native
`write_graph_archive`, read its exact TSV members, and call `verify_graph_rows`.
That final check requires this stable profile and exact source manifest pin on
every row, complete node/edge membership, and unchanged assertion envelopes and
mapping endpoints. No production transform or graph build is invoked by the
consumer constructor.

## Test evidence and limits

The projection tests are hermetic synthetic fixtures. The native integration
tests additionally require explicitly selected `MIM_STABLE_TEST_PRODUCER`,
`MIM_STABLE_TEST_PYTHON` (maintained MIM Python 3.13), and
`MIM_STABLE_TEST_PRODUCTS` (the genuine original baseline product fixture).
They run the KG consumer in its maintained runtime and the native MIM validators
in the selected MIM runtime. The native acceptance command is:

```bash
poetry run python scripts/run_pr_gates.py <label> --require-stable-mim
```

Set all three explicit selectors before that command. The maintained tox route
forwards those exact variables, and required mode refuses missing prerequisites,
unexecuted native controls, skips or expected failures. Ordinary runs without
required mode may report unavailable native prerequisites as skips; those runs
do not establish native compatibility. Keep the resulting selected input,
producer, runtime and actual invocation evidence with the gate receipt.

`tests/resources/stable_mim_native_fixture.py` constructs fresh, explicitly
synthetic scientific report pairs and independent external/companion decisions
through the actual pinned native fixture and producers. It covers narrow and
shared-target mappings, held/ownerless sources, no external mapping, rename and
legacy aliases, unresolved consumer lineage, and terminal-record refusal. An
empty external partition uses the explicit source-only mode. The original failed
fixture is retained: the legacy companion requires a supported scoped mapping
for every annotation, product and occurrence owner, and a withheld annotation
cannot bypass that requirement. The new mode validates actual complete native
source products and supplies no companion claims. An all-external-withheld case
retains its four original negative mapping rows while independently supported
source identities remain usable. No test
claims to establish current campaign scientific acceptance or KG release readiness.

The retained variant uses the selected, commit-checked native MIM full 51-claim /
20-owner test fixture, its authenticated mint history, and fresh explicitly
synthetic source decisions. The 14 BSA obligations remain evidence, with a
separate synthetic source hold. It checks native constructor admission, source
refusal, exact ledger/graph transport, persisted reload and the existing native
finalization/archive boundary. It does not reuse campaign scientific reports or
establish that the pending real campaign export has completed.
