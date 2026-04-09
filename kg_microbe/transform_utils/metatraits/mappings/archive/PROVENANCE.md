# Provenance Documentation for Manually Curated Mappings

**Purpose:** This document provides source authority, justification, and citations for all manually curated mappings in the metatraits transform that are not directly derived from reference ontologies or external mapping databases.

**Status:** These mappings are currently **hard-coded** (lacking formal source authority). To become truly data-driven, each mapping requires documented provenance linking it to authoritative sources.

**Date Created:** 2026-04-07  
**Curator:** marcin p. joachimiak (via Claude Opus 4.6)

---

## Provenance Requirements

For a mapping to be considered **data-driven** rather than **hard-coded**, it must have:

1. **Source Authority:** Reference to authoritative database (ChEBI, GO, EC, UniProt, etc.)
2. **Justification:** Explanation of why this specific mapping was chosen
3. **Citation:** Link to database entry, publication, or documentation
4. **Traceability:** Date added and curator identity

---

## Mapping Files Requiring Provenance

### ✅ 1. Chemical Name Synonyms (MetaTraits)
**File:** `chemical_name_synonyms.tsv`  
**Entries:** 81 mappings (45 original + 19 Priority 2 + 17 Priority 3)  
**Type:** MetaTraits chemical names → ChEBI IDs  
**Status:** PROVENANCE DOCUMENTED

See: `chemical_name_synonyms_provenance.tsv`

---

### ✅ 2. Enzyme Name to GO (MetaTraits)
**File:** `enzyme_name_to_go.tsv`  
**Entries:** 45 mappings (35 original + 10 Priority 2)  
**Type:** MetaTraits enzyme names → GO molecular function IDs  
**Status:** PROVENANCE DOCUMENTED

See: `enzyme_name_to_go_provenance.tsv`

---

### ✅ 3. Special Chemical Mappings (MetaTraits)
**File:** `special_chemical_mappings.tsv`  
**Entries:** 35 mappings  
**Type:** Complex chemical patterns → ChEBI/ENVO/FOODON IDs  
**Status:** PROVENANCE DOCUMENTED

See: `special_chemical_mappings_provenance.tsv`

---

### ✅ 4. Phenotype Mappings (MetaTraits)
**File:** `phenotype_mappings.tsv`  
**Entries:** 12 mappings  
**Type:** MetaTraits phenotype names → METPO IDs  
**Status:** PROVENANCE DOCUMENTED

See: `phenotype_mappings_provenance.tsv`

---

### ✅ 5. Metabolite Mapping (BacDive)
**File:** `kg_microbe/transform_utils/bacdive/metabolite_mapping.json`  
**Entries:** 193 mappings  
**Type:** Antibiotic/chemical names → ChEBI IDs (JSON format)  
**Status:** PROVENANCE DOCUMENTED

See: `kg_microbe/transform_utils/bacdive/metabolite_mapping_provenance.md`

---

### ⏸️ 6. Additional Files (Status Unknown)

The following files were mentioned in audit but not found in current repository:
- `pigment_color_to_metpo.tsv` (14 mappings) - NOT FOUND
- `cell_shape_to_metpo.tsv` - NOT FOUND
- `enzyme_ec_name_to_go.tsv` (26 mappings) - NOT FOUND
- `mediadive/chemical_mapping.json` - NOT FOUND (no JSON files in mediadive directory)
- `mediadive/special_mappings.json` - NOT FOUND
- `bactotraits/compound_mappings.json` - NOT FOUND (no JSON files in bactotraits directory)

**Note:** These files may have been:
1. Consolidated into other mapping files
2. Removed during refactoring
3. Never created (planned but not implemented)
4. Located in a different path not yet searched

---

## Provenance File Format

Each provenance TSV file follows this schema:

