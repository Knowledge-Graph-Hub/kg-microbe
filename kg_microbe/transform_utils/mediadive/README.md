# MediaDive Transform

The MediaDive transform converts cultivation media data from the [MediaDive database](https://mediadive.dsmz.de/) into a knowledge graph format.

## Quick Start

### Recommended Workflow (Automatic Bulk Download)

```bash
# Download all data sources including MediaDive bulk data
# MediaDive bulk download happens automatically (~30-60 minutes first time)
poetry run kg download

# Run transform (uses bulk downloaded files, ~2-5 minutes)
poetry run kg transform -s mediadive
```

The bulk download runs automatically as part of `kg download` and downloads all MediaDive data to `data/raw/mediadive/`. On subsequent runs, it skips the bulk download if files already exist (use `--ignore-cache` to force re-download).

### Note on Manual Bulk Download

The bulk download is integrated into the `kg download` command and runs automatically. There is no standalone script to run it manually. If you need to re-download the bulk data, use:

```bash
# Force re-download of bulk data
poetry run kg download --ignore-cache

# Run transform
poetry run kg transform -s mediadive
```

### Slow Option: API-Based Transform (Not Recommended)

```bash
# Run transform with API calls (~30-60 minutes first time, then cached)
# Only use if you don't have bulk data downloaded
poetry run kg transform -s mediadive
```

## Performance Comparison

| Approach | First Run | Subsequent Runs | API Calls |
|----------|-----------|-----------------|-----------|
| **Bulk Download** | 30-60 min (one-time) | 2-5 min | 0 |
| **API Calls** | 30-60 min | 2-5 min | 60,000-120,000 |
| **API + Cache** | 30-60 min | 2-5 min | 0 (cached) |

## Data Flow

### Without Bulk Download (API-based)
```
mediadive.json (basic list)
    ↓
MediaDive API (~60-120k calls)
    ↓
YAML Cache (tmp/medium_yaml/, tmp/medium_strain_yaml/)
    ↓
Transform → nodes.tsv, edges.tsv
```

### With Bulk Download (Recommended)
```
poetry run kg download
    ↓
Automatic bulk download hook (`_post_download_mediadive_bulk`)
    ↓
data/raw/mediadive/*.json (all data pre-downloaded)
    ↓
Transform (reads from files, no API calls)
    ↓
nodes.tsv, edges.tsv
```

## Bulk Download

### Automatic Bulk Download (Recommended)

The bulk download runs automatically when you execute:

```bash
poetry run kg download
```

This automatically triggers the bulk download after downloading `mediadive.json` from `download.yaml`. The bulk download:
1. Downloads detailed recipes for all 3,326 media
2. Downloads strain associations for all media
3. Downloads all solution ingredient data
4. Downloads all compound mapping data

The download is skipped if bulk files already exist (use `--ignore-cache` to force re-download).

### Note on Manual Invocation

The bulk download is integrated into `kg_microbe.utils.mediadive_bulk_download` and is called automatically by the `kg download` command. There is no standalone script for manual invocation.

### Output Files

The script creates the following files in `data/raw/mediadive/`:

- **media_detailed.json** (~15-20 MB) - Detailed recipes for all media
- **media_strains.json** (~5-10 MB) - Strain associations for all media
- **solutions.json** (~5-10 MB) - All solution ingredient data
- **compounds.json** (~2-5 MB) - All compound mapping data

### Updating Bulk Data

To refresh the bulk downloaded data (e.g., monthly):

**Option 1: Using automatic workflow**
```bash
# Force re-download of all data including MediaDive bulk files
poetry run kg download --ignore-cache
```

**Option 2: Manual refresh**
```bash
# Remove old MediaDive bulk data
rm -rf data/raw/mediadive/

# Re-download (happens automatically with kg download)
poetry run kg download
```

## Caching System

The transform uses a **three-tier caching strategy**:

### 1. Bulk Downloaded Files (Tier 1 - Fastest)
- **Location**: `data/raw/mediadive/*.json`
- **Created by**: Automatic post-download hook in `kg download`
- **Purpose**: Pre-download all data to avoid API calls
- **Cache hit**: ~100% (if files exist)

### 2. HTTP Cache (Tier 2)
- **Location**: `mediadive_cache.sqlite` (root directory)
- **Created by**: `requests_cache` library
- **Purpose**: Cache HTTP responses from MediaDive API
- **Size**: ~31 MB
- **Auto-created**: Yes (on first API call)

### 3. YAML File Cache (Tier 3)
- **Locations**:
  - `kg_microbe/transform_utils/mediadive/tmp/medium_yaml/` (~3,336 files)
  - `kg_microbe/transform_utils/mediadive/tmp/medium_strain_yaml/` (~2,718 files)
- **Purpose**: Cache individual API responses as YAML files
- **Auto-created**: Yes (on first API call for each medium)

## Cache Management

### Preserving Cache Between Runs

The cache files are persistent and should be preserved between transform runs:

```bash
# Cache files to preserve:
mediadive_cache.sqlite
kg_microbe/transform_utils/mediadive/tmp/medium_yaml/
kg_microbe/transform_utils/mediadive/tmp/medium_strain_yaml/
```

### Clearing Cache

To force refresh of all data:

```bash
# Remove all cache files
rm mediadive_cache.sqlite
rm -rf kg_microbe/transform_utils/mediadive/tmp/medium_yaml/
rm -rf kg_microbe/transform_utils/mediadive/tmp/medium_strain_yaml/

# Remove bulk downloaded data
rm -rf data/raw/mediadive/

# Then re-run download to regenerate bulk data
poetry run kg download
```

### Partial Cache Clear

To refresh only specific types of data:

```bash
# Refresh only medium details
rm -rf kg_microbe/transform_utils/mediadive/tmp/medium_yaml/

# Refresh only strain associations
rm -rf kg_microbe/transform_utils/mediadive/tmp/medium_strain_yaml/

# Refresh HTTP cache
rm mediadive_cache.sqlite
```

## API Endpoints Used

The transform interacts with the following MediaDive REST API endpoints:

| Endpoint | Purpose | Calls (without bulk) |
|----------|---------|---------------------|
| `/rest/media` | Get basic media list | 1 |
| `/rest/medium/{id}` | Get detailed recipe | 3,326 |
| `/rest/medium_strains/{id}` | Get strain associations | 3,326 |
| `/rest/solution/{id}` | Get solution ingredients | ~10,000-15,000 |
| `/rest/compound/{id}` | Get compound mappings | ~50,000-100,000 |

**Total**: ~60,000-120,000 API calls per transform run (without caching)

## Transform Statistics

During the transform, you'll see statistics about data sources:

```
================================================================================
MediaDive Transform Complete
================================================================================
Data source: Bulk downloaded files (data/raw/mediadive/)
API calls avoided: 118,423
API calls made: 0
================================================================================
```

Or, if running without bulk download:

```
================================================================================
MediaDive Transform Complete
================================================================================
Data source: MediaDive API (slow - consider running bulk download)
API calls made: 118,423
To speed up future transforms, run: poetry run kg download
================================================================================
```

## Troubleshooting

### Transform is slow

**Cause**: No bulk data or cache available

**Solution**: Download bulk data (happens automatically with `kg download`)
```bash
poetry run kg download
```

### Bulk download fails partway

**Cause**: Network interruption or API timeout

**Solution**: Re-run the download - it will use HTTP cache to skip already downloaded data
```bash
poetry run kg download
```

### Missing or incomplete data in transform output

**Cause**: Outdated or corrupted cache

**Solution**: Clear cache and re-download
```bash
rm -rf data/raw/mediadive/
rm mediadive_cache.sqlite

# Re-download
poetry run kg download
```

### API rate limiting

**Cause**: Too many API requests

**Solution**: Use bulk download to avoid API calls
```bash
poetry run kg download
```

## Data Structure

### Media Records

Each medium contains:
- **Basic info**: ID, name, source, pH range, links
- **Recipe**: List of solutions and their ingredients
- **Strains**: Bacterial strains that grow in the medium
- **Type**: Complex or defined medium

### Solutions

Each solution contains:
- **Ingredients**: Compounds or sub-solutions
- **Amounts**: Quantity and units
- **Concentrations**: g/L and mmol/L

### Compounds

Each compound is mapped to standard identifiers:
- **ChEBI** (preferred)
- **KEGG**
- **PubChem**
- **CAS Registry Number**

## Integration with KG-Microbe

The MediaDive transform integrates with:
- **BacDive**: Links media to bacterial strains
- **ChEBI**: Standardizes chemical compound IDs
- **NCBITaxon**: Links strains to taxonomic IDs

## Contributing

When modifying the MediaDive transform:

1. Preserve the three-tier caching strategy
2. Update this README if changing cache locations
3. Test with and without bulk downloaded data
4. Verify API call statistics are logged correctly

## References

- [MediaDive Database](https://mediadive.dsmz.de/)
- [MediaDive API Documentation](https://mediadive.dsmz.de/rest)
- [DSMZ (German Collection of Microorganisms and Cell Cultures)](https://www.dsmz.de/)
