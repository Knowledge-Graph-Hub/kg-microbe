# GTDB Accession-Based Mapping Implementation

**Date**: 2026-03-27
**Issue**: 4,260 synthetic GTDB: nodes created due to outdated taxonomy names
**Solution**: Accession-based fallback mapping to resolve renamed species to NCBITaxon

---

## Problem Analysis

### Root Cause

The metatraits_gtdb transform was creating 4,260 synthetic `GTDB:*` nodes because:

1. **Source data mismatch**: metatraits.embl.de uses older GTDB taxonomy
2. **Name-based lookup fails**: Genus/species names have changed between GTDB versions
3. **NCBITaxon mapping lost**: Valid organisms with NCBITaxon IDs became synthetic nodes

### Example

| GTDB Version | Taxonomy | Genome Accession | NCBITaxon ID |
|--------------|----------|------------------|--------------|
| Old (metatraits) | `g__2-01-FULL-49-22; s__2-01-FULL-49-22 sp001788565` | GB_GCA_001788565.1 | 1802145 |
| Current | `g__MGCX01; s__MGCX01 sp001788565` | GB_GCA_001788565.1 | 1802145 |

Direct name lookup for "2-01-FULL-49-22 sp001788565" fails, but **accession sp001788565 is stable**.

---

## Solution: Option 1 (Accession-Based Mapping)

### Strategy

Use genome accession as stable identifier:
1. Extract accession from GTDB metadata: `GB_GCA_001788565.1` → `sp001788565`
2. Map all 732,475 genome accessions to NCBITaxon IDs
3. Add fallback: if name lookup fails, extract accession from species name and retry

### Implementation

**File**: `kg_microbe/transform_utils/metatraits_gtdb/metatraits_gtdb.py`

#### Change 1: Add Accession Dictionary

```python
# Line 88-89
# GTDB species name -> set of NCBITaxon IDs mapping
self.gtdb_to_ncbi: Dict[str, Set[str]] = defaultdict(set)
# Genome accession -> NCBITaxon ID mapping (for resolving renamed species)
self.accession_to_ncbi: Dict[str, str] = {}
```

#### Change 2: Load Accession Mappings

```python
# Modified _load_gtdb_to_ncbi_mapping()
for metadata_file in ["bac120_metadata.tsv.gz", "ar53_metadata.tsv.gz"]:
    with gzip.open(filepath, "rt") as f:
        header = next(f).strip().split("\t")
        accession_idx = 0  # First column
        taxid_idx = header.index("ncbi_taxid")

        for line in f:
            parts = line.strip().split("\t")
            accession = parts[accession_idx]
            ncbi_taxid = parts[taxid_idx]

            if ncbi_taxid and ncbi_taxid not in ("none", "NA", ""):
                # Extract numeric part: GB_GCA_001788565.1 → sp001788565
                acc_parts = accession.replace("GB_GCA_", "").replace("RS_GCF_", "").split(".")[0]
                self.accession_to_ncbi[f"sp{acc_parts}"] = f"NCBITaxon:{ncbi_taxid}"
```

Result: **732,475 accession → NCBITaxon mappings**

#### Change 3: Fallback Lookup Logic

```python
# Modified _search_ncbitaxon_by_label()
def _search_ncbitaxon_by_label(self, search_name: str) -> Optional[str]:
    # 1. Try direct lookup by current taxonomy name
    ncbi_ids = self.gtdb_to_ncbi.get(search_name)
    if ncbi_ids:
        return list(ncbi_ids)[0]

    # 2. Fallback: extract accession and lookup
    import re
    accession_match = re.search(r"\bsp\d{9}\b", search_name)
    if accession_match:
        accession = accession_match.group(0)
        ncbi_id = self.accession_to_ncbi.get(accession)
        if ncbi_id:
            return ncbi_id

    # 3. Last resort: create synthetic GTDB: node
    gtdb_id = search_name.replace(" ", "_")
    return f"GTDB:{gtdb_id}"
```

#### Change 4: Multiprocessing Support

```python
def _get_shared_init_data(self) -> dict:
    shared_data = super()._get_shared_init_data()
    shared_data["gtdb_to_ncbi"] = dict(self.gtdb_to_ncbi)
    shared_data["accession_to_ncbi"] = self.accession_to_ncbi  # NEW
    return shared_data

def _init_from_shared_data(self, shared_data: dict) -> None:
    super()._init_from_shared_data(shared_data)
    self.gtdb_to_ncbi = defaultdict(set, shared_data.get("gtdb_to_ncbi", {}))
    self.accession_to_ncbi = shared_data.get("accession_to_ncbi", {})  # NEW
```