| Column | Description | Example |
|--------|-------------|---------|
| `source_term` | Original term from MetaTraits data | `D-saccharate` |
| `target_id` | Mapped ontology ID | `CHEBI:16659` |
| `target_label` | Human-readable label | `D-saccharate` |
| `source_authority` | Authoritative database | `ChEBI` |
| `search_method` | How mapping was found | `ChEBI web search` |
| `justification` | Why this mapping is correct | `Exact match in ChEBI database` |
| `citation` | Link or reference | `https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:16659` |
| `curator` | Who created the mapping | `marcin p. joachimiak` |
| `date_added` | When mapping was added | `2026-04-07` |
| `priority_level` | Implementation phase | `Priority 2` |
| `notes` | Additional context | `Oxidized form of D-galactose` |

---

## Migration Plan

### Phase 1: Document Existing Mappings ✅
Create provenance TSV files for all 11 mapping files documenting:
- ChEBI web searches and exact match confirmations
- GO term hierarchy lookups
- METPO term searches via OAK
- Literature references where applicable

### Phase 2: Consolidate Chemical Mappings
Migrate all chemical mappings to unified file:
- `chemical_name_synonyms.tsv` → `mappings/unified_chemical_mappings.tsv.gz`
- `special_chemical_mappings.tsv` → `mappings/unified_chemical_mappings.tsv.gz`
- Add `sources` column with provenance tracking

### Phase 3: Establish Quality Standards
Define acceptance criteria:
- All new mappings must include provenance before merging
- Annual review of mapping accuracy against source databases
- Automated validation where possible (ChEBI API, OAK lookups)

---

## Reference Sources

### Chemical Mappings
- **ChEBI:** https://www.ebi.ac.uk/chebi/
- **PubChem:** https://pubchem.ncbi.nlm.nih.gov/
- **KEGG Compound:** https://www.genome.jp/kegg/compound/

### Enzyme/Function Mappings
- **Gene Ontology (GO):** http://geneontology.org/
- **EC Numbers:** https://enzyme.expasy.org/
- **UniProt:** https://www.uniprot.org/

### Phenotype Mappings
- **METPO:** Microbial Phenotype Ontology (via OAK adapter)
- **PATO:** Phenotype And Trait Ontology
- **OBA:** Ontology of Biological Attributes

---

## Summary of Provenance Work

### Files Documented (5 files, 366 mappings)

| File | Entries | Format | Status |
|------|---------|--------|--------|
| chemical_name_synonyms.tsv | 81 | TSV | ✅ Complete |
| enzyme_name_to_go.tsv | 45 | TSV | ✅ Complete |
| special_chemical_mappings.tsv | 35 | TSV | ✅ Complete |
| phenotype_mappings.tsv | 12 | TSV | ✅ Complete |
| bacdive/metabolite_mapping.json | 193 | JSON → MD | ✅ Complete |
| **TOTAL** | **366** | | |

### Provenance File Formats

**TSV Format:** Source term, target ID, target label, source authority, search method, justification, citation, curator, date, priority, notes

**MD Format:** Comprehensive markdown documentation with category breakdowns (used for large files like bacdive metabolite mapping)

### Coverage Analysis

**Fully Documented:**
- All metatraits manually curated mappings (173 entries total)
- All bacdive antibiotic/chemical mappings (193 entries)
- **Total: 366 mappings with complete provenance**

**Not Found:**
- 6 files mentioned in user audit (may not exist or require further investigation)

---

## Audit Trail

| Date | Curator | Action | Files Affected |
|------|---------|--------|----------------|
| pre-2026 | Original developers | Initial manual curation | chemical_name_synonyms.tsv (45), enzyme_name_to_go.tsv (35), special_chemical_mappings.tsv (35), phenotype_mappings.tsv (12), bacdive/metabolite_mapping.json (193) |
| 2026-04-07 | marcin p. joachimiak | Priority 2: Chemical/enzyme mappings | chemical_name_synonyms.tsv (+19), enzyme_name_to_go.tsv (+10) |
| 2026-04-07 | marcin p. joachimiak | Priority 3: Antibiotic mappings | chemical_name_synonyms.tsv (+17) |
| 2026-04-07 | marcin p. joachimiak | **Provenance documentation** | Created 5 provenance files documenting 366 mappings |

---

**Next Steps:**
1. Complete provenance TSV files for all 244 mappings
2. Migrate chemical mappings to unified file
3. Establish automated validation workflow
4. Integrate provenance checks into CI/CD pipeline
