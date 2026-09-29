# Finite MicrobeDecoder material dispositions

This catalogue records scientific review of **13 existing local material IDs,
240 source assertions and 235 complete raw records** from the selected #650
cohort. It does not ground those materials to external chemical identities,
alter MIM's pinned supported mappings, change graph nodes/edges, or approve a
graph release. Every row explicitly retains `identity_status=unresolved` and
`identity_approved=false`.

`mappings/canonical/microbedecoder_material_dispositions.tsv` has one row per
reviewed record/field/literal use. These are not 240 independent experiments
or 235 distinct taxonomic identities. The source subject is an LPSN name record;
different raw records can point to the same accepted LPSN subject.

## Exact scope and provenance

Each row carries:

- `source_record`: the original whole-CSV SHA-256 and CSV-record ordinal;
- `raw_record_sha256`: all raw fields serialized as sorted compact JSON,
  `ensure_ascii=False`, `allow_nan=False`, UTF-8 with `surrogateescape`, without
  a trailing newline; it is independent of the ordinal and column ordering;
- original subject, field, literal, citation, existing local object,
  scientific predicate/relation, knowledge source, knowledge level and agent;
- a semantic disposition, unresolved identity status, evidence URI(s) and
  field/record-specific curation rationale.

Literal and citation cells use the producer's finalized backslash display
encoding. The complete-record hash preserves the original CSV fields instead
of treating that display encoding as the source bytes. Major/minor products
remain distinguished by their exact source columns.

No wildcard, case-folding, normalized global alias, substrate decomposition,
external target or same-as relation is authorized. The two existing `sugar`
nodes remain distinct and keep the user's approved **record-scoped unresolved**
policy; "approved" there describes the preservation policy, not chemical
identity. Registry-local MIM identities are likewise not ontology groundings.

## Dispositions and remaining scientific uncertainty

| Reviewed context | Assertions | Meaning preserved |
| --- | ---: | --- |
| PYG | 114 | Named medium, with unknown specific recipe; not exact MICRO:0001573. |
| PYGS | 3 | Three strain-matched descriptions expand the name to peptone–yeast extract–glucose–starch broth; no complete recipe or independent component consumption inferred. |
| CMC + PY + horse serum | 1 | Separate culture-preparation contexts; CMC is not assumed to be carboxymethylcellulose. |
| H2+CO2 and cyclopentanol+CO2 | 101 | Joint conditions, not individual molecules or independent component-use assertions. |
| Mono-/disaccharides and sugars | 14 | Substrate-class descriptions, not an identified sugar or physical mixture. |
| Peptones | 2 | Unspecified protein digest; mammalian origin/formulation unproved. |
| Isopropionate and 3-methylacetate | 2 | Unresolved product identities, with original literal and source role retained. |
| Aminovalerate | 1 | Identity unresolved; culture-authenticity/phenotype warning cannot establish either a positive or negative result. |
| Record-scoped sugar | 2 | Original distinct nodes preserved without NCIT:C71939 substitution. |
| **Total** | **240** | **Disposition reviewed; chemical identities unresolved.** |

The catalogue's citations distinguish primary growth evidence from source
vocabulary interpretation. In particular, the Methanolacinia paynteri
cyclopentanol/CO2 record is not claimed to have strain-specific growth verified
from an abstract that separately describes enzyme assays. No blanket primary
revalidation of all 240 observations is claimed.

Pinned MIM record links refer to commit
`1848b0fe521bc2462f165912fcf92d09ad9a8cec`, not the sibling checkout's floating
state. They document reviewed limitations rather than importing withheld
mappings. The public-target restrictions for PYG and peptones must not be
overridden by a matching acronym/plural synonym.

## Loader and optional cohort diagnostics

```python
from kg_microbe.transform_utils.microbedecoder.material_dispositions import (
    MaterialDispositionCuration,
)

materials = MaterialDispositionCuration()  # or a caller-owned consumed-input stream
decision = materials.resolve_edge(edge)
```

`resolve_edge` returns an immutable decision only for an exact known
record/field/literal. It checks the original subject, local object, citation,
scientific route and evidence tier; a changed witness for a known use raises
`ValueError`. An unseen record, snapshot, field or literal returns `None` and
remains unreviewed. Consumers must continue reporting the identity as
unresolved and must not replace `object` or the edge predicate with a
disposition label.

The table is an **inventory dependency, not a transform dependency**. A future
source download must not stop transforming merely because it is not this
reviewed cohort. It also must not inherit these reviews by matching material
names alone. If an inventory consumes the table, include its actual file bytes
in that inventory's consumed-input/fingerprint contract.

Two explicit diagnostic methods are available:

```python
materials.validate_raw(raw_csv_path)
materials.validate_edges(source_edges_path, require_all=True)
```

The raw check requires the exact reviewed source snapshot, verifies complete
records plus literal/citation membership, and detects missing records or
input changes. The edge check streams finalized source rows, rejects duplicate
known assertions and changed evidence, and optionally requires all reviewed
uses. `require_all=False` permits partial/other snapshots while reporting
matched counts, missing reviewed uses, snapshot applicability and whether the
cohort is complete. The downstream inventory should request strict coverage
only when explicitly checking this reviewed cohort, not for every old fixture
or later source snapshot.

For the selected evidence, raw source SHA-256 is
`0c6ff730a108720a5d6972400f2bccf2eca8621713b62736abdf5df0fb188c95`.
The closed continuation-source edge witness SHA-256 is
`1f00bad342261fee143ebcaeaed10b49459011e3a1f7a8500532d47bbcce17b6`.
These describe the reviewed source artifacts, not the hash or acceptance of a
current production merged archive.

Hermetic regression coverage lives in
`tests/test_microbedecoder_material_dispositions.py`; its raw fixture is a
tiny synthetic immutable CSV, not a redistributed 27,010-record source.
