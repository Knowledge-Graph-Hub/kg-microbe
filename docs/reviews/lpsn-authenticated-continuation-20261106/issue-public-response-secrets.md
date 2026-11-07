Independent read-only review of PR #1750 found that public_payload checks decoded string values but not object keys or duplicate-key values shadowed during ordinary JSON parsing; the raw response is then persisted. Client access/refresh token values are not included in the in-memory sensitive set. A malformed or echoing response could therefore persist sensitive material.

Acceptance: reject duplicate JSON object keys; inspect all decoded keys/values and raw response bytes against the authorized in-memory credentials and client token values before any write or hash. Never save or fingerprint those sensitive values. Add controls for duplicate-key shadowing, secret-bearing object keys, token echoes, encoded values and unchanged successful public record retention. Failure provenance must contain fixed nonsecret categories only.

Disposition: fix and re-review before live authentication; no credentials were read by the audit.
