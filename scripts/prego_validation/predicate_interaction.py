"""Does the score behave differently for location_of vs capable_of, on matched taxa?

The headline verdict — score discriminates on `location_of`, not on `capable_of` —
was measured with a different gold standard per predicate, so predicate was
confounded with benchmark ascertainment, coverage (0.1%-41.5%) and taxon degree.
External review downgraded it to plausible-but-unproven and named this analysis
as the cheapest way to settle it.

Design, chosen to remove those confounds rather than adjust for them:

* **Matched taxa.** Only taxa carrying BOTH a BacDive isolation record and a
  BacDive assay result are used, so both predicates are judged on the same
  organisms drawn from the same resource.
* **Within-term.** The high/low score comparison happens inside a term, so term
  identity cannot drive it. Boundaries are tie-safe — an index median lets sort
  order decide which tied rows fall in which half, which is exactly the defect
  that inflated the published BTO figure.
* **Degree-stratified.** Comparisons are additionally confined to a taxon-degree
  decile, closing the path where the high-score half simply holds better-covered
  taxa (measured: BTO 23.10 vs 18.73, ENVO 91.64 vs 70.67).
* **Two-way clustered bootstrap.** Taxa and terms are resampled together, since
  edges reuse both. iid intervals are optimistic here.

Reports the high/low ratio per predicate with clustered CIs, and the interaction
(their difference). A confidently positive interaction supports the verdict; one
whose interval spans zero does not.
"""

import pickle
import random
from collections import defaultdict

BACDIVE = "data/transformed/bacdive/edges.tsv"
PREGO = "data/transformed/prego/edges.tsv"
UBERON = "data/transformed/ontologies/uberon_nodes.tsv"
POS, NEG = "METPO:2000302", "METPO:2000303"
BOOTSTRAP = 400
SEED = 20260806


def build_location_gold():
    """Return (gold pairs, term set, taxon set) for ENVO+BTO isolation records."""
    u2b = defaultdict(set)
    with open(UBERON) as fh:
        h = next(fh).rstrip("\n").split("\t")
        xi = h.index("xref")
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) > xi and "BTO:" in f[xi]:
                for x in f[xi].split("|"):
                    if x.startswith("BTO:"):
                        u2b[f[0]].add(x)
    strain_tax, hits = {}, []
    with open(BACDIVE) as fh:
        next(fh)
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 3:
                continue
            s, p, o = f[0], f[1], f[2]
            if s.startswith("kgmicrobe.strain:") and p == "biolink:subclass_of" and o.startswith("NCBITaxon:"):
                strain_tax[s] = o
            elif p == "biolink:location_of" and o.startswith("kgmicrobe.strain:"):
                hits.append((s, o))
    gold = set()
    for term, strain in hits:
        taxon = strain_tax.get(strain)
        if not taxon:
            continue
        if term.startswith("ENVO:"):
            gold.add((term, taxon))
        elif term.split(":")[0] in ("UBERON", "CL"):
            for bto in u2b.get(term, ()):
                gold.add((bto, taxon))
    return gold, {t for t, _ in gold}, {x for _, x in gold}


def build_function_labels():
    """Return {(taxon, GO): bool} from unanimous BacDive assay results."""
    tri = pickle.load(open("/tmp/assay_gold.pkl", "rb"))
    out = {}
    for key, (pos, neg) in tri.items():
        if pos and not neg:
            out[key] = True
        elif neg and not pos:
            out[key] = False
    return out


def collect(loc_gold, loc_terms, loc_taxa, fn_labels, taxa):
    """Return per-predicate {term: [(score, hit, taxon)]} restricted to ``taxa``."""
    obs = {"location_of": defaultdict(list), "capable_of": defaultdict(list)}
    with open(PREGO) as fh:
        h = next(fh).rstrip("\n").split("\t")
        si, oi, sci = h.index("subject"), h.index("object"), h.index("prego_score")
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) <= sci:
                continue
            s, o = f[si], f[oi]
            try:
                score = float(f[sci])
            except ValueError:
                continue
            if (s.startswith("ENVO:") or s.startswith("BTO:")) and o.startswith("NCBITaxon:"):
                if o in taxa and s in loc_terms and o in loc_taxa:
                    obs["location_of"][s].append((score, (s, o) in loc_gold, o))
            elif s.startswith("NCBITaxon:") and o.startswith("GO:") and s in taxa:
                lab = fn_labels.get((s, o))
                if lab is not None:
                    obs["capable_of"][o].append((score, lab, s))
    return obs


