# Finite MicrobeDecoder crosswalk quarantine (#1224)

The producer can withhold individually reviewed, authority-contradicted
`NCBI_Taxonomy_ID` and `GOLD_Organism_ID` claims. This is a source-quality
disposition, not a replacement-taxonomy mapping or a rule for inferring traits.
Assembly, IMG, unreviewed and insufficiently supported links retain their
existing behavior. A link that remains in the graph is not thereby certified.

## Reviewed contract

Three canonical files form one reviewed input:

- `mappings/canonical/microbedecoder_crosswalk_quarantine.json`: exact raw CSV
  SHA-256/record count, decision-table filename/hash/count, evidence filename,
  compressed hash, and decoded evidence hash/byte count.
- `microbedecoder_crosswalk_quarantine.tsv`: one rule for each exact record,
  original field and source token, complete raw-record hash, original complete
  field as base64, raw and effective LPSN identifiers, original pre-fold target,
  unchanged predicate/relation/provenance, disposition, witness ID and rationale.
- `microbedecoder_crosswalk_quarantine_evidence.json.gz`: lossless historical
  authority witnesses, with SHA-addressed shared composite values. Decompression
  is bounded by the declared length and a 256 MiB safety ceiling; compressed
  hash, gzip CRC, decoded size and decoded hash are checked before JSON parsing.

The record hash is SHA-256 of the complete `csv.DictReader` record serialized
with sorted keys, compact separators and `ensure_ascii=True`. The raw CSV is
decoded using UTF-8 with `surrogateescape`; this preserves rare non-UTF8 bytes.
Record ordinals count CSV records, not physical lines. There are no wildcard
aliases or namespace-wide deletion instructions.

Each nonempty disposition requires machine-checked saved evidence of an
accepted LPSN chain, an independent explicit BacDive type-strain record and its
LPSN/name/taxid supports, complete active NCBI lineages, original authority edge
provenance, raw taxdump genus/phylum rank rows and retired-ID hops. The target
must disagree with both supporting authorities at both genus and phylum, with
no explicit source/target native-name or synonym agreement. GOLD rules also
retain and validate their original raw organism declaration and explicit taxid
link, native link or fold witness. Original emitted claims remain in evidence.

These are **historical reviewed authority snapshots**, not an assertion that
all current taxonomy releases are identical. File/member hashes identify the
authority snapshots used for review; necessary saved rows, paths and claims
are checked for internal consistency. Runtime does not discover new conflicts,
redo a whole-authority uniqueness search, or silently upgrade the policy from
fresh external taxonomy. A changed raw CSV must receive a newly reviewed pin.
Current accepted-LPSN drift affecting any selected subject also fails preflight.
Authority updates affecting a historical decision require explicit curation.

## Producer and publication lifecycle

The producer reads one immutable consumed raw snapshot. It loads the policy,
table and evidence as consumed inputs, then preflights the **entire** CSV before
opening any graph output. Missing/duplicate headers, ragged records, changed
counts, altered selected records, changed reference cells or effective LPSN
subjects abort. Reordering rows or blanking a selected cell cannot evade review.

During emission a rule matches the original column/token/target **before** GOLD
folding or assembly side effects. It suppresses only that single claim and
does not emit a replacement edge. Every declared rule must dispatch exactly
once. Other edges preserve their existing context and provenance.

`crosswalk_quarantine.tsv` is mandatory, including when an explicitly injected
synthetic test policy has zero rules. It contains the rule/witness IDs, complete
raw source record, full original pre-fold edge row, reversible JSON/base64
versions, original field/token/target, evidence URI/rationale and compressed
and decoded evidence identities. The raw-record JSON preserves source
citations and otherwise unused fields; the original edge JSON preserves all
edge columns. The sidecar is outside the assertion graph and is not another
scientific edge source.

The producer records the report identity after successfully closing it.
Source finalization copies and verifies that original identity before and after
staging and before publication. The completion record includes it in both
`producer_audit_members` and `audit_members`. Repeat finalization and merge
admission enforce current registered required-sidecar declarations; deleting
the sidecar or deleting its receipt entries does not bypass this contract.
Consumed input guards continue through source finalization and merge admission.

## Hermetic tests

Tests inject an ordinary policy with `crosswalk_quarantine_policy=Path(...)`.
`tests.microbedecoder_quarantine_fixtures.write_fixture_quarantine_policy` creates
a hash-bound policy for a specific tiny fixture; it is not a runtime bypass.
The producer never invents an empty policy when files or evidence are missing.
`canonical_names=True` writes the canonical three filenames, including gzip,
for isolated finalization/fingerprint tests.

Focused coverage is in `test_microbedecoder_crosswalk_quarantine.py`,
`test_microbedecoder_crosswalk_witnesses.py`,
`test_microbedecoder_crosswalk_quarantine_emission.py`, and
`test_producer_audit_lifecycle.py`. New production acceptance still requires a
fresh producer run, finalization, guarded merge, and graph/model/path reviews;
passing these hermetic tests does not certify an existing release artifact.
