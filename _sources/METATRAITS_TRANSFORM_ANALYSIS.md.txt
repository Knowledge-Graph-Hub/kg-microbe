# Metatraits Transform: Step-by-Step Analysis

## Why `ncbitaxon.db.gz` (2GB) Was Downloaded

The metatraits transform resolves taxon names (e.g. `"Euryarchaeota archaeon"`) to NCBITaxon IDs. It uses the [OAK](https://github.com/INCATools/ontology-access-kit) library for ontology lookups.

**Lazy adapter creation:** The OAK adapter is now created only on the first cache miss. If `ncbitaxon_nodes.tsv` provides full coverage for your input taxa, the adapter is never created and no download occurs.

**When a download does occur (first cache miss):**
1. **`_get_ncbitaxon_adapter()`** tries the local source first: `sqlite:data/raw/ncbitaxon.owl`
2. The local file is missing or invalid, so the adapter fails
3. On exception, it falls back to **`sqlite:obo:ncbitaxon`**
4. OAK’s `sqlite:obo:ncbitaxon` downloads a pre-built NCBITaxon SQLite database (~2GB compressed) from a central repository and caches it locally
5. That download is what you saw as `ncbitaxon.db.gz`

**To avoid the download:** Provide NCBITaxon labels via one of:
- `data/transformed/ontologies/ncbitaxon_nodes.tsv` (from `poetry run kg transform -s ontologies`)
- `data/raw/ncbitaxon_nodes.tsv` (manually placed; same format: id, category, name, ...)

The metatraits transform checks both paths and loads the first existing file. With ~70k+ labels preloaded, taxon resolution is fast (dict lookup) and OAK is only used for taxa not in the file.

---

## Why It Appears Stuck at "Processing files: 0%| 0/3"

The progress bar shows **file-level** progress (0/3 = first of three files). The bottleneck is **inside** the first file.

### Step-by-step flow

| Step | Location | What happens |
|------|----------|--------------|
| 1 | `run()` line 241 | `tqdm(input_files, desc="Processing files")` – progress bar over 3 files |
| 2 | Line 243–244 | `for input_path in iterable` → opens first file (e.g. `ncbi_species_summary.jsonl.gz`) |
| 3 | Line 245 | `for line in f` – iterates over **each line** (54,654+ lines in species file) |
| 4 | Line 257 | `tax_id = self._search_ncbitaxon_by_label(tax_name)` – **OAK lookup per line** |
| 5 | `_search_ncbitaxon_by_label` | Cache miss → `_get_ncbitaxon_impl()` creates adapter → `search_by_label(...)` |

### Root cause (when cache is empty)

- `ncbitaxon_name_to_id` is filled from `NCBITAXON_NODES_FILE` (ontologies output) or `data/raw/ncbitaxon_nodes.tsv`
- If that file is missing, the cache is empty
- Each `_search_ncbitaxon_by_label` call that misses the cache triggers an OAK `basic_search` on the 2GB SQLite DB

**Update:** OAK lookup results are now cached in `ncbitaxon_name_to_id` (see `_search_ncbitaxon_by_label`). The first occurrence of each taxon triggers an OAK lookup; subsequent occurrences reuse the cached ID. This reduces repeated lookups when the same taxon appears many times across lines.

The bar still advances only when the entire first file is finished, so with many unique taxa and no preloaded NCBITaxon labels, the first file can remain slow until all unique taxa have been resolved and cached.
