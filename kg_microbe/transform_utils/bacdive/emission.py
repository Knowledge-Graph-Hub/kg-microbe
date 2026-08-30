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


#: Header of the deposit-conflict report written alongside nodes.tsv / edges.tsv.
DEPOSIT_CONFLICT_HEADER = ["strain_id", "parent_count", "parents", "bacdive_ids"]


def resolve_deposit_parents(claims):
    """
    Decide which culture-collection deposits may assert a parent taxon (#892).

    A deposit number such as ``ATCC 13722`` identifies a physical deposit, not a
    BacDive record, so several records can cite the same one. When they disagree
    about the taxon, emitting one ``subclass_of`` edge per claiming record leaves
    the deposit node with several parents and nothing to tell them apart, so a
    consumer that takes "the" parent gets whichever one file order put first.
    A parent is asserted only when every claiming record agrees.

    :param claims: ``{strain CURIE: {NCBITaxon CURIE: [BacDive record key, ...]}}``.
    :return: ``(resolved, conflicts)`` where ``resolved`` is a sorted list of
        ``(strain CURIE, NCBITaxon CURIE)`` pairs safe to emit, and ``conflicts``
        is a sorted list of ``(strain CURIE, claims-for-that-deposit)`` pairs.
    """
    resolved = []
    conflicts = []
    for strain_curie in sorted(claims):
        parents = claims[strain_curie]
        if len(parents) > 1:
            conflicts.append((strain_curie, parents))
        else:
            resolved.append((strain_curie, next(iter(parents))))
    return resolved, conflicts


def deposit_conflict_rows(conflicts):
    """
    Render conflicting deposit claims as report rows.

    The report is the record that a claim existed and what it was, so a consumer
    who needs the ambiguous taxonomy can still recover what was suppressed.

    :param conflicts: ``conflicts`` as returned by :func:`resolve_deposit_parents`.
    :return: List of rows matching :data:`DEPOSIT_CONFLICT_HEADER`.
    """
    rows = []
    for strain_curie, parents in conflicts:
        rows.append(
            [
                strain_curie,
                len(parents),
                "|".join(sorted(parents)),
                "|".join(sorted({key for keys in parents.values() for key in keys})),
            ]
        )
    return rows
