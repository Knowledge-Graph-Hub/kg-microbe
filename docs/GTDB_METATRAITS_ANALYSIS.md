# GTDB MetaTraits Overlap Analysis

**Date:** 2026-03-22
**Status:** ✅ INTEGRATE recommended
**Decision:** Add GTDB metatraits transform to KG-Microbe pipeline

---

## Executive Summary

GTDB metatraits data provides **significant new coverage** compared to existing NCBITaxon metatraits:

- **56.4%** of GTDB taxa map to NCBITaxon IDs that **don't have trait data yet** (48,235 taxa, 83.7M observations)
- **28.6%** of GTDB taxa have **no NCBITaxon mapping** (24,481 taxa, 418M observations)
- Only **15.0%** redundant overlap with existing NCBITaxon metatraits (12,831 taxa, 97.4M observations)

**Recommendation:** INTEGRATE GTDB metatraits into the transform pipeline.

---

## Analysis Details

### Current State

**Existing NCBITaxon metatraits coverage:**
- 8,320 unique NCBITaxon taxa with trait data
- 1,048,641 trait edges in transformed data
- ~291K trait observations

**Available GTDB metatraits data:**
- 85,547 unique GTDB taxa with trait data
- 599,090,288 total trait observations across all taxa
- 3 files: gtdb_species_summary.jsonl.gz (46MB), gtdb_genus_summary.jsonl.gz (16MB), gtdb_family_summary.jsonl.gz (4.4MB)

### Overlap Breakdown

| Category | Taxa Count | Taxa % | Observations | Obs % | Description |
|----------|-----------|--------|--------------|-------|-------------|
| **Redundant** | 12,831 | 15.0% | 97,416,071 | 16.3% | GTDB taxa map to NCBITaxon IDs that already have traits |
| **New Coverage** | 48,235 | 56.4% | 83,659,503 | 14.0% | GTDB taxa map to NCBITaxon IDs without traits |
| **GTDB-only** | 24,481 | 28.6% | 418,014,714 | 69.8% | GTDB taxa have no NCBITaxon mapping |
| **Total** | 85,547 | 100% | 599,090,288 | 100% | All GTDB metatraits data |

### Key Insights

1. **High New Coverage (56.4%)**: More than half of GTDB taxa would add trait data to NCBITaxon organisms that currently lack it.

2. **Substantial GTDB-only Coverage (28.6%)**: Nearly one-third of GTDB taxa don't map to any NCBITaxon ID. These are likely:
   - MAGs (Metagenome-Assembled Genomes)
   - SAGs (Single-cell Amplified Genomes)
   - Uncultured organisms
   - Recently discovered species not yet in NCBI Taxonomy

3. **Observation Density**: GTDB-only taxa have the highest observation density (17,077 obs/taxon) compared to New Coverage (1,734 obs/taxon) and Redundant (7,592 obs/taxon). This suggests GTDB-only taxa are well-characterized despite lacking NCBI mappings.

4. **Low Redundancy (15.0%)**: Only 15% overlap means adding GTDB metatraits would mostly complement (not duplicate) existing NCBITaxon metatraits.

---

## Data Sources

### Files Downloaded

All files downloaded from https://metatraits.embl.de/:

1. **gtdb_species_summary.jsonl.gz** (46 MB)
   - Species-level GTDB trait annotations
   - Format: `{"tax_name": "Species_name spXXXXX", "summaries": [...]}`

2. **gtdb_genus_summary.jsonl.gz** (16 MB)
   - Genus-level GTDB trait annotations

3. **gtdb_family_summary.jsonl.gz** (4.4 MB)
   - Family-level GTDB trait annotations

4. **GTDB2NCBI.tsv.gz** (2.8 MB)
   - GTDB R220 → NCBITaxon mapping (species-level only)
   - Note: Not used in final analysis due to granularity mismatch

5. **NCBI2GTDB.tsv.gz** (2.8 MB)
   - NCBITaxon → GTDB R220 mapping
   - Note: Not used in final analysis

### Mapping Approach

**Final approach used GTDB metadata files** (already in KG-Microbe):
- `data/raw/gtdb/bac120_metadata.tsv.gz` (bacterial metadata)
- `data/raw/gtdb/ar53_metadata.tsv.gz` (archaeal metadata)

These files contain:
- `accession`: Genome assembly ID (e.g., "GB_GCA_002774085.1")
- `gtdb_taxonomy`: Full GTDB lineage ending in species (e.g., "s__Species_name spXXXXX")
- `ncbi_taxid`: Corresponding NCBITaxon ID (715,231 of 715,230 genomes have mappings)

**Mapping logic:**
1. Extract GTDB species name from `gtdb_taxonomy` (e.g., "0-14-0-10-38-17 sp002774085")
2. Map to `ncbi_taxid` (e.g., "1974884")
3. Compare against NCBITaxon IDs that already have trait data in transformed edges

---

## Sample Taxa by Category

### Redundant (NCBITaxon already has traits)
Examples:
- `1-14-0-10-45-34 sp002778785`
- `1-14-0-20-39-49 sp002787635`
- `1109 sp001028815`

These GTDB taxa map to NCBITaxon organisms that already have trait data from the existing NCBITaxon metatraits.

