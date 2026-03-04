# Metatraits Transform: Step-by-Step Analysis

## Why `ncbitaxon.db.gz` (2GB) Was Downloaded

The metatraits transform resolves taxon names (e.g. `"Euryarchaeota archaeon"`) to NCBITaxon IDs. It uses the [OAK](https://github.com/INCATools/ontology-access-kit) library for ontology lookups.

**Flow:**
1. **`_get_ncbitaxon_adapter()`** (line 48–57) tries the local source first: `sqlite:data/raw/ncbitaxon.owl`
2. The local `ncbitaxon.db` was empty or invalid (no `statements` table), so the adapter failed
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
| 5 | Line 124–129 | `_search_ncbitaxon_by_label`: cache miss → `search_by_label(self.ncbi_impl, ...)` |

### Root cause: OAK results not cached

- `ncbitaxon_name_to_id` is filled only from `NCBITAXON_NODES_FILE` (ontologies output)
- If that file is missing, the cache is empty
- Each `_search_ncbitaxon_by_label` call that misses the cache triggers an OAK `basic_search` on the 2GB SQLite DB
- **OAK lookup results are never written back into `ncbitaxon_name_to_id`**
- The same taxon (e.g. `"Euryarchaeota archaeon"`) can appear many times → repeated OAK lookups for the same name

With ~54k lines in the species file and many unique taxa, this leads to tens of thousands of slow OAK lookups. The bar stays at 0/3 because it only advances when the **entire first file** is finished.

---

## Fix: Cache OAK lookup results

When `_search_ncbitaxon_by_label` gets a result from OAK, it should store it in `ncbitaxon_name_to_id` so later lines with the same taxon name reuse the cached ID instead of querying OAK again.
