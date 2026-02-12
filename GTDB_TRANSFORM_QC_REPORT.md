# GTDB Transform QC Report

**Date**: February 10, 2026
**Transform Version**: Initial implementation
**GTDB Release**: Latest (downloaded from /releases/latest/)

---

## Issue Identified and Resolved

### Problem
Initial transform showed only **32 archaeal genomes** (expected ~17,000+)

### Root Cause
The `ar53_taxonomy.tsv` file was truncated during download:
- Initial file: 5.0 KB, 63 lines, only *Methanocatella smithii*
- All entries were from a single species

### Resolution
Re-downloaded `ar53_taxonomy.tsv` using curl:
- Corrected file: 2.3 MB, 17,245 lines
- 6,968 unique archaeal species
- Diverse coverage across multiple phyla

---

## Transform Output Summary

### Input Data
| Source | Genomes | Status |
|--------|---------|--------|
| Bacterial (bac120_taxonomy.tsv) | 715,230 | ✅ Complete |
| Archaeal (ar53_taxonomy.tsv) | 17,245 | ✅ **Fixed** |
| **Total Input** | **732,475** | ✅ |

### Output Nodes
| Node Type | Count | Category |
|-----------|-------|----------|
| GTDB Taxa | 181,959 | biolink:OrganismTaxon |
| Genomes | 732,475 | biolink:Genome |
| **Total Nodes** | **914,434** | |

**Verification**: 181,959 + 732,475 = 914,434 ✅

### Output Edges
| Edge Type | Count | Predicate | Relation |
|-----------|-------|-----------|----------|
| Taxonomy Hierarchy | 181,957 | biolink:subclass_of | rdfs:subClassOf |
| Genome → Taxon | 732,475 | biolink:subclass_of | rdfs:subClassOf |
| GTDB → NCBI Mappings | 245,471 | biolink:close_match | skos:closeMatch |
| **Total Edges** | **1,159,903** | | |

**Verification**: 181,957 + 732,475 + 245,471 = 1,159,903 ✅

### NCBI Mapping Coverage
- **Unique GTDB taxa with NCBI mappings**: 143,614 / 181,959
- **Coverage**: 78.9%
- **Deduplication**: Working correctly (no duplicate mappings per taxon)

### File Sizes
- `nodes.tsv`: 91 MB
- `edges.tsv`: 89 MB
- **Total**: 180 MB

---

## Data Quality Checks

### ✅ Genome Count Validation
```
Expected: 732,475 (715,230 bacteria + 17,245 archaea)
Actual:   732,475 genomes in nodes.tsv
Status:   PASS ✓
```

### ✅ Edge Integrity
```
Subclass edges: 914,432
  - Taxa hierarchy: ~181,957 (one parent per taxon except root)
  - Genome→Taxon: 732,475 (one species per genome)
Status: PASS ✓
```

### ✅ Node Categories
```
All genome nodes: biolink:Genome ✓
All taxa nodes: biolink:OrganismTaxon ✓
No category mixing ✓
```

### ✅ NCBI Mappings
```
Total close_match edges: 245,471
Unique GTDB taxa mapped: 143,614
Deduplication working: YES ✓
Coverage: 78.9% (reasonable for GTDB→NCBI mapping)
```

### ✅ Archaeal Diversity
Before fix:
- 32 genomes
- 1 species (Methanocatella smithii only)
- ❌ INCOMPLETE

After fix:
- 17,245 genomes
- 6,968 unique species
- Multiple phyla: Methanobacteriota, Thermoproteota, Halobacteriota, Nanobdellota, Asgardarchaeota, Thermoplasmatota, Aenigmatarchaeota, etc.
- ✅ COMPLETE

### ✅ Taxonomy Hierarchy Examples

**E. coli (Bacteria)**:
```
GenBank:GCF_000005845 (genome)
  └─ GTDB:299 (s__Escherichia_coli)
    └─ GTDB:147 (g__Escherichia)
      └─ GTDB:281 (f__Enterobacteriaceae)
        └─ GTDB:205 (o__Enterobacterales)
          └─ GTDB:295 (c__Gammaproteobacteria)
            └─ GTDB:209 (p__Pseudomonadota)
              └─ GTDB:3 (d__Bacteria)
```

