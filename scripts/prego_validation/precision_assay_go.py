"""
Direct precision test: do PREGO's high-score edges hit assay-POSITIVE pairs?

Assay evidence gives labelled negatives, so precision is measurable without
any null model — sidestepping the Cartesian-baseline confound entirely.
BacDive phenotype assays are also provenance-disjoint from both UniProt
(genome annotation) and metatraits (trait curation).
"""
import pickle
from collections import defaultdict

tri = pickle.load(open("/tmp/assay_gold.pkl", "rb"))
# Unanimous labels only; conflicting strain-level evidence is excluded.
label = {}
for k, (p, n) in tri.items():
    if p and not n: label[k] = 1
    elif n and not p: label[k] = 0

agg = {"continuous": defaultdict(lambda: [0, 0]), "flat": defaultdict(lambda: [0, 0])}
n = matched = 0
with open("data/transformed/prego/edges.tsv") as fh:
    h = next(fh).rstrip("\n").split("\t")
    si, oi, sci, chi = h.index("subject"), h.index("object"), h.index("prego_score"), h.index("prego_channel")
    is_cont, layout = continuous_predicate(h)
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) <= max(sci, chi): continue
        s, o = f[si], f[oi]
        if not (s.startswith("NCBITaxon:") and o.startswith("GO:")): continue
        n += 1
        lab = label.get((s, o))
        if lab is None: continue
        matched += 1
        try: v = float(f[sci])
        except ValueError: continue
        slot = agg["continuous" if is_cont(f) else "flat"][round(v, 4)]
        slot[0] += 1
        slot[1] += lab

assert_non_empty(sum(v[0] for v in agg["continuous"].values()), layout)
print(f"  layout: {layout}")
print(f"  prego taxon->GO edges          : {n:,}")
print(f"  with unanimous assay evidence  : {matched:,} ({100*matched/n:.3f}%)")
print(f"  assay labels available         : {len(label):,} "
      f"({sum(label.values()):,} positive / {len(label)-sum(label.values()):,} negative)\n")

for name in ("continuous", "flat"):
    d = agg[name]
    tot = sum(v[0] for v in d.values())
    if not tot: continue
    hits = sum(v[1] for v in d.values())
    print(f"  === {name}: {tot:,} labelled edges | precision {hits/tot:.4f}")
    print(f"    {'window':>7} {'score range':>20} {'n':>9} {'precision':>10}  note")
    target = tot / 5
    cn = ch_ = 0; lo = prev = None; w = 0
    for sv in sorted(d):
        c, hh = d[sv]
        if lo is None: lo = sv
        cn += c; ch_ += hh; prev = sv
        if cn >= target and w < 4:
            w += 1
            note = "TIED" if lo == prev else ""
            print(f"    {w:>7} {lo:>9.3f}-{prev:<9.3f} {cn:>9,} {ch_/cn:>9.4f}  {note}")
            cn = ch_ = 0; lo = None
    if cn:
        note = "TIED" if lo == prev else ""
        print(f"    {w+1:>7} {lo:>9.3f}-{prev:<9.3f} {cn:>9,} {ch_/cn:>9.4f}  {note}")
    print()
