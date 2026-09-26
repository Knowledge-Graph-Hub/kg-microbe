"""Helper functions for parsing GTDB data."""

from kg_microbe.transform_utils.constants import NCBI_ASSEMBLY_PREFIX


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


def strip_gtdb_prefix(accession):
    """
    Return a GTDB accession without its archive prefix, version intact.

    Args:
        accession: "RS_GCF_000005845.2", "GB_GCA_000008865.2" or "GCF_000005845.2"

    Returns:
        str: "GCF_000005845.2" / "GCA_000008865.2" / "GCF_000005845.2"

    """
    if accession.startswith(("RS_", "GB_")):
        return accession[3:]
    return accession


def assembly_curie(accession):
    """
    Return the ``ncbi.assembly:`` CURIE for a GTDB accession.

    The version suffix is kept: ``GCA_000005845.1`` and ``.2`` are different
    assemblies of the same genome, and no NCBI resolver accepts a version-less
    accession, so dropping it made the identifier both ambiguous and
    unresolvable (#882). GTDB's own ``RS_``/``GB_`` prefix is not part of the
    NCBI identifier and is dropped; ``GCF_`` vs ``GCA_`` already says which
    archive the accession belongs to.

    Args:
        accession: "RS_GCF_000005845.2" or "GCA_000008865.2"

    Returns:
        str: "ncbi.assembly:GCF_000005845.2"

    """
    return f"{NCBI_ASSEMBLY_PREFIX}{strip_gtdb_prefix(accession)}"


def assembly_archive(accession):
    """
    Return the archive an assembly accession belongs to.

    Args:
        accession: "RS_GCF_000005845.2" or "GCA_000008865.2"

    Returns:
        str: "RefSeq", "GenBank", or "NCBI Assembly" when the accession is
        neither shape.

    """
    stripped = strip_gtdb_prefix(accession)
    if stripped.startswith("GCF_"):
        return "RefSeq"
    if stripped.startswith("GCA_"):
        return "GenBank"
    return "NCBI Assembly"


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