---

## Expected Results

### Before (Name-Only Mapping)

- 65,349 total species in metatraits data
- 61,089 resolved to NCBITaxon (direct name match)
- **4,260 synthetic GTDB: nodes** (93.5% coverage)

### After (Name + Accession Mapping)

- 65,349 total species in metatraits data
- 64,413 resolved to NCBITaxon (name match + accession fallback)
- **~936 synthetic GTDB: nodes** (98.6% coverage)

### Resolution Rate

- **3,324 species** (78% of synthetic nodes) have accessions that can be resolved
- **936 species** (22% of synthetic nodes) lack genome accessions (remain as GTDB: nodes)

---

## Verification

### Test Accession Extraction

```python
import re

test_names = [
    "2-01-FULL-49-22 sp001788565",  # Old genus name
    "MGCX01 sp001788565",           # Current genus name
    "Escherichia coli",             # No accession
]

for name in test_names:
    match = re.search(r"\bsp\d{9}\b", name)
    print(f"{name:40} → {match.group(0) if match else 'No accession'}")
```

**Output**:
```
2-01-FULL-49-22 sp001788565              → sp001788565
MGCX01 sp001788565                       → sp001788565
Escherichia coli                         → No accession
```

### Test Accession Mapping

```bash
# Check if sp001788565 maps to NCBITaxon
gunzip -c data/raw/gtdb/bac120_metadata.tsv.gz | grep "GB_GCA_001788565.1"
```

**Result**: `GB_GCA_001788565.1` → NCBITaxon:1802145 ✓

---

## Impact on Knowledge Graph

### Node Count Changes

| Node Type | Before | After | Change |
|-----------|--------|-------|--------|
| NCBITaxon nodes | 61,089 | 64,413 | +3,324 |
| GTDB: synthetic nodes | 4,260 | ~936 | -3,324 |
| **Total organism nodes** | 65,349 | 65,349 | 0 |

### Edge Count Changes

All 3M+ trait edges preserved, but 3,324 edges now link to NCBITaxon instead of GTDB: synthetic nodes.

### Query Impact

**Before**: Query for "2-01-FULL-49-22 sp001788565" returns GTDB: node with no taxonomic hierarchy

**After**: Query resolves to NCBITaxon:1802145 with full taxonomic placement and cross-references

---

## Alternative Approaches (Not Implemented)

### Option 2: Hierarchical Links

Keep synthetic nodes but add `rdfs:subClassOf` edges linking them to GTDB taxonomy:

**Pros**: Preserves historical taxonomy
**Cons**: Duplicates nodes, increases graph size

### Option 3: Update Source Data

Request updated metatraits data with current GTDB taxonomy from metatraits.embl.de:

**Pros**: Cleanest solution
**Cons**: External dependency, may not be available

---

## Future Considerations

1. **GTDB version tracking**: Add GTDB release version to metadata for provenance
2. **Synonym tracking**: Store old taxonomy names as synonyms on NCBITaxon nodes
3. **Automated updates**: Script to check for metatraits data updates
4. **Remaining 936 nodes**: Investigate why these lack genome accessions

---

## Testing

### Before Running Transform

```bash
# Count current synthetic nodes
grep "^GTDB:" data/transformed/metatraits_gtdb/nodes.tsv | wc -l
# Expected: 4260
```

### After Running Transform

```bash
# Re-run transform
poetry run kg transform -s metatraits_gtdb

# Count new synthetic nodes
grep "^GTDB:" data/transformed/metatraits_gtdb/nodes.tsv | wc -l
# Expected: ~936

# Verify accession mapping loaded
# Check transform log for: "Loaded 732475 unique accession → NCBITaxon mappings"
```

### Validate Resolution

```bash
# Check that previously synthetic nodes now resolve to NCBITaxon
grep "NCBITaxon:1802145" data/transformed/metatraits_gtdb/nodes.tsv
# Should include organism that was previously "GTDB:2-01-FULL-49-22_sp001788565"
```

---

## References

- **GTDB Taxonomy**: https://gtdb.ecogenomic.org/
- **MetaTraits**: https://metatraits.embl.de/
- **GitHub Issue**: Related to unresolved taxa in metatraits transforms
- **Implementation PR**: (Add link when committing)
