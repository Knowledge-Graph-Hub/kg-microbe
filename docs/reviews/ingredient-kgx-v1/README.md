# Ingredient KGX review

Tracking: #1135; failed-run review finding #1142. Dependencies: #1141 and #1120.

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
