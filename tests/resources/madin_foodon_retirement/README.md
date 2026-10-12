# Exact native Madin / FOODON retirement evidence

Selected read-only from the existing pinned downloads on 2026-09-30. CSV
excerpts retain all columns and source values; only CRLF line endings in the
environment excerpt are normalized to LF. The OWL fixture contains the two
unchanged complete class elements inside a minimal namespace wrapper, not an
invented equivalence axiom. Do not refresh these immutable fixtures from live
services during tests.

| Canonical source | SHA-256 | Selected physical lines |
| --- | --- | --- |
| `data/raw/environments.csv` | `99299fe635159712f95568783ad3b484230fb31781262f1f6f8bd84db4bc3048` | Header and 76 |
| `data/raw/madin_etal.csv` | `6100fc11679cd9facae65cad37a2969978bc64c3e57984d896f8147f78db6440` | Header and 2126, 28894, 132957, 133427 |
| `data/raw/foodon.owl` | `1e11fc50283c6498697a7aca9606c9d914f1cda71cc5510e006d949c32df7db0` | 511496–511501 |
| `data/raw/po.owl` | `a066a2091b96dc6c960683a67936ccda4926afd96e4edb22df9e30feec16e9e0` | 38792–38803 |

Configured Madin inputs are the native repository's
[environment conversion table](https://raw.githubusercontent.com/bacteria-archaea-traits/bacteria-archaea-traits/master/data/conversion_tables/environments.csv)
and [condensed traits](https://github.com/bacteria-archaea-traits/bacteria-archaea-traits/blob/master/output/condensed_traits_NCBI.csv?raw=true).
Those mutable URLs are not version pins; the hashes above identify the inspected
local bytes. The ontology version IRIs recorded in those bytes are
`http://purl.obolibrary.org/obo/foodon/releases/2025-12-30/foodon.owl` and
`http://purl.obolibrary.org/obo/po/releases/2026-01-09/po.owl`.

`FOODON:03420174` is an explicitly deprecated `owl:Class` with exactly one
`IAO:0100001` replacement, `PO:0009011`. The replacement is an active named
plant-structure class, with parent `PO:0025131` (plant anatomical entity).
This is identifier-retirement authority, not a label match or a `same_as` claim.

The native habitat key is exactly `host_plant_vasculature`. Its identifier cell
contains `FOODON:03420174, UBERON:0002049` and its label cell contains
`part of plant, vasculature`. Replace only the exact FOODON token and its aligned
label. Preserve `UBERON:0002049`, its label, ordering, and all unrelated fields.
The correction table holds individual CURIEs so existing stub collection can
discover `PO:0009011`; a composite replacement cell would fail that contract.

The four native trait records have tax IDs 519050, 456493, 399742, and 324057.
Tests run the real producer over those unchanged records, with unrelated NER
and chemical enrichment isolated, then compare complete edge multisets. Exactly
four `location_of` subjects change; all objects, predicates, relations, primary
knowledge sources, knowledge levels and agent types, plus the four companion
vasculature assertions and other emitted assertions, are conserved.

Independent successor evidence under `data/resolve93-20260930.2qMze1/`:

- `foodon-03420174-native-retirement.json`, SHA-256
  `f4d13b02d77cc903f7c31dee41f16a6f0fbb695371abc90eff1b1e1e892236f2`.
- `foodon-blocking-edges-independent-review.json`, SHA-256
  `6bcf926103a3442da754480c365779d4ce01e6277eeff7a6c02958919df9feac`.
  This inventories the four original merged observations at physical lines
  14571028–14571031; neither original report nor merged graph is edited.

The reviewer JSON's FOODON `source_line` is 511497; direct text-line counting
locates the class opening at 511496 and its definition at 511497. The exact
class content and source hash agree. This note preserves the original report
instead of rewriting it. This finite upstream repair is not whole-graph
scientific acceptance, a validation waiver, or release authorization.
