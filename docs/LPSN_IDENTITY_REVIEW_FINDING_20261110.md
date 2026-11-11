Read-only adversarial review of PR #1836 found a P2 citation-provenance gap.
`LPSNAPITransform._fetch` accepts cached/live payloads without matching their
record ID to the requested ID. The new citation description then attributes
the field to the requested LPSN record. A cache file named `1002.json` whose
payload identifies record1005 can therefore misattribute a publication label.
The audit helper rejects this mismatch, but production does not.

Validate payload type and exact record identity before using cached or live
records. Add mismatched-ID, missing-ID, null and list regressions. This inherited
fetch weakness now undermines the new source-label provenance guarantee; the
fix must exercise the production path rather than only the audit helper.
