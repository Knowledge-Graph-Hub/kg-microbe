# Ingredient KGX review

Tracking: #1135; review findings #1142, #1145 and #1146. Dependencies: #1141 and #1120.

The real MIM #775 export is projected to 71 nodes and 51 source-qualified claims.
Round 1 verified all structured claims through public loose/archive merge and
reload, including seven BSA recipe contexts, source-specific A7030, the unselected
A9647-or-A7409 group, and current/historical/rejected registry annotations.

Round 2 reproduced certification of prior output after an injected projection
failure. The public run boundary now latches failures until an explicit new run.
Ten focused projection/transport checks passed. Registration is explicit-only,
with its own required consumed SSSOM input; it does not require or activate the
production unified mapping file. Dispatch/input-contract checks cover that route.
The integrated #1120 broad-match prerequisite and #1133/#1134 lookup checks passed
127 focused tests before the subsequent #1143 cache-isolation fix.

General activation remains disabled. #1136 owns the complete scientific-case
matrix, independent native ontology excerpts, two synthetic products sharing one
CAS, candidate receipt and production activation refusal. No production download
pin or general CultureMech ingestion is changed here.

Round 3 used the complete pinned Biolink 4.4.2 model and reproduced a namespace
collision: Biolink already defines `MIM`. The application now uses
`MIM.ingredient` for local graph endpoints, retaining original producer IDs in
the structured claim payload. This also fixes the 34 full-suite failures caused
by that collision. Existing collision rejection remains enabled. A separate
multi-mapping probe reproduced a dangling broader endpoint when the source also
had an authorized identity; both broad/narrow directions now use that reviewed
canonical owner. Five focused regression cases cover namespace and row order.
The combined projection, offline merge and ontology conversion suite passes:
56 tests, including the affected full-model context paths. Full tox/pytest is
rerun on this corrected version before merge.
