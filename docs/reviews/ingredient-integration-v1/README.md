# Producer-to-merge integration review

Tracking #1136. Producer: MIM #775 at
`73f14f4a930249836b4c3eee9bae635c731d6c5e`. Consumer dependencies: #1139,
#1141, #1144 and the #1120 broader-mapping implementation.

The actual producer's 20-case export is combined with independent native KGX
excerpts and complete Biolink 4.4.2. All 51 original source claims survive the
finalized public KGX archive, with the native xanthine and rifamycin subclass
edges. A second actual producer export adds clearly synthetic same-CAS products
and two occurrences from one source; all 57 claims retain their identities and
payloads. Reversing native input order leaves graph semantics unchanged.

Review found and fixed:

- #1145: a broader mapping could reference an undeclared original MIM endpoint
  after an authorized identity replacement. Both directions now use the reviewed
  canonical endpoint while preserving the original row.
- #1146: the complete pinned model already owns `MIM`. Local ingredient graph
  endpoints use `MIM.ingredient`; original producer IDs remain in payloads.
  These two projection fixes are carried by parent PR #1144.
- #1147: valid hashes could admit an internally contradictory legacy companion.
  Candidate construction/reload now reject same-pair exact/nonidentity clashes
  independently of row order. The old production artifact is unchanged.
- #1148: MediaDive's recipe writer failed without strain observations. Resetting
  the per-medium strain list preserves ingredient output in that case.

The focused combined gate passed 78 tests. Native fixture generation was
reproduced byte for byte from the recorded source hashes. Regenerating the
synthetic fixture through the pinned MIM exporter reproduces manifest
`4dfbfd1927fd6899a04b50efa3049dc2e35ceda817020f5bf007a936b45edb33` and archive
`21a1510e8c88b29ab8eeeac3baf50406540ac7d2759e0829534eb599542e359c`.

The initial legacy test lacked the actual ChEBI closure authority required by
source finalization. It now reconstructs a small SemSQL database from 429 exact
original statement rows for the two required terms and their asserted ancestry;
the strict authority checks remain enabled. Source versions/hashes are independent
of the main native JSON excerpt and are explicitly recorded as such.

Full repository checks and current-head CI are required before merge. Production
activation remains refused; the #1123 source-closure/promotion decision is not
replaced by a passing fixture report. Lysozyme/sorbitan evidence holds remain
separate scientific review tasks.
