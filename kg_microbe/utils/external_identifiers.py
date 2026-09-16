"""Exact external identifier retirement and assembly alias evidence."""

import csv
import re
import tarfile
from pathlib import Path
from typing import Dict

from kg_microbe.transform_utils.constants import ID_COLUMN, NCBI_ASSEMBLY_PREFIX, SAME_AS_COLUMN

ASSEMBLY_ACCESSION = re.compile(r"ncbi\.assembly:GC[AF]_[0-9]+\.[0-9]+\Z")


def resolve_replacement(identifier: str, replacements: Dict[str, str]) -> str:
    """Follow only explicitly supplied replacements, rejecting cyclic evidence."""
    seen = set()
    while identifier in replacements:
        if identifier in seen:
            raise ValueError(f"Cyclic external identifier replacements: {sorted(seen)}")
        seen.add(identifier)
        identifier = replacements[identifier]
    return identifier


def load_taxid_merges(raw_dir: Path) -> Dict[str, str]:
    """Read NCBI merged.dmp proof; absence means no locally available retirement evidence."""
    path = Path(raw_dir) / "taxdump.tar.gz"
    if not path.is_file():
        return {}
    replacements = {}
    with tarfile.open(path) as archive:
        stream = archive.extractfile("merged.dmp")
        if stream is None:
            raise ValueError(f"{path}: no merged.dmp member")
        for line in stream:
            fields = [item.strip() for item in line.decode("utf-8").split("|")]
            old, new = fields[:2]
            if not old.isdigit() or not new.isdigit():
                raise ValueError(f"{path}: invalid taxid replacement {old!r} -> {new!r}")
            if old in replacements and replacements[old] != new:
                raise ValueError(f"{path}: conflicting replacements for {old}")
            replacements[old] = new
    return {old: resolve_replacement(old, replacements) for old in replacements}


def load_assembly_aliases(nodes_file: Path) -> tuple:
    """
    Return declared assemblies and uniquely proven, version-exact GTDB same_as aliases.

    Never infer a GenBank/RefSeq pair from a shared numeric accession. Both
    accessions come from the GTDB row, and accession versions remain intact.
    """
    declared = set()
    aliases = {}
    with Path(nodes_file).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {ID_COLUMN, SAME_AS_COLUMN} <= set(reader.fieldnames or []):
            raise ValueError(f"{nodes_file}: expected id and same_as columns")
        for row in reader:
            canonical = row[ID_COLUMN]
            if not canonical.startswith(NCBI_ASSEMBLY_PREFIX):
                continue
            if not ASSEMBLY_ACCESSION.fullmatch(canonical):
                raise ValueError(f"{nodes_file}: invalid assembly {canonical}")
            declared.add(canonical)
            for alias in filter(None, row[SAME_AS_COLUMN].split("|")):
                if not ASSEMBLY_ACCESSION.fullmatch(alias):
                    raise ValueError(f"{nodes_file}: invalid assembly alias {alias}")
                if alias == canonical:
                    continue
                if alias in aliases and aliases[alias] != canonical:
                    raise ValueError(f"{nodes_file}: conflicting same_as targets for {alias}")
                aliases[alias] = canonical
    # A declared node is not redirected to a different declared node merely
    # because both happen to occur in same_as columns; that needs reconciliation.
    for alias in aliases:
        if alias in declared:
            raise ValueError(f"{nodes_file}: alias {alias} is also independently declared")
    return declared, aliases
