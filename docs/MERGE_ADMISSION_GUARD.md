# Bind publication to the originally admitted inputs (#1100)

Production `kg merge` retains a request-local admission snapshot from the
exact reads used by its source-freshness verifier. It includes the original
configuration, selected graph members, finalization records, producer
markers, audit reports, consumed/declared inputs, recursively validated
upstream evidence, producer/shared Python files, and repository schema files.
Lexical source paths stay bound to their original resolved targets, so a
symlink retarget cannot leave the old target unchanged and substitute another
input during staging.
The original source-resolution precedence is checked too: creating a new
CWD-relative candidate cannot shadow an admitted configuration-relative file.

Each file is SHA256-hashed with bounded-memory streaming. Metadata records
are parsed from those same captured bytes; graph-scale input contents are not
copied or retained in memory. Device/inode, size, mode, modification time and
change time are recorded around each read. Package membership is captured to
detect newly added Python helpers. Previously absent optional schema/shared
files must remain absent.

Admission finishes with a filesystem-identity comparison. After KGX, staged
cleanup, validation and packaging, but before any staged output publication,
the original identities are checked again, including full hashes and a final
metadata comparison. Changed, missing or replaced evidence raises
`SourceFinalizationRequired`; the previous published archive remains intact.
Even a concurrently completed, independently valid transform run is not a
substitute for the originally admitted source bundle. An identical-byte
replacement also conservatively aborts if its inode or write metadata changed.

This is a fail-closed observed-drift guard, not a filesystem transaction,
exclusive producer lock, or proof against a malicious writer that can conceal
changes to both bytes and filesystem metadata. There remains an unavoidable
small observation-to-publication window without writer coordination. Source
producers and merge should not deliberately run concurrently against the same
output tree. Cross-file publication semantics remain unchanged. The explicit
`allow_unfinalized_sources: true` diagnostic mode still opts out of production
source-admission requirements and labels its artifact accordingly; its
configuration identity is nevertheless bound so it cannot be relabelled as
a finalized release after admission.

The guard adds one full streamed recheck of admitted files before publication;
it intentionally prefers explicit I/O cost over silently publishing a graph
whose original admission evidence changed. It does not claim every raw input
in the entire pipeline was captured: existing declared/recorded dependency
scope remains the contract.
