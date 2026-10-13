# Synthetic direction-reader fixtures

Created 2026-10-13 for the `uniprot&metanetx` branch extraction. These fixtures
are synthetic API contract examples, not biological association evidence.
Nonconsecutive family members prevent accidental direction assignment through
identifier arithmetic. The duplicate mapping must remain a separate row.
The protein token with an isoform-like suffix tests literal preservation, not
the existence of that isoform or its reaction annotation.

Tests create a synthetic release policy under `tmp_path`, pinning this tiny
directions table. It is never a production release or admission contract.
