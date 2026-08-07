"""Fold enrichment with tie-safe windows (boundaries only fall on score changes)."""
import pickle
from collections import defaultdict

gold, gtaxa, ggos = pickle.load(open("/tmp/uniprot_gold.pkl", "rb"))

def is_cont(ch):
    p = ch.split()
    return len(p) == 4 and p[1] == "of" and p[3] == "samples" and p[0].isdigit()

# score -> [n, hits], per channel. Aggregating by exact score keeps ties atomic.
agg = {"continuous": defaultdict(lambda: [0, 0]), "flat": defaultdict(lambda: [0, 0])}
stax, sgos = set(), set()
n = 0
with open("data/transformed/prego/edges.tsv") as fh:
    h = next(fh).rstrip("\n").split("\t")
    si, oi, sci, chi = h.index("subject"), h.index("object"), h.index("prego_score"), h.index("prego_channel")
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) <= max(sci, chi): continue
        s, o = f[si], f[oi]
        if not (s.startswith("NCBITaxon:") and o.startswith("GO:")): continue
        n += 1
        try: t = int(s[10:]); g = int(o[3:]); v = float(f[sci])
        except ValueError: continue
        if t in gtaxa: stax.add(t)
        if g in ggos: sgos.add(g)
        if t in gtaxa and g in ggos:
            key = "continuous" if is_cont(f[chi]) else "flat"
            slot = agg[key][round(v, 4)]
            slot[0] += 1
            slot[1] += 1 if g in gold.get(t, ()) else 0

base = sum(len(gold[t] & sgos) for t in stax if t in gold) / (len(stax) * len(sgos))
print(f"  baseline {base:.5f} | shared taxa {len(stax):,} GO {len(sgos):,}\n")

for name in ("continuous", "flat"):
    d = agg[name]
    if not d: continue
    total = sum(v[0] for v in d.values()); hits = sum(v[1] for v in d.values())
    print(f"  === {name}: {total:,} pairs, hit rate {hits/total:.4f}, fold {(hits/total)/base:.2f}x")
    print(f"    {'window':>7} {'score range':>20} {'n':>11} {'hit rate':>9} {'fold':>7}  note")
    target = total / 5
    cn = ch_ = 0; lo = None; prev = None; w = 0
    for sv in sorted(d):
        cnt, hh = d[sv]
        if lo is None: lo = sv
        cn += cnt; ch_ += hh; prev = sv
        if cn >= target and w < 4:
            w += 1
            note = "TIED — ordering artifact, ignore" if lo == prev else ""
            print(f"    {w:>7} {lo:>9.3f}-{prev:<9.3f} {cn:>11,} {ch_/cn:>8.4f} {(ch_/cn)/base:>6.2f}x  {note}")
            cn = ch_ = 0; lo = None
    if cn:
        note = "TIED — ordering artifact, ignore" if lo == prev else ""
        print(f"    {w+1:>7} {lo:>9.3f}-{prev:<9.3f} {cn:>11,} {ch_/cn:>8.4f} {(ch_/cn)/base:>6.2f}x  {note}")
    print()
