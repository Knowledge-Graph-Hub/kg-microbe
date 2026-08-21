"""KGX row-emission helpers for the BacDive transform."""

STRAIN_BACDIVE_PREFIX = "kgmicrobe.strain:bacdive_"


class StrainProvenanceWriter:

    """Add a BacDive strain CURIE to provenance for strain-derived edges."""

    def __init__(self, inner_writer, *, knowledge_source: str, ks_column_index: int):
        """Wrap a CSV writer and record the provenance column position."""
        self._inner = inner_writer
        self._ks = knowledge_source
        self._ks_idx = ks_column_index

    def writerow(self, row) -> None:
        """Write one row, augmenting bare source provenance when applicable."""
        row = list(row)
        if len(row) > self._ks_idx and row[self._ks_idx] == self._ks:
            for endpoint in (row[0], row[2] if len(row) > 2 else None):
                if isinstance(endpoint, str) and endpoint.startswith(STRAIN_BACDIVE_PREFIX):
                    bacdive_id = endpoint[len(STRAIN_BACDIVE_PREFIX) :]
                    row[self._ks_idx] = f"['{self._ks}', 'bacdive:{bacdive_id}']"
                    break
        self._inner.writerow(row)

    def writerows(self, rows) -> None:
        """Apply provenance augmentation to a sequence of rows."""
        for row in rows:
            self.writerow(row)
