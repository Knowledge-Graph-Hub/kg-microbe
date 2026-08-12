"""
Shared LPSN nomenclature helpers.

LPSN's GSS export marks each record's nomenclatural standing in a ``status``
column. Only rows whose status contains ``correct name`` are the currently
accepted name; everything else — synonyms, illegitimate names, rejected names —
defers to another record through ``record_lnk``.

Two transforms anchor edges on ``lpsn:<record_no>`` and so need the same
resolution:

* **bacdive** matches a strain's reported species against GSS names (#684);
* **microbedecoder** takes ``LPSN_ID`` straight from its source column (#746).

Both were placing live strains under deprecated records. The resolver lived on
``BacDiveTransform`` when only bacdive needed it; it holds no BacDive state, so
it moved here rather than being duplicated.
"""

from typing import Dict

#: LPSN GSS marks the currently accepted name with this phrase in ``status``.
LPSN_CORRECT_NAME = "correct name"

#: Deepest synonym chain observed in the shipped GSS is 3 hops. The cap is a
#: backstop against a cyclic chain in a future release, not a real limit — and
#: it matters because the failure mode of an unbounded walk is a hang rather
#: than a wrong answer, which costs a CI job its whole budget (#742).
LPSN_MAX_SYNONYM_HOPS = 25


def resolve_accepted_records(gss_rows: Dict[str, dict]) -> Dict[str, str]:
    """
    Map each non-current LPSN record to the accepted name it defers to.

    Anchoring on a synonym puts a living strain under a deprecated class, which
    reasoners and any closure step then propagate. Dropping those edges would
    lose real information — the organism genuinely is that taxon, LPSN has simply
    renamed it — so ``record_lnk``, LPSN's own crosswalk, is followed instead.

    Measured on the shipped GSS: every ``record_lnk`` resolves to a real row,
    7,018 synonyms reach a correct name in one hop, 250 in two, 2 in three, and
    no chain cycles. 192 dead-end with no link and are left alone, there being
    nothing better to point them at.

    Bounded as well as cycle-guarded: the ``seen`` set is the real protection,
    but if it were lost the walk would hang rather than answer wrongly, so the
    iteration count is capped too.

    :param gss_rows: ``record_no`` to its parsed GSS row.
    :return: ``record_no`` to accepted ``record_no``, for those that move. A
        record already carrying ``correct name``, or whose chain dead-ends, is
        absent from the mapping.
    """
    accepted: Dict[str, str] = {}
    for record_no, row in gss_rows.items():
        if LPSN_CORRECT_NAME in (row.get("status") or ""):
            continue
        seen = {record_no}
        current = row
        for _ in range(LPSN_MAX_SYNONYM_HOPS):
            link = (current.get("record_lnk") or "").strip()
            if not link or link in seen:
                # Dead-end or a cycle: keep the original rather than guess.
                break
            seen.add(link)
            target = gss_rows.get(link)
            if target is None:
                break
            if LPSN_CORRECT_NAME in (target.get("status") or ""):
                accepted[record_no] = link
                break
            current = target
    return accepted
