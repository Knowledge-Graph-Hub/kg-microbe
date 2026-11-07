The authenticated continuation audit of PR #1750 found that scripts/adhoc/kgm_rebuild_20261105.py hashes the entire inherited environment into environment_sha256. Credentials were not loaded by this audit. The approved LPSN execution may inherit exactly two credential variables, so persisted provenance must be explicitly limited to reviewed nonsecret execution settings.

Acceptance: use a documented allowlist and explicit fingerprint scope; never serialize or fingerprint credential values or arbitrary inherited environment. Offline controls must show that rotating synthetic credentials or unrelated secret variables leaves the execution fingerprint unchanged, while changing a relevant nonsecret setting changes it. Preserve old receipts as historical; do not restamp them.

Disposition: in scope for PR #1750 before authentication.
