Read-only adversarial review of PR #1836 found a P2 production freshness gap.
The new citation labels consume cached LPSN API JSON fields, but those records
are absent from production consumed-input snapshots and native input binding.
The external audit helper hashes them; its ledger is not part of producer
finalization/admission. Editing, deleting or redirecting a consumed citation
record can leave the existing label output marked fresh.

Bind exact consumed record bytes and selected locators to production provenance,
verify them before finalization and during downstream admission, and preserve
an auditable record-input ledger. Test byte mutation, deletion and same-byte
locator redirection. Preserve bounded cache/live behavior and do not silently
introduce fallback metadata. This inherited infrastructure gap is now relevant
to the publication-label provenance contract.