### New Coverage (NCBITaxon exists, no traits)
Examples:
- `0-14-0-10-38-17 sp002774085` → NCBITaxon:1974884
- `0-14-0-20-30-16 sp002779075`
- `0-14-0-20-34-12 sp002779065`

These GTDB taxa map to valid NCBITaxon IDs, but those organisms don't have trait data yet. **This is the primary value proposition for GTDB metatraits.**

### GTDB-only (no NCBITaxon mapping)
Examples (genus/family level):
- `0-14-0-10-38-17` (genus)
- `0-14-0-20-30-16` (genus)
- `0-14-0-20-34-12` (genus)

These GTDB taxa have no NCBITaxon mapping at all. They represent:
- Uncultured organisms
- Metagenome-derived genomes
- Genomes not yet integrated into NCBI Taxonomy

---

## Recommendation: INTEGRATE

### Rationale

✅ **New coverage threshold met:** 56.4% >> 20% threshold
✅ **GTDB-only threshold met:** 28.6% >> 10% threshold
✅ **Low redundancy:** Only 15% overlap with existing data
✅ **High observation count:** 83.7M new observations for mapped taxa + 418M for GTDB-only taxa
✅ **Complementary coverage:** GTDB focuses on genomes while NCBI focuses on cultured organisms

### Benefits

1. **Expand trait coverage** for 48,235 NCBITaxon organisms that currently lack trait data
2. **Add genome-level resolution** by linking traits to specific genome assemblies
3. **Include uncultured organisms** (28.6% GTDB-only taxa) that are important for environmental/microbiome studies
4. **Increase observation density** from 291K to 599M trait observations

### Implementation Complexity

**Medium complexity:**
- Can reuse existing `MetaTraitsTransform` class as base
- Requires mapping GTDB species names to NCBITaxon IDs via GTDB metadata
- Need to decide how to handle GTDB-only taxa (create custom GTDB: prefix nodes?)

---

## Next Steps

### Phase 1: Create GTDB MetaTraits Transform

**File:** `kg_microbe/transform_utils/metatraits_gtdb/metatraits_gtdb.py`

**Approach:**
1. Inherit from existing `MetaTraitsTransform` class
2. Override `_search_ncbitaxon_by_label()` to use GTDB → NCBITaxon mapping from metadata files
3. For GTDB-only taxa (no NCBITaxon mapping):
   - **Option A:** Skip these taxa (lose 28.6% but cleaner)
   - **Option B:** Create `GTDB:` namespace nodes (keeps all data but adds new namespace)
   - **Recommended:** Option B - preserve all data
4. Input files: `gtdb_*_summary.jsonl.gz`
5. Output: `data/transformed/metatraits_gtdb/nodes.tsv` and `edges.tsv`

### Phase 2: Register Transform

**File:** `kg_microbe/transform.py`

1. Add constant: `METATRAITS_GTDB = "metatraits_gtdb"`
2. Add to `DATA_SOURCES` dict:
   ```python
   METATRAITS_GTDB: MetaTraitsGTDBTransform,
   ```

### Phase 3: Add to Merge Configuration

**File:** `merge.yaml`

Add `metatraits_gtdb` to the merge priority list (after `metatraits`).

### Phase 4: Testing

```bash
# Transform GTDB metatraits
poetry run kg transform -s metatraits_gtdb

# Verify outputs
wc -l data/transformed/metatraits_gtdb/{nodes,edges}.tsv

# Check for duplicates with NCBITaxon metatraits
comm -12 <(cut -f1,2,3 data/transformed/metatraits/edges.tsv | sort) \
         <(cut -f1,2,3 data/transformed/metatraits_gtdb/edges.tsv | sort) | wc -l

# Run full merge
poetry run kg merge -y merge.yaml

# Verify final edge counts
wc -l data/merged/merged-kg_edges.tsv
```

---

## Open Questions

1. **GTDB-only namespace:** Should we create GTDB: prefix nodes for taxa without NCBITaxon mappings?
   - **Pro:** Preserves all data (28.6% of taxa, 69.8% of observations)
   - **Con:** Introduces new namespace, complicates downstream queries
   - **Decision:** TBD based on use case requirements

2. **Observation density:** Why do GTDB-only taxa have 10x more observations per taxon?
   - Hypothesis: These are well-studied MAGs/SAGs with extensive trait characterization
   - May indicate high-quality genome-derived trait predictions

3. **Redundancy handling:** Should we skip redundant 15% or merge them (averaging trait values)?
   - **Recommendation:** Skip to avoid duplicate edges (KGX merge will deduplicate anyway)

4. **Priority:** Should GTDB metatraits be prioritized over NCBITaxon metatraits in merge.yaml?
   - **Recommendation:** NCBITaxon first (more authoritative for cultured organisms)

---

## References

- MetaTraits database: https://metatraits.embl.de/
- GTDB R220: https://gtdb.ecogenomic.org/
- Overlap analysis script: `scripts/analyze_gtdb_metatraits_overlap.py`
- Full analysis output: `gtdb_overlap_report.txt`

---

## Change Log

- **2026-03-22:** Initial analysis completed. Recommendation: INTEGRATE.
- **2026-03-22:** Updated mapping approach to use GTDB metadata files instead of GTDB2NCBI.tsv.gz (better granularity).
