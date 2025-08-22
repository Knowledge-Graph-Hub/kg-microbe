# BacDive API Tools

Tools for downloading strain data from the BacDive API and storing it in MongoDB.

## Performance

- ~80 records/sec (excluding 1sec/batch API delays)
- Uses batches of 100 IDs per API call

## BacDive ID Distribution

Note that BacDive IDs are not continuous. Based on observed data, there appears to be a gap in available records roughly between IDs 25,000-100,000. For efficient downloads of higher ID ranges, consider starting from ID 100,000.

## Usage

Run from project root directory:

```bash
# Use predefined targets
make -f bacdive_api/bacdive-api.Makefile bacdive-small

# Or run script directly with custom ranges
poetry run python bacdive_api/download_bacdive_subset.py --start-id 100000 --end-id 176000
```

See `bacdive-api.Makefile` for available targets and `--help` for all script options.