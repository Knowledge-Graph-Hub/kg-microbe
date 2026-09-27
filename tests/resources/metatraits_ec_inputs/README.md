# Optional EC input lifetime fixtures (#1193)

These tiny synthetic maps deliberately assign one EC query different targets.
They test actual loader/resolver selection and byte provenance, not biology.
The two files have equal byte length so restored-mtime tests cannot pass merely
because a changed input has a different size. Missing EC remains an allowed
empty map and uses the unchanged EC identifier fallback.

`legacy_loader.txt` is the exact `_load_ec_to_go` method extracted from reviewed
base b8f355ca6cb5beb47b83dd67a463513386e453ad (producer SHA256
7dcd7c4a70fb4063fd37544ebcb32bc0914f054f55ff212be27a4616287b7ecb),
dedented without semantic edits. Tests compile it with the same repository raw
locator and prove it loads the fixture but does not establish required read
evidence. The independently preserved V4 whole old-gate reproduction remains
the separate evidence that the earlier public gate actually accepted drift.

`legacy_verify_finalized.txt` is the exact standalone verifier from the same
base (also byte-identical to that function in the first issue-1193 matrix).
It is compiled against the current actual registered tiny records and real
helpers, without retaining its discarded returned admission. This genuine
old-method control accepts EC mutation during later audit/member reads; the
corrected verifier must reject the same callbacks, including absent-to-present.
The test never substitutes a fake finalizer or edits a production artifact.
