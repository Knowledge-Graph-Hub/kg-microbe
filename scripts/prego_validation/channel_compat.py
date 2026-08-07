"""
Identify continuous-channel PREGO edges across both edges.tsv layouts.

The validation scripts in this directory each carried their own ``is_cont``
that matched the shape of an evidence tally (``402 of 487 samples``) against
the ``prego_channel`` column. That was correct only while ``prego_channel``
held PREGO's column 6 verbatim.

Since #703 the channel is derived from the **archive filename**, so
``prego_channel`` holds ``environmental_samples`` and the tally string moved to
a new ``prego_evidence`` column. Against a post-#703 ``edges.tsv`` the old
shape-match therefore returns False for every row, forever — silently. It does
not crash: ``ubiquity_check.py`` reported "0 GO terms" and an empty table with
exit 0, while ``fold_enrichment_go.py`` and ``precision_assay_go.py`` filed
100% of edges under "flat", collapsing the continuous-vs-flat contrast that is
the entire point of both.

Those three scripts produced the numbers in ``docs/PREGO_SCORE_VALIDATION.md``,
so a silent all-rows-excluded failure is the worst possible failure mode here.
This module picks the right test from the header and refuses to return an
empty selection without saying so.
"""

# The archive-derived channel name for the one channel whose score varies.
# Mirrors kg_microbe.transform_utils.prego.utils.CHANNEL_ENVIRONMENTAL; these
# scripts read shipped TSVs and deliberately avoid importing the package.
CHANNEL_ENVIRONMENTAL = "environmental_samples"


def _is_tally(value: str) -> bool:
    """
    Return True for a pre-#703 evidence tally such as ``402 of 487 samples``.

    :param value: Raw column value.
    :return: True if the value has the tally shape.
    """
    parts = value.split()
    return len(parts) == 4 and parts[1] == "of" and parts[3] == "samples" and parts[0].isdigit()


def continuous_predicate(header):
    """
    Return ``(predicate, description)`` for detecting continuous-channel rows.

    Picks the test from the header rather than guessing, so the same script
    works on an ``edges.tsv`` generated before or after #703.

    :param header: Parsed header row of ``edges.tsv`` as a list of column names.
    :return: A tuple of a ``fields -> bool`` predicate and a human-readable
        description of which layout was detected.
    :raises SystemExit: If neither ``prego_channel`` nor ``prego_evidence`` is
        present, since every caller depends on one of them.
    """
    if "prego_evidence" in header:
        # Post-#703: channel is the archive name, tally lives in prego_evidence.
        chi = header.index("prego_channel")
        return (lambda f: f[chi] == CHANNEL_ENVIRONMENTAL), "post-#703 (prego_channel == environmental_samples)"
    if "prego_channel" in header:
        # Pre-#703: prego_channel holds PREGO's column 6 verbatim.
        chi = header.index("prego_channel")
        return (lambda f: _is_tally(f[chi])), "pre-#703 (tally shape in prego_channel)"
    raise SystemExit("edges.tsv has neither prego_channel nor prego_evidence; cannot identify the continuous channel.")


def assert_non_empty(n_continuous: int, description: str) -> None:
    """
    Abort if the continuous selection is empty.

    An empty selection is never a real result on the shipped data — the
    continuous channel is ~53% of PREGO edges. It means the layout probe was
    wrong, which is precisely the silent failure this module exists to prevent.

    :param n_continuous: Number of rows classified continuous.
    :param description: Layout description from :func:`continuous_predicate`.
    :raises SystemExit: If ``n_continuous`` is zero.
    """
    if n_continuous == 0:
        raise SystemExit(
            f"no continuous-channel rows matched using {description}. "
            "The edges.tsv layout is not what was detected — refusing to report "
            "a result computed over zero rows."
        )
