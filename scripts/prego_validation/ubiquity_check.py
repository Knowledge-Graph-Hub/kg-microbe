"""
Test whether PREGO's score measures ubiquity rather than confidence.

Hypothesis: the environmental-samples score rewards co-occurrence frequency,
so a GO term attached to many taxa (generic, ubiquitous) scores higher than a
specific one. If true, thresholding up selects generic annotations.

Prediction: within the continuous channel, a GO term's taxon degree should
correlate POSITIVELY with its mean score.
"""
from collections import defaultdict


def is_cont(ch):
    p = ch.split()
    return len(p) == 4 and p[1] == "of" and p[3] == "samples" and p[0].isdigit()

deg = defaultdict(int)      # GO -> distinct taxa (approximated by edge count)
tot = defaultdict(float)    # GO -> summed score
with open("data/transformed/prego/edges.tsv") as fh:
    h = next(fh).rstrip("\n").split("\t")
    si, oi, sci, chi = h.index("subject"), h.index("object"), h.index("prego_score"), h.index("prego_channel")
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) <= max(sci, chi): continue
        if not (f[si].startswith("NCBITaxon:") and f[oi].startswith("GO:")): continue
        if not is_cont(f[chi]): continue
        try: sc = float(f[sci])
        except ValueError: continue
        deg[f[oi]] += 1
        tot[f[oi]] += sc

rows = [(deg[g], tot[g] / deg[g], g) for g in deg if deg[g] >= 50]
rows.sort()
print(f"  GO terms with >=50 continuous-channel edges: {len(rows):,}\n")
print(f"  {'ubiquity decile':>15} {'degree range':>22} {'terms':>7} {'mean score':>11}")
k = len(rows) // 10
for d in range(10):
    lo, hi = d * k, (d + 1) * k if d < 9 else len(rows)
    w = rows[lo:hi]
    if not w: continue
    ms = sum(r[1] for r in w) / len(w)
    print(f"  {d+1:>15} {w[0][0]:>9,}-{w[-1][0]:<11,} {len(w):>7,} {ms:>10.3f}")

# Spearman-ish: rank correlation between degree and mean score
n = len(rows)
by_deg = sorted(range(n), key=lambda i: rows[i][0])
by_scr = sorted(range(n), key=lambda i: rows[i][1])
rd = [0]*n; rs = [0]*n
for r, i in enumerate(by_deg): rd[i] = r
for r, i in enumerate(by_scr): rs[i] = r
mean_d = mean_s = (n - 1) / 2
num = sum((rd[i]-mean_d)*(rs[i]-mean_s) for i in range(n))
den = (sum((rd[i]-mean_d)**2 for i in range(n)) * sum((rs[i]-mean_s)**2 for i in range(n))) ** 0.5
print(f"\n  Spearman rank correlation (GO degree vs mean score): {num/den:+.4f}")
print("    positive => score tracks ubiquity, supporting the hypothesis")
