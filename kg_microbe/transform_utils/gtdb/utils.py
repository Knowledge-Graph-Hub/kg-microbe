"""Helper functions for parsing GTDB data."""


def parse_taxonomy_string(taxonomy_str):
    """
    Parse GTDB taxonomy string into list of taxa.

    Args:
        taxonomy_str: "d__Bacteria;p__Proteobacteria;c__Gammaproteobacteria;..."

    Returns:
        List of taxon names: ["d__Bacteria", "p__Proteobacteria", ...]

    """
    return [t.strip() for t in taxonomy_str.split(";") if t.strip()]


def extract_accession_type(accession):
    """
    Extract accession type (GCF or GCA) from accession string.

    Args:
        accession: "RS_GCF_000005845.2" or "GB_GCA_000008865.2" or "GCF_000005845.2"

    Returns:
        tuple: ("GCF_000005845", "2") or ("GCA_000008865", "2")

    """
    # Remove GTDB prefix if present (RS_ or GB_)
    if accession.startswith("RS_") or accession.startswith("GB_"):
        accession = accession[3:]

    parts = accession.split(".")
    base = parts[0]
    version = parts[1] if len(parts) > 1 else "1"
    return base, version


def clean_taxon_name(taxon_name):
    r"""
    Clean taxon name into the canonical GTDB local identifier form.

    Replaces spaces with underscores. The output is also the local ID for
    the `GTDB:` CURIE (e.g. `GTDB:s__Escherichia_coli`), matching the
    Bioregistry-registered format for GTDB (regex `^[cdfgops]__\\w+\\S+$`,
    URI pattern `https://gtdb.ecogenomic.org/tree?r={id}`).

    Note: GTDB taxon names are only "best effort" stable across releases
    (per GTDB's own FAQ), so consumers should pair the CURIE with a release
    label (e.g. via `provided_by` or release-tagged provenance).

    Args:
        taxon_name: "s__Escherichia coli"

    Returns:
        "s__Escherichia_coli"

    """
    return taxon_name.replace(" ", "_")
