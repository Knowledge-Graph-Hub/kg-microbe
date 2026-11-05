# MediaDive resolution evidence — 2026-11-05

These are exact copies of selected run records, not rewritten or restamped receipts.
The full raw responses, cache generations, ledgers, failed attempts, executable audits,
logs and original inputs remain under `data/rebuild-evidence/20261105/` in the owned
M5 worktree. The [run report](../../MEDIADIVE_RESOLUTION_1734_20261105.md) separates
source admission, code validation and graph validation.

The original seed/canary/batch records correctly report admission false. The later
`admission-r2.json` and independent audit establish finite qualified source admission:
6,056 nonempty endpoints and 632 unknown/unavailable endpoints, with association
coverage explicitly incomplete. Earlier failed reviews and the failed first activation
remain historical. No copied record certifies an unrun producer, graph or release.

`manifest.json` gives each original evidence locator and the copied byte/hash identity.
The curated exact-case policy is in `mappings/mediadive_unknown_dispositions.json`.
No unknown is an explicit empty list or a negative growth assertion.

| Copy | Bytes | SHA-256 |
| --- | ---: | --- |
| [resolution-seed-r1-receipt.json](resolution-seed-r1-receipt.json) | 40739 | `0af71098c42a2ea4ea51a675e537140ca694729c6143e9d2a6399f0523d3f216` |
| [resolution-canary-r1-receipt.json](resolution-canary-r1-receipt.json) | 40802 | `083c59cbd5cc548a0356c59b3eb80e50239e2265e8432dfe659fba87609a348d` |
| [resolution-batch-r1-receipt.json](resolution-batch-r1-receipt.json) | 43527 | `f1570d0b78f85d760bee496cc546815d2a1fbbeb85b5bc28231f50a92e2df823` |
| [seed-canary-batch-independent-audit-1.json](seed-canary-batch-independent-audit-1.json) | 30877 | `6476c469189bdc29b9193ce1bfbb461b952d0810b59490a767c54f035eac01dc` |
| [current-reader-batch-replay-1.json](current-reader-batch-replay-1.json) | 41584 | `309f1932d4b12e024dd0da0509a23d71ff06ec495e63169c7794900451c60ef7` |
| [admission-r2.json](admission-r2.json) | 80519 | `c0d7f181cc6a0f0999c1bd8618a0f26317a2fa16eb290d992f43da86cff67db2` |
| [admission-r2-independent-audit-1.json](admission-r2-independent-audit-1.json) | 86687 | `7202e5c85461a4af99e40731e130495d37b4e9e707cfca16d1aa334a0323f9ad` |
| [finite-policy-and-helper-independent-review-1.json](finite-policy-and-helper-independent-review-1.json) | 4245 | `4d2ac1cbfeab6bd3d18dbe5cebacf2da4d46363c78399efc8cfaf684ed902931` |
| [finite-policy-and-helper-independent-review-2.json](finite-policy-and-helper-independent-review-2.json) | 7362 | `be91c7e219230c538fe9007e99de0c6295d8e744b31de1f140c763a36f6d81a4` |
| [finite-policy-and-helper-independent-review-3.json](finite-policy-and-helper-independent-review-3.json) | 13945 | `7dcf25477fdcc659aa2096868ae9a85738b7881bff1a4d91d0b4d8269b3baafe` |
| [current-documentation-policy-proof-1.json](current-documentation-policy-proof-1.json) | 44789 | `2eaa5f694ce4d32ad806dd312e2d4e702a33dc07acc2adf5609632d072ed72f2` |
| [official-doc-contract-activation-failure-assessment-1.json](official-doc-contract-activation-failure-assessment-1.json) | 4793 | `410d49937258c09e6dcd0435bdc0653f9a6a1bafc1e6fff673f7e48887ccd6c8` |
| [current-ontology-revalidation-r1.json](current-ontology-revalidation-r1.json) | 7292 | `472a7c94aaac89317552fa2b8eae908db6764dfa85e2803f49bb86cef7dc4920` |
| [ontology-admission-r1.json](ontology-admission-r1.json) | 17923 | `6d258408d22885a952674ee3f30a90e872df57ef365f059b3f0fd1fe3f4e863d` |
| [finite-unknown-policy-review-criteria-1.json](finite-unknown-policy-review-criteria-1.json) | 9808 | `7ac2d4af1065f6a764a612e045832be30a70052b29ffb020192224e564fbb990` |
| [identity-comparison-1.json](identity-comparison-1.json) | 8970 | `ad51dd3ea92e506899a0c6fc57f7a44e83eda9a61eab581141dabd5ceeca97d3` |
| [control-r2-scientific-comparison-1.json](control-r2-scientific-comparison-1.json) | 8899 | `3b436135eacb90e2e8d016fc37c365de35650871f01b82e38275ca4f431aaff2` |
| [unknown-r2-scientific-assessment-1.json](unknown-r2-scientific-assessment-1.json) | 2531 | `f4c4dd9dbccf1400662e60113f3096d1a273e992899b0d27a48661e8b5c34479` |
| [production-acquisition-independent-review-1.json](production-acquisition-independent-review-1.json) | 6604 | `ca0386897a7762c77ea6a1e8363fa48cc4ef780c14c4afd9a7d272f22b00040a` |
| [production-acquisition-independent-review-2.json](production-acquisition-independent-review-2.json) | 6567 | `517cfe47977e09035886cf50953f30c2ffbeb6729e07452d39e9ad0b66eacb81` |
| [production-consumer-independent-review-1.json](production-consumer-independent-review-1.json) | 5242 | `32ea4b00e2b81c23921d10c0863a14277954cf9275a40dcbd84a69f45cd50fff` |
| [production-consumer-independent-review-2.json](production-consumer-independent-review-2.json) | 4160 | `9dcc21f733f751106507227182e2c72af72ba082a432d174645e88c2831c618d` |
| [merge-qualification-review-1.json](merge-qualification-review-1.json) | 2730 | `dd6c999becfc70010932dba582dcedf0b98dfc4d69413c5e3411fe80f98fb165` |
| [artifact-verifier-root-review-1.json](artifact-verifier-root-review-1.json) | 926 | `df0a4a8c48c5e562f59723f267e97d72af57dc10045e548d8ed48c044e40d1ab` |
| [native-strain-id-multiplicity-official-assessment-1.json](native-strain-id-multiplicity-official-assessment-1.json) | 3398 | `5fd50601d1bd2e69ef87ca1eb10a6b770a5e0c2daf462b38e826b309c59ab296` |
| [consumer-fixture-consistency.json](consumer-fixture-consistency.json) | 3325 | `b7710e872abbc88ad70a3b0a872c3f840af06b43e59bee7957e865e15ced9c64` |
| [consumer-recipe-fixture-repairs-r3.json](consumer-recipe-fixture-repairs-r3.json) | 2283 | `eedf275021da196209604d96d63477be31b2d208fbcd57f4f92b6d69e0bf0324` |
| [consumer-review-findings-1767-1768.json](consumer-review-findings-1767-1768.json) | 3267 | `4a9757900313d189e85d25bb84cb248a5d6011f4f0082f29bbd9db63fc7cf567` |
| [remaining-fixture-repairs-r1.json](remaining-fixture-repairs-r1.json) | 1033 | `466f0eb32796f3e54d5241a2b1ed5b454716b3405c49b4e25afed608cd91558c` |
| [remaining-fixture-repairs-independent-review-1.json](remaining-fixture-repairs-independent-review-1.json) | 3692 | `ca9546debc68c9a26930586b4e3b710356ed1ff9e72556fc490c5bd1425a359e` |
| [format-preservation-r1.json](format-preservation-r1.json) | 248 | `3069a02bfe93b021c6f0607520728a36c2a9b77314ae31e18b3958f594182a10` |
| [october-preservation-r1.json](october-preservation-r1.json) | 2591 | `66b99af0016c61bab0e0cef9c544e5f64d8b3bcfc8615762e6d88d727b4417d6` |
| [october-comparison-helper-root-review-1.json](october-comparison-helper-root-review-1.json) | 637 | `1fdedd209d82aa4a7fe5279eaa231f8740e0246507d0af50d43466d8cda489ca` |
| [documentation-contract-fix/frozen-source-proof.json](documentation-contract-fix/frozen-source-proof.json) | 996 | `5866a82bdaa2d87a18ef0b8ea5d1dd7d96bfff5de2f3db11d92a7b7b2a2d633d` |
| [documentation-contract-fix/fixture-boundary-correction.json](documentation-contract-fix/fixture-boundary-correction.json) | 1160 | `7918f32e99737e7e7ed1ae24bd716a896a402b075f3b775b76dc9f60b9d4705a` |
| [artifact-stream-review/repair.json](artifact-stream-review/repair.json) | 703 | `def15922024a9b4902e28a28c1285feda25193db9b4df09c25fc80d65c5eaaf6` |
| [artifact-stream-review/final-identity.json](artifact-stream-review/final-identity.json) | 469 | `a374b4be60236dd6b0f8cc9aa1d1da8d1713f56a6663b1c3a8ce374109aa3342` |
| [filed-findings.jsonl](filed-findings.jsonl) | 4122 | `f2562ab16e82c8aade2b96decf744470ad03d1840caa4d2e55cfb46372a83e2d` |
| [ncbitaxon-reuse-independent-review-1.json](ncbitaxon-reuse-independent-review-1.json) | 6800 | `31605de02e84bd35b7890003df34b6ca80d4ece5b7638acbad37f64088f667ec` |
| [lpsn-phase-helper-independent-review-1.json](lpsn-phase-helper-independent-review-1.json) | 4772 | `b2105f2eb78696295e752f4267c0262281350ee72b27a8ca8e9c8f0c861742ba` |
| [lpsn-phase-helper-review/final-readonly-review.json](lpsn-phase-helper-review/final-readonly-review.json) | 3391 | `cf3c95e3ebf3531f6839e186ab89900d189acc51241f471e4b4694db7ec40e5b` |
| [lpsn-phase-helper-review/final-identity.json](lpsn-phase-helper-review/final-identity.json) | 899 | `867bbcbb1ac0099613436fb4556ba27a58fa4cda014f65b9a0db38f8b8172395` |
| [lpsn-phase-helper-focused-r1.log](lpsn-phase-helper-focused-r1.log) | 2783 | `23547fc9de005b137dd74bc34a04d84a71efa06522a00bdfb3c44ec70e056e3f` |
| [native-fixture-whitespace-check-r1.json](native-fixture-whitespace-check-r1.json) | 403 | `cdc840fa1e3f5e8d53b1ae1ca05fcd92337c2bf0ad5d1422ab1def4adc685064` |
