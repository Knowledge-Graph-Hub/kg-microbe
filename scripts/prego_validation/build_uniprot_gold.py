"""
Build a taxon->GO gold standard from UniProt proteome annotations.

Joins `protein -derives_from-> NCBITaxon` with `protein -participates_in|located_in-> GO`.
Rows are grouped by protein, so this needs no protein->taxon dict.
"""
import pickle

FUNC = "data/merged/20250222_function/merged/kg-microbe-function/merged-kg_edges.tsv"
PREGO = "data/transformed/prego/edges.tsv"

# ---- pass 1: PREGO's entity space (bounds everything downstream) ----
ptaxa, pgos = set(), set()
with open(PREGO) as fh:
    h = next(fh).rstrip("\n").split("\t")
    si, oi = h.index("subject"), h.index("object")
    for line in fh:
        f = line.split("\t", oi + 1)
        if len(f) <= oi: continue
        s, o = f[si], f[oi]
        if s.startswith("NCBITaxon:") and o.startswith("GO:"):
            ptaxa.add(int(s[10:])); pgos.add(int(o[3:]))
print(f"  prego taxa {len(ptaxa):,}  prego GO {len(pgos):,}", flush=True)

# ---- pass 2: UniProt gold, restricted to PREGO's space ----
GO_PREDS = ("biolink:participates_in", "biolink:located_in")
gold = {}
cur = None; cur_go = []; cur_tax = None
n_pairs = 0

def flush():
    global n_pairs
    if cur_tax is not None and cur_tax in ptaxa and cur_go:
        s = gold.setdefault(cur_tax, set())
        for g in cur_go:
            if g in pgos and g not in s:
                s.add(g); n_pairs += 1

with open(FUNC) as fh:
    next(fh)
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) < 3: continue
        subj, pred, obj = f[0], f[1], f[2]
        if not subj.startswith("UniprotKB:"): continue
        if subj != cur:
            flush(); cur = subj; cur_go = []; cur_tax = None
        if pred == "biolink:derives_from" and obj.startswith("NCBITaxon:"):
            try: cur_tax = int(obj[10:])
            except ValueError: pass
        elif pred in GO_PREDS and obj.startswith("GO:"):
            try: cur_go.append(int(obj[3:]))
            except ValueError: pass
flush()

gtaxa = set(gold)
ggos = set()
for s in gold.values(): ggos |= s
print(f"  UNIPROT GOLD: {n_pairs:,} pairs | taxa {len(gtaxa):,} | GO {len(ggos):,}", flush=True)
pickle.dump((gold, gtaxa, ggos), open("/tmp/uniprot_gold.pkl", "wb"), protocol=4)
