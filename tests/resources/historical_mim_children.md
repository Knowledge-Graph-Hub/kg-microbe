# Historical MIM child-reader fixture

`historical_mim_children.sssom.tsv` is an explicit, minimal mechanism fixture.
It represents the former unified child/parent shapes with declared SKOS
semantics (`child broadMatch parent`); it is not an authoritative chemical
mapping source, nor permission to restore its rows to production.

The original production-dependent tests were based on older MIM mappings with
legacy `narrowMatch` direction. Keep this fixture's reader regression separate
from the reviewed production product and from the independent legacy/SKOS
direction tests in `test_sssom_predicate_semantics.py`.

## Content-bound admission evidence

Upstream source commit: `1848b0fe521bc2462f165912fcf92d09ad9a8cec`.

| Product | SHA256 |
| --- | --- |
| `manifest.json` | `9bb29d5605d93dea351be9624d99c5d8ada57d4b9831b22764957b784bd685af` |
| `mapping-dispositions.tsv` | `87b4a72969681e4b808c526552c84c36daa17c6697970735a4e0ba0270523154` |
| supported `ingredient_mappings.sssom.tsv` | `6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb` |
| `withheld_mappings.sssom.tsv` | `c37491ed4191889d375b02510137a178ee9b44a341131e42afec07d7953e8405` |

| Subject | Exact local registry row | External broad-match row | Disposition positions (exact / broad) |
| --- | --- | --- | --- |
| `MIM:Vermont_Soil` | `kgmicrobe.ingredient:vermont_soil`: SUPPORTED | `ENVO:00001998`: WITHHOLD | 2913 / 2912 |
| `MIM:Beef_Brain_Powder` | `kgmicrobe.ingredient:beef_brain_powder`: SUPPORTED | `FOODON:02020911`: WITHHOLD | 499 / 498 |
| `MIM:Actinomycin_A` | `kgmicrobe.compound:actinomycin_a`: WITHHOLD | `CHEBI:15369`: WITHHOLD | 298 / 297 |

Actinomycin A's exact row is withheld because its owner bytes changed after the
evidence snapshot. Parent rows await explicit relation/synonym-scope review;
beef-brain source material alone does not establish that the prepared powder is
a kind of that material. The real-artifact tests therefore require the two
supported local identities without those parents and no Actinomycin A unified
identity. These current-product assertions can change only with new reviewed
evidence; withholding is not a global denial of future independent support.
