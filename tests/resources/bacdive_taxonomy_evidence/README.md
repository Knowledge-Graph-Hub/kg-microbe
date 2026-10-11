# Synthetic offline behavior fixtures

These literal files are prospective permanent fixtures for #1353, #1354 and
#1361. They are synthetic controls, not evidence that any real taxon or strain
has the shown biology. After thaw, tests create SQLite only under `tmp_path`
from `authority.sql`; source readers consume actual fixture bytes through the
normal native-input APIs. No network, adapter selector/build, or test-only
contract bypass is needed. Full biological acceptance remains the separately
bound current-native 1,086-deposit/172-convergence and 85-collapse review.

The controls include direct, inferred, mixed descendant/ancestor, same-target
direct+inferred, disjoint, repeated-token, later-special-inference, absent,
convergent-LPSN, and genuinely ambiguous-LPSN cases. Their original source array
positions are part of native evidence; do not prefilter or renumber them.
