# BacDive MongoDB Download Makefile

.PHONY: bacdive-small bacdive-medium bacdive-large bacdive-reset

# Small exploration - IDs 1-50
bacdive-small:
	poetry run python download_bacdive_subset.py --start-id 1 --end-id 50

# Medium dataset - IDs 1-500
bacdive-medium:
	poetry run python download_bacdive_subset.py --start-id 1 --end-id 500

# Large dataset - IDs 1-2000
bacdive-large:
	poetry run python download_bacdive_subset.py --start-id 1 --end-id 2000

# Drop collection and start fresh with IDs 1-10
bacdive-reset:
	poetry run python download_bacdive_subset.py --start-id 1 --end-id 10 --drop-collection