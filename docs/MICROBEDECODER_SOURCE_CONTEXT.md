# MicrobeDecoder source assertion context

Issues #1076 and #1083 repair evidence loss in the **producer**. A merge cannot
reconstruct source columns or qualifiers from the old value-only trait nodes.
Rebuild the MicrobeDecoder transform before merging; do not edit a historical
merged graph to guess the lost distinctions.

## Identity and evidence

Snapshot trait placeholder IDs use the `kgmicrobe.trait:` namespace, a readable
column slug, and the full SHA-256 of the UTF-8 JSON pair `[source_column, token]`
(no extra JSON whitespace). Tokens are the source parser's trimmed multivalue
tokens, not interpreted phenotype codes. In particular:

- Motility `0` and spore formation `0` are distinct placeholders.
- Salt concentration `<1`, `1`, and `>1` are distinct placeholders.
- Identical column/token pairs share a placeholder across records.
- A value of `0` is **not** automatically interpreted as a negative phenotype.

Names include the dimension and token, ending in `(source value)`. Curators can
later map the coding convention to a phenotype ontology; these placeholder
names do not establish that biological interpretation.

Snapshot and metabolism assertions retain these scalar fields:

| Field | Meaning |
| --- | --- |
| `source_column` | Exact source CSV column that produced the assertion. |
| `source_record` | `sha256:<CSV byte digest>#record=<1-based data-record ordinal>`. Quoted multiline CSV cells do not change record counting. |
| `value` | Source token, including numeric operators and leading zeros. |
| `value_encoding` | `backslash`, declaring reversible literal encoding below. |
| `description` | Snapshot dimension or metabolism `major`/`minor` qualifier. |
| `source_citation` | Complete literature citation text or Bergey article link, even when no identifier is recognized. |
| `source_citation_base64` | Exact original citation-cell bytes, base64 encoded, including rare malformed UTF-8 bytes. |
| `publications` | Sorted distinct explicitly recognized DOI/PMID CURIEs, pipe-separated according to the Biolink multivalued slot. |

Crosswalk assertions also retain `source_record`; their existing
`original_object` evidence remains unchanged. Source records anchor the exact
raw input version. They are not claims that two CSV rows are independent
biological experiments, and a changed CSV digest intentionally identifies a
new source snapshot.

## Literal TSV contract

This producer declares `TSV_QUOTING = csv.QUOTE_NONE`, matching KGX TSV input.
Literal quotes are not CSV-escaped. In `value`, `source_citation`, and display
text, a literal backslash is encoded as `\\`, tab as `\t`, carriage return as
`\r`, and newline as `\n`. Decode left to right, consuming each escape once;
do not use repeated replacements or a general-purpose Unicode escape decoder.
Ordinary codes and numeric operators are unchanged. The complete raw CSV bytes
remain addressable by the source-record digest; the source's existing UTF-8
replacement-decoding policy for rare malformed name bytes is not a claim of
byte-perfect display decoding. `source_citation_base64` preserves the exact
citation bytes independently of that display policy.

Source deduplication uses complete rows and literal string types. It must not
coerce `0`/`00` to numbers, interpret text as NA, drop differing citations or
qualifiers, or pool scalar fields into pipe lists. KGX preserves the resulting
complete assertion/evidence bundles; only identical assertions deduplicate.

## Regression and real-source evidence

`tests/test_microbedecoder_context.py` exercises source generation, repeated
runs, numeric/operator distinctions, literal encoding, citations and a real
KGX archive round trip. Fixtures are immutable and require no live services.

The first isolated real-source canary used CSV SHA-256
`0c6ff730a108720a5d6972400f2bccf2eca8621713b62736abdf5df0fb188c95`.
It retained all **362,472 unique source-record/column/token snapshot assertions**
with zero missing or invented tokens, and recovered **4,357** subject/column/value
distinctions previously collapsed into the old `trait:0` and `trait:1` buckets.
Its 516,678 total edges reflect retained context, not fabricated observations.
The audit is under `data/remediation-microbedecoder-20260914.afqqwh/`; it is a
producer canary, not evidence that the final merged release has been rebuilt.

Round-1 independent review found three related defects, tracked by #1083–#1085:
50 identifier-free literature citation cells, 8,166 omitted Bergey article
links, mapping infrastructure failures treated as successful no-matches, and
148 numeric-locant cells whose chemical names were split at internal commas.
The producer now retains citation text/bytes and all recognized identifiers,
propagates mapping failures (while ordinary no-match remains `None`), and
protects numeric locants followed by a name hyphen. It is not a general
chemical-name parser: ambiguous nonnumeric commas still require curation.
Identity crosswalk splitting is unchanged. Separate immutable literal-token
tests cover `2,3-butanediol` and `endo-1,4-beta-xylanase`; the original canary's
expected set reused the then-current splitter and did not establish token
semantic correctness. Its counts above are a round-1 baseline, not final
post-tokenization counts.

The round-2 producer rebuild on the same raw CSV retained **362,361** unique
snapshot assertions and wrote **516,528** total edges after the numeric-locant
repair. It recovers **4,355** zero/one dimension distinctions; the two-count
change from round 1 removes fragments invented by the old chemical tokenizer.
The exhaustive record/column/token comparison has zero missing or extra
assertions under the current parser. Independently specified checks also match
the raw `2,3-butanediol` and `endo-1,4-beta-xylanase` examples. Exact citation-cell
bytes match the raw CSV on **15,013 Bergey** and **463 literature** assertions.
These remain isolated producer acceptance results, not a rebuilt merged release.
