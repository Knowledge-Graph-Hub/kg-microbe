# Ingredient occurrence and registry context in KGX

The explicit `mim_ingredients` transform consumes the reviewed lookup candidate
from `INGREDIENT_BUNDLE.md`. It does not ingest all CultureMech graphs (#905) or
change the production ingredient download pin (#1123). Its source selection is
`<raw>/mim_ingredients/selection.json`:

```json
{"mode":"candidate_only","lookup_directory":"/path/to/lookup-candidate","lookup_manifest_sha256":"<reviewed SHA-256>"}
```

Run `poetry run kg transform -s mim_ingredients --help` for the standard transform
options. Direct Python callers can instantiate `MIMIngredientsTransform(raw,
output)`, call `run()`, then `finalize(fresh_run=True)`. Standard CLI dispatch also
writes the source fingerprint used by public merge admission. The actual run
records the selection, every lookup/bundle member, and original review evidence
as consumed inputs. A failed run remains ineligible for finalization until an
explicit new run begins. Source finalization also requires local FoodOn data when
FoodOn nodes are present.

## What the nodes and assertions mean

Generic ingredient nodes retain the reviewed canonical identity and current CAS
xref set. No product preparation, catalog number or supplier is added to their
names, synonyms or universal properties. A catalog record is a supplier's product
specification; it is not a physical lot, an ingredient ontology subclass or an
assertion of molecular identity. Distinct product IDs remain distinct even when
they have the same CAS xref.

`MIM.product`, `MIM.annotation`, `MIM.mapping`, and `MIM.source` nodes are typed
`biolink:InformationContentEntity`. Their edges use `biolink:related_to` with
`relation=IAO:0000136` (is about). Biolink 4.4.2 explicitly lists that IAO relation
under the narrower mappings of `related to`. These edges describe what a source
record or reviewed claim is about; they do not assert every reported claim is
accepted as active chemical knowledge.

| Record | Assertion payload | Meaning |
| --- | --- | --- |
| Catalog record → ingredient | `ingredient_product_json` | Original supplier, catalog number, preparation, source payload, evidence and review state |
| Identifier annotation → owning entity | `ingredient_annotation_json` | Full original identifier/source/status/version/evidence tuple, including rejected or historical claims |
| Mapping review record → resolved source concept | `ingredient_mapping_json` | Original SSSOM row, scope and explicit identity authorization |
| Source record → ingredient | `ingredient_occurrence_json` | Original recipe/observation occurrence, quantity, preparation, selected product or alternatives |

This is the linked registry-annotation table in graph form. Filtering edges with
`ingredient_annotation_json` yields one intact claim per row; the subject names
the stable annotation, and the object names its projected canonical owner. It
survives an ordinary graph-only archive because it is part of the graph. Evidence
URNs and JSON pointers identify bytes in the separately retained pinned producer
bundle; they are not replaced by invented web citations. Every context assertion
also carries `ingredient_bundle_sha256`.

A source record uses `MIM.source:SHA256(canonical_JSON(source_id))`, distinguishing
a recipe's information record from a growth-medium material using the original
CultureMech ID. The original source ID is its xref and remains in the assertion's
`publications` and structured payload. The primary information resource is
`infores:mediaingredientmech`, which publishes the reviewed interpretation.

The seven BSA recipe occurrences remain separate assertions. Only the original
CultureBotHT record selects A7030. CultureMech:015191 retains one explicit
`one_of`/`UNSPECIFIED` group containing A9647 and A7409. No selected-product or
confirmed-use edge is emitted for either unselected alternative. Both product
records remain independently queryable. Missing concentrations and CAS values are
not inferred.

## Typed extension transport

The application contract is `kg_microbe/profiles/ingredient_kgx_v1.yaml`.
`ingredient_profile` is one CURIE; `ingredient_record_kind` is one node enum;
`ingredient_bundle_sha256` is one edge digest. The four `*_json` fields each hold
one canonical JSON object as a **scalar** TSV field. Their nested field types and
cardinalities come from the producer's `ingredient_bundle_v1.schema.json`:
quantities are object-or-null, preparation is string-or-null, evidence is an array
of document/pointer objects, and alternatives are arrays of explicit option
groups. Tabs/newlines are JSON-escaped; quotes and literal pipes retain their
meaning. A pipe inside JSON is never an array delimiter.

`ingredient_occurrence_id` is one stable occurrence CURIE. Optional
`ingredient_product_id` is populated only when the original occurrence explicitly
selects a product. Both must agree with the full structured occurrence. Canonical
TSV validation rejects unknown profiles, pooled scalars, duplicate JSON keys,
non-finite values, malformed claim types and inconsistent selected products. Merge
uses its existing complete-assertion key, so different preparation or evidence
stays on a different assertion even if its endpoints are identical.

Supported broad/narrow mappings retain explicit broad-match semantics; narrower
rows reverse to a normalized `biolink:broad_match` edge while the original row
remains in its payload. An unreviewed or withheld mapping remains a review record.
No exact, close or broad mapping creates `same_as` or an inferred subclass. Native
ontology classification is supplied independently by its ontology transform.

Namespaces are registered in the application profile, project prefix map and
pinned KGX context. The existing MIM source namespace is preserved. These are
application extensions, not new standard SSSOM or Biolink slots.

Validation: `tests/test_ingredient_kgx.py` runs the actual producer export through
consolidation, lookup, this transform, source finalization, public KGX merge,
archive/loose serialization and reload. The general activation matrix is #1136.
References: [KGX format](https://biolink.github.io/kgx/kgx_format.html) and
[Biolink 4.4.2](https://github.com/biolink/biolink-model/blob/v4.4.2/biolink-model.yaml).
