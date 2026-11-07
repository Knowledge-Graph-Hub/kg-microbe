Independent read-only review of PR #1750 found that the new outer credential loader invokes the main launcher with inherited stdout/stderr. The launcher protects its later worker, but the first credential-bearing Python interpreter can emit output during startup/imports before launcher __main__ establishes protection.

Acceptance: bind stdout/stderr to DEVNULL at the first credential-bearing subprocess creation as well. Retain only fixed nonsecret process/receipt acknowledgement; credentials remain environment-only. An offline first-process startup hook emitting a synthetic credential before main must produce no captured output or saved secret. Preserve the inner worker and exception protections.

Disposition: fix and re-review before live authentication; no real values were loaded for review.
