"""KGX row-emission helpers for the BacDive transform."""

from kg_microbe.transform_utils.bacdive.references import publication_doi
from kg_microbe.utils.provenance import bacdive_record_url, knowledge_source_tokens, serialize_knowledge_sources

STRAIN_BACDIVE_PREFIX = "kgmicrobe.strain:bacdive_"


class StrainProvenanceWriter:
    """Keep PKS scalar and attach a BacDive record page to strain-derived evidence."""

    def __init__(self, inner_writer, *, knowledge_source: str, ks_column_index: int, publications_column_index: int):
        """Wrap a CSV writer and record the provenance column position."""
        self._inner = inner_writer
        self._ks = knowledge_source
        self._ks_idx = ks_column_index
        self._publications_idx = publications_column_index

    def writerow(self, row, *, publications=None) -> None:
        """Attach explicit item citations and record evidence without changing the primary resource."""
        row = list(row)
        if len(row) > self._ks_idx and row[self._ks_idx] == self._ks:
            if publications:
                row.extend([""] * max(0, self._publications_idx + 1 - len(row)))
                row[self._publications_idx] = serialize_knowledge_sources(
                    [
                        publication_doi(token) or token
                        for token in knowledge_source_tokens([row[self._publications_idx], publications])
                    ]
                )
            for endpoint in (row[0], row[2] if len(row) > 2 else None):
                if isinstance(endpoint, str) and endpoint.startswith(STRAIN_BACDIVE_PREFIX):
                    bacdive_id = endpoint[len(STRAIN_BACDIVE_PREFIX) :]
                    row.extend([""] * max(0, self._publications_idx + 1 - len(row)))
                    row[self._publications_idx] = serialize_knowledge_sources(
                        row[self._publications_idx], bacdive_record_url(bacdive_id)
                    )
                    break
        self._inner.writerow(row)

    def writerows(self, rows) -> None:
        """Apply provenance augmentation to a sequence of rows."""
        for row in rows:
            self.writerow(row)


