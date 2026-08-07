"""Build a taxon->GO gold standard WITH NEGATIVES from BacDive assay results.

BacDive records assay outcomes with polarity — METPO:2000302 "shows activity of"
and METPO:2000303 "does not show activity of" — so chaining

    strain -(polarity)-> assay -has_output-> GO

and lifting strain to NCBITaxon via subclass_of yields both positives and
negatives. That is what makes precision measurable without a null model, unlike
every other gold standard available in-graph.

Pairs where one strain tested positive and another negative for the same species
are recorded as conflicting and must be excluded by the consumer: picking a side
would invent evidence.

Writes /tmp/assay_gold.pkl as {(taxon, go): [n_pos, n_neg]}.
"""
import pickle
from collections import defaultdict

EDGES = "data/transformed/bacdive/edges.tsv"
POS, NEG = "METPO:2000302", "METPO:2000303"

assay_go, strain_tax = {}, {}
strain_assays = defaultdict(list)
with open(EDGES) as fh:
    next(fh)
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) < 3:
            continue
        s, p, o = f[0], f[1], f[2]
        if s.startswith("kgmicrobe.assay:") and p == "biolink:has_output" and o.startswith("GO:"):
            assay_go.setdefault(s, set()).add(o)
        elif s.startswith("kgmicrobe.strain:") and p == "biolink:subclass_of" and o.startswith("NCBITaxon:"):
            strain_tax[s] = o
        elif p in (POS, NEG) and o.startswith("kgmicrobe.assay:"):
            strain_assays[s].append((o, p))

print(f"  assays with a GO output : {len(assay_go):,}")
print(f"  strain->NCBITaxon links : {len(strain_tax):,}")
print(f"  strains with +/- results: {len(strain_assays):,}")

tri = defaultdict(lambda: [0, 0])
for strain, results in strain_assays.items():
    taxon = strain_tax.get(strain)
    if not taxon:
        continue
    for assay, polarity in results:
        for go in assay_go.get(assay, ()):
            tri[(taxon, go)][0 if polarity == POS else 1] += 1

pos = sum(1 for v in tri.values() if v[0] and not v[1])
neg = sum(1 for v in tri.values() if v[1] and not v[0])
mix = sum(1 for v in tri.values() if v[0] and v[1])
print(f"\n  (taxon,GO) pairs with assay evidence: {len(tri):,}")
print(f"    unanimous POSITIVE : {pos:,}")
print(f"    unanimous NEGATIVE : {neg:,}")
print(f"    conflicting        : {mix:,}  (exclude — one strain +, another -)")
print(f"  distinct taxa {len({k[0] for k in tri}):,}  distinct GO {len({k[1] for k in tri}):,}")
pickle.dump(dict(tri), open("/tmp/assay_gold.pkl", "wb"))
