"""Helper functions for parsing GTDB data."""


def parse_taxonomy_string(taxonomy_str):
    """
    Parse GTDB taxonomy string into list of taxa.

    Args:
        taxonomy_str: "d__Bacteria;p__Proteobacteria;c__Gammaproteobacteria;..."

    Returns:
        List of taxon names: ["d__Bacteria", "p__Proteobacteria", ...]
    """
    return [t.strip() for t in taxonomy_str.split(';') if t.strip()]


def extract_accession_type(accession):
    """
    Extract accession type (GCF or GCA) from accession string.

    Args:
        accession: "RS_GCF_000005845.2" or "GB_GCA_000008865.2" or "GCF_000005845.2"

    Returns:
        tuple: ("GCF_000005845", "2") or ("GCA_000008865", "2")
    """
    # Remove GTDB prefix if present (RS_ or GB_)
    if accession.startswith('RS_') or accession.startswith('GB_'):
        accession = accession[3:]

    parts = accession.split('.')
    base = parts[0]
    version = parts[1] if len(parts) > 1 else "1"
    return base, version


def clean_taxon_name(taxon_name):
    """
    Clean taxon name for use as node name.

    Replace spaces with underscores, handle special characters.

    Args:
        taxon_name: "s__Escherichia coli"

    Returns:
        "s__Escherichia_coli"
    """
    return taxon_name.replace(' ', '_')
