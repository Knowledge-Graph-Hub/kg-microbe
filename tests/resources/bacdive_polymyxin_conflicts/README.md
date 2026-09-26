# BacDive explicit Polymyxin B identity conflicts (#1185)

`records.json` is a compact projection of the pinned raw BacDive records 76 and
167665, not invented chemical identities. Original source SHA256:
`57344e55e5683d168b735b6f186fd239d5637820d0c1559a210945bca883cea2`.
The guarded selection report SHA256 is
`cb10563c0a8dce11865642a932c79a0da3a620cc430c42c47b74e5b34d60c615`;
its complete selected-record ledger SHA256 is
`03eb71a3deba11b11de212ba7d7bc5e92930c7deefce94bcb0d89dd4fbf1f229`.

The projection retains exact General.BacDive-ID, complete selected chemical
items, and their own complete reference records. Other source fields are omitted.
Original positions are record 29 / antibiotic resistance item 0 for 76, and
record 90647 / metabolite utilization item 15 for 167665. Fixture lists contain
only the selected item; tests separately exercise original gaps and duplicates.
Runtime diagnostics correctly report positions in the actual input, not the
original full input's positions when using this projected fixture.

Native CHEBI:8309 identifies polymyxin B1 (CAS 4135-11-9), whereas NCIT:C61894
identifies the Polymyxin B B1/B2 mixture (CAS 1404-26-8). See the independently
reviewed `mappings/reviews/chemical-scopes-20260923.md`. Neither the supplied
member ID nor the generic raw name resolves their conflict for these particular
experimental materials. This fix retains a source-local record/item material,
not an external equivalence, native subclass, or shared mixture identity.

The 380 selected raw conflicts (379 antibiotic items, one negative assimilation)
are distinct from the existing 207 reviewed name-only mixture graph claims.
Only 361 of the 379 antibiotic items satisfy the current literal yes-sign rule;
raw counts do not promise final graph counts or taxonomy admission. The source's
negative assimilation in 167665 retains its own DOI 10.1099/ijsem.0.003750; this
fixture does not claim independent paper-level validation of the extraction.

`chemical_identity_conflicts.jsonl` preserves all reached/taxon-admitted conflict
items, including non-emitting signs, as typed complete raw objects. IDs bind the
typed record ID, one-based input record position and exact field/list position;
identical items at different positions remain distinct. The graph preserves
`original_object`, source provider, predicate/sign and own item citations. The
sidecar is atomic but is **not included in the standard graph finalization
receipt**: postbuild acceptance must explicitly hash/admit it together with the
raw input, producer receipt and graph. No production mapping or pin is changed.
