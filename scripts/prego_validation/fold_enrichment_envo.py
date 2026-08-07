"""Fold enrichment of PREGO ENVO -location_of-> NCBITaxon vs BacDive isolation sources.

Prints the threshold curve
(precision and retention at candidate cutoffs) and the within-ENVO-term
stratified ratio, which is what controls for term degree — the raw fold numbers
do not (see #698).
"""
import bisect
from collections import defaultdict

strain_tax, env_strain = {}, []
with open("data/transformed/bacdive/edges.tsv") as fh:
    next(fh)
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) < 3:
            continue
        s, p, o = f[0], f[1], f[2]
        if s.startswith("kgmicrobe.strain:") and p == "biolink:subclass_of" and o.startswith("NCBITaxon:"):
            strain_tax[s] = o
        elif s.startswith("ENVO:") and p == "biolink:location_of" and o.startswith("kgmicrobe.strain:"):
            env_strain.append((s, o))
gold = {(e, strain_tax[s]) for e, s in env_strain if s in strain_tax}
genv = {e for e, _ in gold}
gtax = {t for _, t in gold}
print(f"  gold: {len(gold):,} ENVO->taxon pairs ({len(genv):,} ENVO, {len(gtax):,} taxa)")

labelled, all_scores = [], []
per_term = defaultdict(list)
shared_env, shared_tax = set(), set()
with open("data/transformed/prego/edges.tsv") as fh:
    h = next(fh).rstrip("\n").split("\t")
    si, oi, sci = h.index("subject"), h.index("object"), h.index("prego_score")
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) <= sci:
            continue
        s, o = f[si], f[oi]
        if not (s.startswith("ENVO:") and o.startswith("NCBITaxon:")):
            continue
        try:
            v = float(f[sci])
        except ValueError:
            continue
        all_scores.append(v)
        if s in genv:
            shared_env.add(s)
        if o in gtax:
            shared_tax.add(o)
        if s in genv and o in gtax:
            hit = (s, o) in gold
            labelled.append((v, hit))
            per_term[s].append((v, hit))

# Baseline over the SHARED entity space, per the TISSUES protocol.
base = sum(1 for e, t in gold if e in shared_env and t in shared_tax) / (len(shared_env) * len(shared_tax))
labelled.sort()
all_scores.sort()
n_all = len(all_scores)
print(f"  comparable {len(labelled):,} of {n_all:,} ENVO edges | baseline {base:.5f}\n")
print(f"  {'>= T':>6} {'overlap':>10} {'fold':>8} {'kept':>10} {'kept %':>8}")
for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
    sub = [h for v, h in labelled if v >= t]
    if not sub:
        continue
    p = sum(sub) / len(sub)
    kept = n_all - bisect.bisect_left(all_scores, t)
    print(f"  {t:>6.2f} {p:>10.4f} {p / base:>7.2f}x {kept:>10,} {100 * kept / n_all:>7.2f}%")

up = dn = lo_h = lo_n = hi_h = hi_n = 0
for _term, rows in per_term.items():
    if len(rows) < 100:
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
print(f"\n  within-term (>=100 edges): {up + dn} terms, higher-score half agrees MORE in {up}")
print(f"    pooled low {lo_h / lo_n:.4f} vs high {hi_h / hi_n:.4f} -> {(hi_h / hi_n) / (lo_h / lo_n):.2f}x")
