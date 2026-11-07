# Reviewed broader-form source fixture

`source-claims.json` retains all six unmodified source rows for the two supported
hydrate-to-parent broader claims at immutable MIM commit
`0dac278466699129a083343a921c2e0ca18a9ab4`, with original source positions and
review decisions. Whole-source and review SHA256 values are recorded in the
fixture. This subset is not relabeled as the complete official export.

Tests construct a clearly synthetic six-row export manifest/disposition partition
under `tmp_path`, retaining every original row field. They use independently
identified synthetic native-node controls to exercise reconstruction. Actual
native candidate output and full graph admission remain separate required gates.

The broader source rows do not authorize alias copying or identity to the parent.
CAS and local exact siblings supply form identity separately.