def ratio(per_term, degree, keep_taxa=None, keep_terms=None):
    """Return the pooled high/low hit-rate ratio, tie-safe and degree-stratified."""
    lo_h = lo_n = hi_h = hi_n = 0
    for term, rows in per_term.items():
        if keep_terms is not None and term not in keep_terms:
            continue
        rows = [r for r in rows if keep_taxa is None or r[2] in keep_taxa]
        by_dec = defaultdict(list)
        for score, hit, taxon in rows:
            by_dec[degree.get(taxon, 0)].append((score, hit))
        for stratum in by_dec.values():
            if len(stratum) < 10:
                continue
            stratum.sort(key=lambda r: r[0])
            mid = len(stratum) // 2
            while mid < len(stratum) and stratum[mid][0] == stratum[mid - 1][0]:
                mid += 1
            if mid == 0 or mid >= len(stratum):
                continue
            lo, hi = stratum[:mid], stratum[mid:]
            lo_h += sum(1 for _, x in lo if x)
            lo_n += len(lo)
            hi_h += sum(1 for _, x in hi if x)
            hi_n += len(hi)
    if not lo_n or not hi_n or not lo_h:
        return None, lo_n + hi_n
    return (hi_h / hi_n) / (lo_h / lo_n), lo_n + hi_n


def main():
    """Run the matched-taxa predicate-by-score interaction analysis."""
    loc_gold, loc_terms, loc_taxa = build_location_gold()
    fn_labels = build_function_labels()
    fn_taxa = {t for t, _ in fn_labels}
    matched = loc_taxa & fn_taxa
    print(f"  taxa with isolation records : {len(loc_taxa):,}")
    print(f"  taxa with assay results     : {len(fn_taxa):,}")
    print(f"  MATCHED (used below)        : {len(matched):,}\n")

    obs = collect(loc_gold, loc_terms, loc_taxa, fn_labels, matched)
    # Taxon degree = number of comparable observations, decile-binned.
    counts = defaultdict(int)
    for per_term in obs.values():
        for rows in per_term.values():
            for _s, _h, taxon in rows:
                counts[taxon] += 1
    ordered = sorted(counts, key=lambda t: counts[t])
    degree = {t: (10 * i) // max(1, len(ordered)) for i, t in enumerate(ordered)}

    point = {}
    for pred, per_term in obs.items():
        r, n = ratio(per_term, degree)
        point[pred] = r
        terms = sum(1 for rows in per_term.values() if rows)
        print(f"  {pred:<12} terms {terms:>4} | in-stratum n {n:>7,} | high/low ratio "
              f"{'n/a' if r is None else f'{r:.3f}'}")

    if point["location_of"] is None or point["capable_of"] is None:
        print("\n  insufficient matched data for an interaction estimate")
        return

    rng = random.Random(SEED)
    all_taxa, diffs = sorted(matched), []
    for _ in range(BOOTSTRAP):
        tx = set(rng.choices(all_taxa, k=len(all_taxa)))
        vals = {}
        for pred, per_term in obs.items():
            terms = sorted(per_term)
            tm = set(rng.choices(terms, k=len(terms))) if terms else set()
            vals[pred], _ = ratio(per_term, degree, keep_taxa=tx, keep_terms=tm)
        if vals["location_of"] and vals["capable_of"]:
            diffs.append(vals["location_of"] - vals["capable_of"])
    diffs.sort()
    obs_diff = point["location_of"] - point["capable_of"]
    print(f"\n  INTERACTION (location_of ratio - capable_of ratio): {obs_diff:+.3f}")
    if len(diffs) >= 20:
        lo = diffs[int(0.025 * len(diffs))]
        hi = diffs[int(0.975 * len(diffs))]
        print(f"  two-way clustered 95% CI over {len(diffs)} resamples: [{lo:+.3f}, {hi:+.3f}]")
        print(f"  fraction of resamples with location_of > capable_of: "
              f"{sum(1 for d in diffs if d > 0) / len(diffs):.3f}")
        print("\n  -> " + ("supports the predicate split" if lo > 0 else
                           "CI spans zero; the split is NOT established on matched taxa"))


if __name__ == "__main__":
    main()
