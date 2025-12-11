# BacDive NCBITaxon ID Cases

How BacDive records are linked to NCBITaxon based on available taxonomy data.

---

## Case 1: BacDive has strain-level NCBITaxon ID

- NCBITaxon ID with `matching_level == "strain"` exists in BacDive API response
- Creates strain node: `kgmicrobe.strain:bacdive_XXXX`
- Creates subclass edge: `strain → NCBITaxon (strain-level)`
- All feature edges go to strain node only

---

## Case 2: BacDive has species-level NCBITaxon ID (no strain-level available)

- NCBITaxon ID exists but only with `matching_level == "species"`
- Creates strain node: `kgmicrobe.strain:bacdive_XXXX`
- Creates subclass edge: `strain → NCBITaxon (species-level)`
- All feature edges go to strain node only

---

## Case 3: BacDive has NO NCBITaxon ID from API

When `ncbitaxon_id` is `None` from the BacDive API, a fallback search is performed:

### Fallback Search Logic

1. Uses OAK `basic_search()` to search NCBITaxon by scientific name
2. Tries ranks in order until a match is found:
   - `SPECIES` (e.g., "Pusillimonas ginsengisoli")
   - `GENUS` (e.g., "Pusillimonas")
   - `FAMILY`
   - `ORDER`
   - `CLASS`
   - `PHYLUM`
   - `DOMAIN`
3. Stops at first match found

### Case 3a: Fallback search finds a match

- Creates strain node: `kgmicrobe.strain:bacdive_XXXX`
- Creates subclass edge: `strain → NCBITaxon (at matched rank)`
- Prints INFO message: `BacDive {key} - found NCBITaxon {id} via {rank}: {name}`
- All feature edges go to strain node only

### Case 3b: Fallback search finds NO match at any rank

- Creates strain node: `kgmicrobe.strain:bacdive_XXXX`
- **NO subclass edge** - strain node is orphan (not connected to NCBITaxon hierarchy)
- Prints WARNING: `BacDive {key} - no NCBITaxon match found for: {full_name}`
- All feature edges go to strain node only
- Label falls back to scientific name or just `"bacdive_XXXX strain"`

---

## Summary

| Case | NCBITaxon Source | Subclass Edge | Notes |
|------|------------------|---------------|-------|
| 1 | BacDive API (strain-level) | Yes | Best case |
| 2 | BacDive API (species-level) | Yes | Common |
| 3a | OAK search (any rank) | Yes | Fallback succeeded |
| 3b | None | No | Orphan strain node |
