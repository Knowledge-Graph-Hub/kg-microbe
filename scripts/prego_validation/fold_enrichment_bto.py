"""Fold enrichment of PREGO BTO -location_of-> NCBITaxon vs BacDive host anatomy.

BacDive records host/tissue isolation against UBERON and CL, not BTO. The
crosswalk is already in-repo: 1,645 anatomy terms in the ontologies output carry
BTO xrefs. This is the same reverse-lookup the prego transform uses for
DOID->MONDO, so no new mapping is needed — an earlier assessment wrongly
concluded these edges were untestable.
"""
from collections import defaultdict

u2b = defaultdict(set)
with open("data/transformed/ontologies/uberon_nodes.tsv") as fh:
    h = next(fh).rstrip("\n").split("\t")
    xi = h.index("xref")
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) <= xi or "BTO:" not in f[xi]:
            continue
        for x in f[xi].split("|"):
            if x.startswith("BTO:"):
                u2b[f[0]].add(x)
print(f"  crosswalk: {len(u2b):,} anatomy terms -> {len({b for v in u2b.values() for b in v}):,} BTO terms")

strain_tax, anat_strain = {}, []
with open("data/transformed/bacdive/edges.tsv") as fh:
    next(fh)
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) < 3:
            continue
        s, p, o = f[0], f[1], f[2]
        if s.startswith("kgmicrobe.strain:") and p == "biolink:subclass_of" and o.startswith("NCBITaxon:"):
            strain_tax[s] = o
        elif p == "biolink:location_of" and o.startswith("kgmicrobe.strain:") and s.split(":")[0] in ("UBERON", "CL"):
            anat_strain.append((s, o))
gold = set()
for anat, strain in anat_strain:
    taxon = strain_tax.get(strain)
    if taxon:
        for bto in u2b.get(anat, ()):
            gold.add((bto, taxon))
gbto = {b for b, _ in gold}
gtax = {t for _, t in gold}
print(f"  gold: {len(gold):,} BTO->taxon pairs ({len(gbto):,} BTO, {len(gtax):,} taxa)")

per_term = defaultdict(list)
agg = defaultdict(lambda: [0, 0])
shared_bto, shared_tax = set(), set()
n = 0
with open("data/transformed/prego/edges.tsv") as fh:
    h = next(fh).rstrip("\n").split("\t")
    si, oi, sci = h.index("subject"), h.index("object"), h.index("prego_score")
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) <= sci:
            continue
        s, o = f[si], f[oi]
        if not (s.startswith("BTO:") and o.startswith("NCBITaxon:")):
            continue
        n += 1
        if s in gbto:
            shared_bto.add(s)
        if o in gtax:
            shared_tax.add(o)
        if s in gbto and o in gtax:
            try:
                v = float(f[sci])
            except ValueError:
                continue
            hit = (s, o) in gold
            slot = agg[round(v, 4)]
            slot[0] += 1
            slot[1] += 1 if hit else 0
            per_term[s].append((v, hit))

comp = sum(v[0] for v in agg.values())
hits = sum(v[1] for v in agg.values())
# Baseline over the SHARED entity space, per the TISSUES protocol: gold
# terms PREGO never mentions are not part of the space it selects from, and
# including them deflates the null and inflates every fold figure.
base = sum(1 for b, t in gold if b in shared_bto and t in shared_tax) / (len(shared_bto) * len(shared_tax))
print(f"  prego BTO edges {n:,} | comparable {comp:,} ({100 * comp / n:.2f}%)")
print(f"  baseline {base:.5f} | overall fold {(hits / comp) / base:.2f}x")

up = dn = lo_h = lo_n = hi_h = hi_n = 0
for _term, rows in per_term.items():
    if len(rows) < 30:
        continue
    rows.sort(key=lambda r: r[0])
    # Tie-safe boundary: move the split to the next score change. An index
    # median splits a tie block, letting sort order rather than the score
    # decide which rows land in which half — the same defect fixed in
    # quality.enrichment_by_window. It materially moved these numbers.
    mid = len(rows) // 2
    while mid < len(rows) and rows[mid][0] == rows[mid - 1][0]:
        mid += 1
    if mid == 0 or mid >= len(rows):
        continue
    lo, hi = rows[:mid], rows[mid:]
    a = sum(1 for _, x in lo if x) / len(lo)
    b = sum(1 for _, x in hi if x) / len(hi)
    lo_h += sum(1 for _, x in lo if x)
    lo_n += len(lo)
    hi_h += sum(1 for _, x in hi if x)
    hi_n += len(hi)
    up, dn = (up + 1, dn) if b > a else (up, dn + 1)
print(f"\n  within-term (>=30 edges): {up + dn} terms, higher-score half agrees MORE in {up}")
print(f"    pooled low {lo_h / lo_n:.4f} vs high {hi_h / hi_n:.4f} -> {(hi_h / hi_n) / (lo_h / lo_n):.2f}x")
