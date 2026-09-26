# Indeterminate MetaTraits regression fixture (#1181)

`metatraits_indeterminate.json` projects the complete summary and taxon name
from the immutable NCBI species source, SHA256
`1881360fb0ae1f28bdbd7d307ed0f7815044b0aa8ad0d769e0ee68f64d431ce7`,
line 21287, summary 114 (one-based). It was independently retained in
`special55-majority-census-v2-20260926/unparsed-majority.jsonl`, SHA256
`713de32b7c31d4ebcc444557d686097cd907041f3a97226df084208e68088b42`.
The full original record contains additional summaries not needed here.
Native NCBITaxon labels identify this species as `NCBITaxon:1462`.

The source explicitly says `No robust majority` despite `true: 80.0`.
The transform must not infer either sign from the percentage. The existing
arsenate mapping and native predicate pair are CHEBI:29125,
METPO:2000017 (positive) and METPO:2000044 (negative).

Tests also derive **synthetic controls**, explicitly changing trait names,
majority labels or quantities. Those are not additional observed source records.
They exercise Tier 1, manual, special chemical, direct fermentation and phenotype
routes, true/false/empty compatibility, quantitative handling, duplicate
preservation and JSON scalar types. GTDB uses the same fixture for inherited
dispatch coverage, not as a claim that the NCBI record is an original GTDB row.

The new `indeterminate_traits.jsonl` contains each deferred regular summary
reached after taxon admission, with its full typed summary, original taxon name,
resolved taxon, provider and reason. It preserves repeats and makes no claim
about global line numbers in worker chunks. Unresolved taxonomy still follows
the existing separate diagnostic path; quantitative/measurement handling is
unchanged. These diagnostics are **not covered by the standard graph-member
finalization receipt**: postbuild review must hash/admit them separately alongside
the immutable raw inputs. A diagnostic is retained evidence, not a KG assertion.
