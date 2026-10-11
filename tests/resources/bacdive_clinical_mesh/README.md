# Native clinical classification fixtures

`records.json` contains literal selected BacDive record IDs and complete isolation sections. Unrelated sections are omitted; `native_array_index` is fixture provenance and is not injected into the producer's native record. The selection includes the first current occurrence of each reviewed clinical target and native macaque/canine Periodontal Pocket records. Source SHA-256: `57344e55e5683d168b735b6f186fd239d5637820d0c1559a210945bca883cea2`.

`mesh2026-clinical-excerpt.nt` contains all 228 native RDF statements for exactly eight subjects: D000038/M0000059, D007249/M0011307, D010514/M0016336, D014947/M0023019. Each pair is a descriptor and its preferred concept. Statements were extracted verbatim from the selected full `mesh2026.nt.gz`, SHA-256 `6997c24530cfbc698690e3d85ba5436e5ee56708f7f77073cbf8f502f3de7c5e`.

The excerpt is **not** the whole native file and its compressed test representation does **not** have that whole-file hash. Production and tests verify the same complete finite selected-statement digest, `b24b583e924202be000211b0727638c41b08100fffb89d296b7a71c42c49c761`, while consumed-input hooks independently record the actual whole input bytes in each run. Changes to the selected scientific evidence require a reviewed code/policy update.

Clinical MeSH projections are bounded manual native-definition/source-context decisions, not native OWL category assertions or strict Biolink validation waivers. A complete current-native source replay independently reproduced 717 Inflammation + 987 Wound source observations and 525 Abscess + 59 Periodontal Pocket source-site assertions before this fixture was accepted.
