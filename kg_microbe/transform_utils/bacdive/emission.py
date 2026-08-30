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


#: Header of the deposit-claim report written alongside nodes.tsv / edges.tsv.
DEPOSIT_CONFLICT_HEADER = [
    "strain_id",
    "parent_count",
    "parents",
    "bacdive_ids",
    "resolution",
    "asserted_parent",
]

#: The claims sat on one lineage; the shared ancestor was asserted (#898).
RESOLUTION_COLLAPSED = "collapsed"
#: The claims were disjoint; no parent was asserted.
RESOLUTION_SUPPRESSED = "suppressed"
#: Ancestry for at least one claim could not be read, so the claims could not be
#: compared and the deposit was suppressed as a precaution rather than a verdict.
#: Distinguishing this matters -- a degraded NCBITaxon adapter otherwise looks
#: exactly like a data problem in BacDive (#897).
RESOLUTION_SUPPRESSED_NO_ANCESTRY = "suppressed_ancestry_unavailable"


def entailed_by_every_claim(parents, ancestors_of):
    """
    Return the one claimed taxon that every other claim entails, or None.

    Claims can differ without contradicting each other: one record records the
    species (``Brevundimonas vesicularis``) and another the strain beneath it
    (``Brevundimonas vesicularis NBRC 12165``). The species claim is true either
    way, so it is the strongest statement all claimants support, and asserting it
    privileges neither record. Only a claim that was actually made is eligible --
    falling back to a computed common ancestor would put a taxon nobody claimed
    (often just ``Bacteria``) on the node.

    :param parents: Iterable of claimed NCBITaxon CURIEs.
    :param ancestors_of: Callable mapping a CURIE to its proper ``is_a``
        ancestors, or None when no ontology is available.
    :return: The entailed CURIE, or None when the claims are disjoint.
    """
    if ancestors_of is None:
        return None
    parents = set(parents)
    ancestry = {parent: ancestors_of(parent) for parent in parents}
    for candidate in sorted(parents):
        if all(candidate in ancestry[other] for other in parents if other != candidate):
            return candidate
    return None


def resolve_deposit_parents(claims, ancestors_of=None, ancestry_failed=None):
    """
    Decide which culture-collection deposits may assert a parent taxon (#892).

    A deposit number such as ``ATCC 13722`` identifies a physical deposit, not a
    BacDive record, so several records can cite the same one. When they disagree
    about the taxon, emitting one ``subclass_of`` edge per claiming record leaves
    the deposit node with several parents and nothing to tell them apart, so a
    consumer that takes "the" parent gets whichever one file order put first.

    A parent is asserted when the claimants agree outright, and when they differ
    only in depth along one lineage -- there the shared ancestor is asserted, per
    :func:`entailed_by_every_claim`. Genuinely disjoint claims get no edge.

    Every deposit with more than one claim is reported, whichever way it went, so
    the report answers "what happened here and why" rather than listing only the
    half that lost its edge (#898).

    :param claims: ``{strain CURIE: {NCBITaxon CURIE: [BacDive record key, ...]}}``.
    :param ancestors_of: Callable mapping an NCBITaxon CURIE to its proper ``is_a``
        ancestors. When None, any disagreement is treated as a conflict.
    :param ancestry_failed: Callable reporting whether a CURIE's ancestry could not
        be read, used to mark a suppression that is a precaution rather than a
        verdict (#897). When None, no suppression is marked that way.
    :return: ``(resolved, contested)``. ``resolved`` is a sorted list of
        ``(strain CURIE, NCBITaxon CURIE)`` pairs to emit. ``contested`` is a sorted
        list of ``(strain CURIE, claims, resolution, asserted parent)`` for every
        deposit with more than one claim; ``asserted parent`` is empty when none was.
    """
    resolved = []
    contested = []
    for strain_curie in sorted(claims):
        parents = claims[strain_curie]
        if len(parents) == 1:
            resolved.append((strain_curie, next(iter(parents))))
            continue
        agreed = entailed_by_every_claim(parents, ancestors_of)
        if agreed is None:
            degraded = ancestry_failed is not None and any(ancestry_failed(parent) for parent in parents)
            resolution = RESOLUTION_SUPPRESSED_NO_ANCESTRY if degraded else RESOLUTION_SUPPRESSED
            contested.append((strain_curie, parents, resolution, ""))
        else:
            resolved.append((strain_curie, agreed))
            contested.append((strain_curie, parents, RESOLUTION_COLLAPSED, agreed))
    return resolved, contested


def deposit_conflict_rows(contested):
    """
    Render contested deposit claims as report rows.

    The report is the record that a claim existed and what became of it, so a
    consumer can recover the taxonomy that was suppressed, and see which deposits
    had theirs coarsened to a shared ancestor.

    :param contested: ``contested`` as returned by :func:`resolve_deposit_parents`.
    :return: List of rows matching :data:`DEPOSIT_CONFLICT_HEADER`.
    """
    return [
        [
            strain_curie,
            len(parents),
            "|".join(sorted(parents)),
            "|".join(sorted({key for keys in parents.values() for key in keys})),
            resolution,
            asserted,
        ]
        for strain_curie, parents, resolution, asserted in contested
    ]
