# Source-backed metadata repairs for EdgeMech

This change addresses #1834 and #1835, upstream follow-ups to
[EdgeMech #36](https://github.com/CultureBotAI/EdgeMech/issues/36).
The retained graph inventory has 79,573 distinct nodes with missing labels.
These repairs preserve identifiers, categories and associations.

LPSN publication nodes now use a unique nonempty `publication_text` or
`ijsem_list_text` citation as their display name. The description records the
source field and explicitly distinguishes a citation label from a verified
article title. Conflicting citation strings remain unresolved; record order
cannot select the winner. Blank or malformed values do not become labels.

PREGO now consumes the existing BTO SemSQL download as a fingerprinted metadata
input. It hydrates only emitted BTO identifiers with explicit class declarations
and unambiguous labels, preserves obsolete status and emits a mandatory metadata
audit. Missing classes/labels remain unresolved. Malformed authority, changed
bytes, redirected input locators and altered audits fail validation.
Dictionary synonyms are not treated as authoritative names.

| Bounded validation | Result |
|---|---|
| LPSN real record784756 production canary | Eight API cache reads; persisted nodes, edges and required record audit; three source citation labels |
| LPSN production run with 35,425 cached records | Labels for 36,512 missing IDs: 19,209 DOI and 17,303 PMID; 21 conflicting DOI IDs unresolved |
| BTO one-ID canary, then all affected IDs | 367/367 labeled; zero unresolved or obsolete in selected authority |
| Eight EC nodes through public merge | Existing names recovered; current blank-name precedence fix confirmed |
| Focused LPSN identity, transform and admission tests | 88 passed |
| Focused BTO/PREGO/freshness/dependency tests | 151 passed |

The BTO authority is the retained **2021-10-26** release, compressed SHA-256
`3141e55d5cbec9ff36e7bdfe443ff28f1708ce124a9bdeaa022f3dcd0cbd07ab`.
No current-release claim is made. Each real canary followed the same launcher,
environment and output path conventions as its subsequent replay, and persisted
outputs were checked. The BTO canary caught a relative-path SQLite URI error;
it was fixed and re-canary-tested before the 367-ID run. The LPSN canary caught
an import resolving to the old checkout; `PYTHONPATH=.` and the recorded producer
module verified the corrected path before the full-cache replay.

Read-only adversarial review found #1837 (unchecked API payload identity) and
#1838 (API citation records absent from production freshness). Both were filed
before correction. Cached/live payloads now require the requested ID. Production
parses immutable record snapshots and records GSS selection plus every selected
API cache locator in a mandatory `lpsn_api_records.tsv`. Finalization/admission
reject changed or deleted consumed bytes, redirected selected locators and a
missing or changed audit. Newly fetched responses are atomically cached before
snapshot parsing; an initially empty cache remains supported.

The final offline production replay exercised `run/_fetch`, not only emitters.
It consumed 35,425 cached API records, recorded 665 absent selected API paths and
made zero live fetches with zero errors. Cached web-fallback labels remain outside
this API-specific provenance guarantee. Canned empty responses for cache misses
are a local replay constraint, not evidence of a remote API result. The earlier
emitter-only artifacts remain retained but are superseded by this production-path
receipt for validating the new record binding.

| Retained artifact under `data/edge-metadata-20261110/` | SHA-256 |
|---|---|
| `lpsn-citation-label-full/receipt.json` | `86e9bb438bc8fa87348ba2fbf5e3bdbc58b1b933fab22f5d56eb35ba50cef918` |
| `lpsn-production-full-v2/receipt.json` | `0bc40292a3b19f176c64771209240fb167147c5f8251261d0f875a1ec7588219` |
| `bto-367/receipt.json` | `bc017d337a46f6e645913954c353689e9a8a9f2f4156eed4fc865e39e2f7d5e1` |
| `bto-367/prego_habitat/nodes.tsv` | `7fdd7952c7ca1126a0a7bb07ab1be4e8cd6843be0794dc65e5727d1ca533ebfa` |
| `bto-367/prego_habitat/prego_bto_metadata.tsv` | `1fc6747747eb748c22e5d334492c55e5e42243fa34f830dd5ad7b61d634b4f93` |
| `ec-eight/published/merged.tar.gz` | `c6486bc3d5c909bbe3f4931fc1cd390691c35bbbcda4ab7a35a6d5153fc15f1e` |

Saved helpers under `scripts/adhoc/` reproduce the diagnosis and bounded replays.
Bulk inputs/results remain local. The pinned incomplete-node Parquet SHA is
`d8db0cbf103054bcc18ec37136b5dc77bca446a83c115b1f5e8b379e61a363d8`.

These are component and source-cache coverage checks, not a complete LPSN/PREGO
source-release selection, complete merged graph or release regeneration. The historical EdgeMech
release remains unchanged. Current upstream code also contains explicit ENVO
dispositions; it should be used during normal regeneration rather than duplicated.
IMG and INSDC still lack owner-supplied record titles in these inputs. Partial and
obsolete EC semantics remain tracked in #267/#268, and citation conflicts require
source reconciliation. These gaps are not evidence that their biological edges
are false.

Final gates use an isolated Python3.12 Poetry environment installed from the
lockfile. The initial focused tests used Python3.10 with an explicit checkout
import path. Final validation uses `scripts/run_pr_gates.py` and records the exact
candidate and per-command results under `data/validation/pr-gates/`; the GitHub
PR carries the final gate outcome. No original checkout or environment was rewritten.
