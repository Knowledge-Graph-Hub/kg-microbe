The authorized LPSN continuation audit of PR #1750 found that LpsnApiTransform._make_authenticated_client unconditionally calls load_dotenv before inspecting the two environment keys. The approved credential-file read is restricted to LPSN_USERNAME and LPSN_PASSWORD via a nonexecuting allowlisted parser; an additional generic dotenv read would exceed that scope. No credentials were read by the audit.

Acceptance: when both environment keys are supplied, client construction must not invoke dotenv loading. Retain explicit missing-credential failure behavior and meaningful offline tests for both-present, each-missing, both-missing and incomplete fallback states. The continuation should additionally disable generic dotenv discovery in its controlled process.

Disposition: in scope for PR #1750 before authentication.
