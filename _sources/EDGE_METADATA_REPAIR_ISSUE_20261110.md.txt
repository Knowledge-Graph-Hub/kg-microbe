EdgeMech's pinned 2026-09-29 release inventory found 79,573 distinct nodes with
missing names. Publication nodes account for 19,230 DOI and 17,303 PMID IDs.
The current LPSN API transform emits unnamed publication stubs even when its
source records contain `publication_text` or `ijsem_list_text` for those IDs.

Preserve a unique nonempty source citation verbatim as the display name, with
the source field explicitly recorded in the node description. Do not represent
the citation as a verified article title, cross-bind the main publication and
IJSEM-list fields, or choose arbitrarily between conflicting citations.

Acceptance: test exact source-field binding, duplicate/conflicting records and
missing/malformed citation values. Replay one retained source record, verify
persisted nodes, then measure the full local cache's coverage of the pinned
missing-ID set. Preserve source IDs and assertions. A bounded replay does not
replace normal release regeneration.

This is an upstream repair for https://github.com/CultureBotAI/EdgeMech/issues/36.
Other gaps include source accessions with no record names in the retained inputs;
those must remain explicit rather than acquire invented labels.