**Methanocaldococcus (Archaea)**:
```
Sample archaeal lineage includes:
  - Domain: d__Archaea
  - Phylum: p__Methanobacteriota
  - Class: c__Methanococci
  - Order: o__Methanococcales
  - Family: f__Methanocaldococcaceae
  - Genus: g__Methanocaldococcus
```

---

## Data Distribution

### Domain Distribution
- **Bacteria**: 715,230 genomes (97.6%)
- **Archaea**: 17,245 genomes (2.4%)
- **Ratio**: ~41:1 (bacterial:archaeal)

This distribution is expected and matches GTDB's composition, as bacterial genomes are much more numerous in databases.

### Taxa Distribution
- **Total unique taxa**: 181,959
- **Bacterial taxa**: ~174,000 (estimated)
- **Archaeal taxa**: ~8,000 (estimated)

---

## Known Limitations

1. **Archaeal taxonomy file download**:
   - The `/releases/latest/` URL may redirect or have issues
   - Manual verification recommended for production use
   - Consider using a specific release version (e.g., `/releases/release220/`)

2. **NCBI mapping coverage**:
   - 78.9% coverage is good but not complete
   - ~38,000 GTDB taxa lack NCBI mappings
   - This is expected for newly-described or uncultured taxa

3. **Metadata file size**:
   - Bacterial metadata: 225 MB (gzipped)
   - Archaeal metadata: 5.4 MB (gzipped)
   - Large files may have slow download/processing times

---

## Recommendations

### For Production Use
1. ✅ Use specific GTDB release version (not `/latest/`)
2. ✅ Verify download checksums if available
3. ✅ Implement automated QC checks (genome counts, file sizes)
4. ✅ Monitor for new GTDB releases (typically 1-2 per year)

### For Future Enhancements
1. Add GTDB release version to node metadata
2. Track genome quality metrics (completeness, contamination)
3. Add representative genome markers
4. Implement incremental updates for new releases

---

## Test Results Summary

| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| Bacterial genomes | 715,230 | 715,230 | ✅ PASS |
| Archaeal genomes | ~17,000+ | 17,245 | ✅ PASS |
| Total genomes | 732,475 | 732,475 | ✅ PASS |
| GTDB taxa created | >100,000 | 181,959 | ✅ PASS |
| Node categories correct | Yes | Yes | ✅ PASS |
| Edge types correct | Yes | Yes | ✅ PASS |
| Hierarchy complete | Yes | Yes | ✅ PASS |
| NCBI mappings present | Yes | Yes | ✅ PASS |
| Deduplication working | Yes | Yes | ✅ PASS |
| File sizes reasonable | Yes | 180 MB | ✅ PASS |

---

## Conclusion

**Status**: ✅ **PASS - Transform working correctly after fix**

The GTDB transform successfully processes 732,475 genomes and creates a complete taxonomic hierarchy with 181,959 unique taxa. The archaeal taxonomy data issue was identified and resolved. All QC checks pass.

**Ready for integration into kg-microbe knowledge graph.**

---

## Command Reference

### Re-download corrected archaeal taxonomy:
```bash
cd data/raw/gtdb
curl -L "https://data.gtdb.ecogenomic.org/releases/latest/ar53_taxonomy.tsv" -o ar53_taxonomy.tsv
```

### Run transform:
```bash
poetry run kg transform -s gtdb
```

### Verify output:
```bash
wc -l data/transformed/gtdb/*.tsv
ls -lh data/transformed/gtdb/
```

### Check node/edge counts:
```bash
awk -F'\t' 'NR>1 {print $2}' data/transformed/gtdb/nodes.tsv | sort | uniq -c
awk -F'\t' 'NR>1 {print $2}' data/transformed/gtdb/edges.tsv | sort | uniq -c
```
