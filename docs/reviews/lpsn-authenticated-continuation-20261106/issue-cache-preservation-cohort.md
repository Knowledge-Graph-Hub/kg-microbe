Independent review of PR #1750 found that the continuation checks a preservation manifest before and after acquisition but does not bind the after-check to the original manifest bytes/cohort. A simultaneous existing-cache mutation and manifest-entry deletion can produce a false pass. Path.rglob also lacks the explicit traversal-error refusal already required by the rebuild inventory contract.

Acceptance: capture and retain the exact manifest identity/cohort before native transform execution; require it unchanged afterward and verify every original member and independent copy. Use exhaustive traversal that propagates errors, including ignored files. Add mutation-plus-entry-deletion, missing-member, traversal failure and successful-addition controls. Preserve all earlier cache copies and receipts.

Disposition: fix in PR #1750 before the remaining source phase.