#: Header of the deposit-claim report written alongside nodes.tsv / edges.tsv.
#: ``withheld_supplied_taxids`` lists citing records whose ambiguous supplied
#: taxids were withheld, as ``<BacDive key>=<CURIE>,<CURIE>`` joined by ``|``;
#: ``other_bacdive_ids`` lists citing records that contributed neither a claim
#: nor withheld candidates (#1421).
DEPOSIT_CONFLICT_HEADER = [
    "strain_id",
    "parent_count",
    "parents",
    "bacdive_ids",
    "resolution",
    "asserted_parent",
    "withheld_supplied_taxids",
    "other_bacdive_ids",
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
#: A record whose ambiguous supplied taxids were withheld cites the deposit, and
#: its candidates could not all be shown to be, or lie beneath, one parent that
#: the other citing records support. That is not proof the records disagree,
#: only that no parent can be asserted for all of them (#1421).
RESOLUTION_SUPPRESSED_WITHHELD = "suppressed_withheld_unresolved"


def contested_deposit_description(parents, withheld=None, others=(), resolution=RESOLUTION_SUPPRESSED):
    """
    Explain, on the node itself, why a contested deposit has no edges (#907).

    A deposit whose claimants disagreed gets neither a parent nor a link to the
    records that cited it, which leaves an organism-typed node with a culture
    number for a label and nothing else -- indistinguishable from an ingest gap.
    The description says which taxa were claimed so the emptiness reads as a
    decision.

    Scoped to BacDive on purpose: 55 of these deposits are the object of an LPSN
    ``close_match`` edge, so a sentence claiming nothing links to the node would
    be false in the merged graph (#908). This transform cannot see LPSN's output
    and should not try to -- it states only what it did itself.

    :param parents: ``{NCBITaxon CURIE: [BacDive record key, ...]}`` for the deposit.
    :param withheld: ``{BacDive record key: [NCBITaxon CURIE, ...]}`` for citing
        records whose ambiguous supplied taxids were withheld (#1421).
    :param others: BacDive record keys of citing records that contributed neither
        a claim nor withheld candidates.
    :param resolution: The deposit's ``RESOLUTION_*`` value. A withheld-record
        suppression is not a proven disagreement, so it is worded as such.
    :return: One-sentence description naming the conflicting claims.
    """
    claims = [f"{taxon} (BacDive {', '.join(sorted(keys))})" for taxon, keys in sorted(parents.items())]
    claims += [
        f"{' or '.join(sorted(taxa))} (BacDive {key}, which supplied these as equal-priority alternatives)"
        for key, taxa in sorted((withheld or {}).items())
    ]
    claims = ", ".join(claims)
    if others:
        claims += f"; it is also cited by BacDive {', '.join(sorted(others))}"
    if resolution == RESOLUTION_SUPPRESSED_WITHHELD:
        return (
            "Culture-collection designation cited by BacDive records that could not be "
            f"shown to describe the same organism: {claims}. BacDive asserts no parent "
            "taxon and no record link for it, because the designation could not be "
            "shown to identify a single organism. Other sources may still reference "
            "this node."
        )
    return (
        "Culture-collection designation claimed by BacDive records that disagree on "
        f"the organism: {claims}. BacDive asserts no parent taxon and no record link "
        "for it, because the designation does not identify a single organism. Other "
        "sources may still reference this node."
    )


def resolution_asserts_a_parent(resolution):
    """
    Report whether a resolution left the deposit with a parent taxon.

    Used to decide whether a record may be linked to the deposit at all. A
    deposit that got a parent is one identifier its claimants agree about, so
    linking to it is sound. One that got none is a designation two unrelated
    organisms happen to share, and ``biolink:close_match`` -- symmetric, and
    mapped to ``SEMMEDDB:same_as`` -- would put those organisms two hops apart
    (#899).

    :param resolution: One of the ``RESOLUTION_*`` values.
    :return: True when a parent was asserted.
    """
    return resolution == RESOLUTION_COLLAPSED


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


def is_contested(parents, withheld=None, citing=None):
    """
    Report whether a deposit's claimants must be resolved rather than trusted.

    Two claimed parents always must. A record whose ambiguous supplied taxids
    were withheld claims no parent, but its candidates are still evidence about
    the organism (#1421). It contests the deposit whenever any other record
    cites it, whether or not that record contributed a claim: a record whose
    parent came only from a late, name-derived route could otherwise be linked
    to an unrelated withheld record. Cited by that record alone, it has nothing
    to contradict.

    :param parents: ``{NCBITaxon CURIE: [BacDive record key, ...]}`` for the deposit.
    :param withheld: ``{BacDive record key: [NCBITaxon CURIE, ...]}`` for the deposit.
    :param citing: Every BacDive record key that cites the deposit. When None, only
        claimants and withheld records are counted.
    :return: True when the deposit belongs in the claims report.
    """
    if len(parents) > 1:
        return True
    if not withheld:
        return False
    if citing is None:
        citing = {key for keys in parents.values() for key in keys} | set(withheld)
    return len(set(citing)) > 1


def _entails(candidate, parent, ancestors_of):
    """Return whether a taxon is the parent itself or lies beneath it."""
    return candidate == parent or (ancestors_of is not None and parent in ancestors_of(candidate))


def resolve_deposit_parents(claims, ancestors_of=None, ancestry_failed=None, withheld=None, citing=None):
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

    A record whose ambiguous supplied taxids were withheld supports no parent,
    but its candidates contest one: the claimed parent survives only if every
    candidate is that taxon or lies beneath it, so the record belongs to it
    whichever candidate is right. Otherwise, and whenever the withheld record
    shares the deposit with a record that claimed nothing, the deposit gets no
    parent and no record links, with :data:`RESOLUTION_SUPPRESSED_WITHHELD` (#1421).
    A candidate is never asserted, not even as a coarser shared parent.

    Every contested deposit is reported, whichever way it went, so the report
    answers "what happened here and why" rather than listing only the half that
    lost its edge (#898).

    :param claims: ``{strain CURIE: {NCBITaxon CURIE: [BacDive record key, ...]}}``.
    :param ancestors_of: Callable mapping an NCBITaxon CURIE to its proper ``is_a``
        ancestors. When None, any disagreement is treated as a conflict.
    :param ancestry_failed: Callable reporting whether a CURIE's ancestry could not
        be read, used to mark a suppression that is a precaution rather than a
        verdict (#897). When None, no suppression is marked that way.
    :param withheld: ``{strain CURIE: {BacDive record key: [NCBITaxon CURIE, ...]}}``
        for citing records whose ambiguous supplied taxids were withheld.
    :param citing: ``{strain CURIE: [BacDive record key, ...]}``, every record that
        cites each withheld-cited deposit. See :func:`is_contested`.
    :return: ``(resolved, contested)``. ``resolved`` is a sorted list of
        ``(strain CURIE, NCBITaxon CURIE)`` pairs to emit. ``contested`` is a sorted
        list of ``(strain CURIE, claims, resolution, asserted parent, withheld)`` for
        every deposit :func:`is_contested` selects; ``asserted parent`` is empty when
        none was, and ``withheld`` is empty when no withheld record cited it.
    """
    withheld = withheld or {}
    citing = citing or {}
    resolved = []
    contested = []
    for strain_curie in sorted(set(claims) | set(withheld)):
        parents = claims.get(strain_curie, {})
        contests = withheld.get(strain_curie, {})
        if not is_contested(parents, contests, citing.get(strain_curie)):
            if parents:
                resolved.append((strain_curie, next(iter(parents))))
            continue
        agreed = next(iter(parents)) if len(parents) == 1 else entailed_by_every_claim(parents, ancestors_of)
        supported = agreed is not None
        if supported and not all(
            _entails(candidate, agreed, ancestors_of) for key in sorted(contests) for candidate in contests[key]
        ):
            agreed = None
        if agreed is None:
            evidence = set(parents) | {candidate for taxa in contests.values() for candidate in taxa}
            degraded = ancestry_failed is not None and any(ancestry_failed(taxon) for taxon in sorted(evidence))
            if degraded:
                resolution = RESOLUTION_SUPPRESSED_NO_ANCESTRY
            elif contests and (supported or not parents):
                resolution = RESOLUTION_SUPPRESSED_WITHHELD
            else:
                resolution = RESOLUTION_SUPPRESSED
            contested.append((strain_curie, parents, resolution, "", contests))
        else:
            resolved.append((strain_curie, agreed))
            contested.append((strain_curie, parents, RESOLUTION_COLLAPSED, agreed, contests))
    return resolved, contested


def deposit_conflict_rows(contested, others=None):
    """
    Render contested deposit claims as report rows.

    The report is the record that a claim existed and what became of it, so a
    consumer can recover the taxonomy that was suppressed, and see which deposits
    had theirs coarsened to a shared ancestor.

    :param contested: ``contested`` as returned by :func:`resolve_deposit_parents`.
    :param others: ``{strain CURIE: [BacDive record key, ...]}``, citing records that
        contributed neither a claim nor withheld candidates.
    :return: List of rows matching :data:`DEPOSIT_CONFLICT_HEADER`.
    """
    others = others or {}
    return [
        [
            strain_curie,
            len(parents),
            "|".join(sorted(parents)),
            "|".join(sorted({key for keys in parents.values() for key in keys})),
            resolution,
            asserted,
            "|".join(f"{key}={','.join(sorted(taxa))}" for key, taxa in sorted(withheld.items())),
            "|".join(sorted(others.get(strain_curie, ()))),
        ]
        for strain_curie, parents, resolution, asserted, withheld in contested
    ]
