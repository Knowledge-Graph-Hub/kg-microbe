Independent read-only review of the #1750 authenticated continuation found an integration blocker before credential loading: the launcher intentionally withholds authenticated plan.command, while the new canary validator requires that plaintext command field. A real authenticated canary therefore cannot authorize the remaining phase even when its request succeeds.

Acceptance: preserve binding to the actual safe command using a digest produced only after secret-bearing arguments are refused; record/verify the same nonsecret command digest in the launch plan and completed execution result. Require both actual execution success and the expected canary command. Add an integrated authenticated-launch-plan/receipt control and refusals for missing or altered digests, wrong mode/receipt/label and failed execution. Do not remove command binding or hash secret arguments.

Disposition: fix in PR #1750 and re-review before any live authentication. No credentials were read for this finding.
