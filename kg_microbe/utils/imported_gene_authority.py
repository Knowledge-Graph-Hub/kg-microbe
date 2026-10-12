"""
Finite native gene authority for otherwise untyped ontology imports.

The curated contract projects exact NCBI Gene ESummary fields, including native
ID, current-record status, official symbol, and taxon. Namespace recognition is
only a lookup optimization and never supplies biological category evidence.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from urllib.parse import parse_qs, urlparse

from kg_microbe.transform_utils.constants import GENE_CATEGORY

GENE_AUTHORITY_FILE = Path(__file__).resolve().parents[2] / "mappings" / "imported_gene_authority.json"
GENE_NATIVE_EVIDENCE_FILE = GENE_AUTHORITY_FILE.with_name("imported_gene_native_esummary.json")


@dataclass(frozen=True)
class GeneAuthority:
    """Validated category/label evidence; no assertion about incident edges."""

    identifier: str
    name: str
    description: str
    taxon: str
    record_url: str
    category: str = GENE_CATEGORY


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_imported_gene_records(stream, *, native_stream=None) -> dict:
    """Bind a curated snapshot to the exact fields and digest of its native evidence."""
    payload = json.load(stream)
    url = urlparse(payload.get("source_url", ""))
    query = parse_qs(url.query)
    if (
        payload.get("version") != 1
        or payload.get("authority") != "NCBIGene"
        or not re.fullmatch(r"[0-9a-f]{64}", payload.get("source_sha256", ""))
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload.get("retrieved", ""))
        or (url.scheme, url.netloc, url.path) != ("https", "eutils.ncbi.nlm.nih.gov", "/entrez/eutils/esummary.fcgi")
        or query.get("db") != ["gene"]
        or query.get("retmode") != ["json"]
        or not isinstance(payload.get("records"), dict)
        or not payload["records"]
    ):
        raise ValueError("Invalid imported gene authority identity")
    if native_stream is None:
        with GENE_NATIVE_EVIDENCE_FILE.open(encoding="utf-8", newline="") as native_file:
            native_text = native_file.read()
    else:
        native_text = native_stream.read()
    native_bytes = native_text.encode("utf-8") if isinstance(native_text, str) else native_text
    if hashlib.sha256(native_bytes).hexdigest() != payload["source_sha256"]:
        raise ValueError("Invalid imported gene authority native evidence digest")
    native = json.loads(native_bytes)
    native_records = native.get("result", {})
    requested = set(query.get("id", [""])[0].split(","))
    if native.get("header", {}).get("type") != "esummary" or set(native_records.get("uids", [])) != requested:
        raise ValueError("Invalid imported gene authority native response identity")
    result = {}
    for identifier, evidence in payload["records"].items():
        record = evidence.get("native_record", {})
        uid = record.get("uid")
        organism = record.get("organism", {})
        taxid = organism.get("taxid")
        if (
            not isinstance(uid, str)
            or not uid.isdigit()
            or uid not in requested
            or identifier != f"NCBIGene:{uid}"
            or evidence.get("record_url") != f"https://www.ncbi.nlm.nih.gov/gene/{uid}"
            or record.get("status") != ""
            or record.get("currentid") != ""
            or not _nonempty(record.get("name"))
            or not _nonempty(record.get("description"))
            or record.get("nomenclaturesymbol") != record["name"]
            or record.get("nomenclaturename") != record["description"]
            or record.get("nomenclaturestatus") != "Official"
            or type(taxid) is not int
            or taxid <= 0
            or not _nonempty(organism.get("scientificname"))
        ):
            raise ValueError(f"Invalid imported gene authority record for {identifier}")
        original = native_records.get(uid)
        if not isinstance(original, dict) or any(
            key not in original or original[key] != value for key, value in record.items()
        ):
            raise ValueError(f"Invalid imported gene authority projection for {identifier}")
        result[identifier] = GeneAuthority(
            identifier=identifier,
            name=record["name"],
            description=record["description"],
            taxon=f"NCBITaxon:{taxid}",
            record_url=evidence["record_url"],
        )
    if {identifier.removeprefix("NCBIGene:") for identifier in result} != requested:
        raise ValueError("Incomplete imported gene authority response")
    return result


@lru_cache(maxsize=2)
def _load_records(path: str, size: int, mtime_ns: int, native_path: str, native_size: int, native_mtime_ns: int):
    """Stat invalidation helps direct callers; producer snapshots hash exact bytes."""
    del size, mtime_ns, native_size, native_mtime_ns
    with open(path, encoding="utf-8") as stream, open(native_path, encoding="utf-8", newline="") as native_stream:
        return MappingProxyType(load_imported_gene_records(stream, native_stream=native_stream))


def imported_gene_record(identifier: str, *, path: Path | None = None, records=None) -> GeneAuthority | None:
    """Return evidence only for an exact validated record; unknown IDs stay untyped."""
    if not identifier.startswith("NCBIGene:"):
        return None
    if records is None:
        path = GENE_AUTHORITY_FILE if path is None else Path(path)
        stat = path.stat()
        native_stat = GENE_NATIVE_EVIDENCE_FILE.stat()
        records = _load_records(
            str(path.resolve()),
            stat.st_size,
            stat.st_mtime_ns,
            str(GENE_NATIVE_EVIDENCE_FILE.resolve()),
            native_stat.st_size,
            native_stat.st_mtime_ns,
        )
    return records.get(identifier)
