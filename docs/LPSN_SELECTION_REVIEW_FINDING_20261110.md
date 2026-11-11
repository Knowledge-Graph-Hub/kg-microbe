Final read-only review of PR #1836 found a P2 completeness gap in saved native
admission. Required API roles are derived only from the contract's own `records`
inventory. A coordinated edit can remove a GSS-selected record from that
inventory, consumed inputs, fingerprint inputs and the rehashed mandatory audit,
while leaving GSS selection and graph output unchanged. Admission then stops
watching that record's citation bytes.

Reconstruct required selected records from the independently hash-verified GSS
input rather than trusting a self-declared inventory. Check present/absent record
membership and applicable linked-record traversal using the producer's rules.
Add a coordinated-omission regression that removes a record from every metadata
location and re-pins the audit, then requires admission failure.
