# FOODON cold-conversion lifecycle fixture (#1745)

These are complete selected node and OWL element records from the actual ROBOT
1.9.11 conversion of the unchanged FOODON OWL. `origin.json` records full input
hashes, fixture hashes, and the extraction set. It retains the reviewed kernel
cohort, its asserted ancestor closure, and the actual deprecated CHEBI:23652
(dextrins) declaration with all four incident named-parent edges and their
ancestor declarations. No labels, types, flags, or assertions were synthesized. All endpoints of the
original complete kernel incidence are retained, including the FOODON:00004348
quality target of seven RO:0000086 assertions; subclass closure alone would
incorrectly omit those assertions.

The native inputs remain pristine. The tested classification projection first
validates complete finite JSON/OWL evidence, proves retirement and removed
incidence from OWL, then computes the live closure. The 22-class kernel policy
and its single rejected parent remain unchanged. Malformed declarations and
unsupported retirement cannot be hidden by that preparation boundary.
