"""
Tests that each stub-import ontology has exactly one declared source.

Part of #604. A stub source read via ROBOT MIREOT against an OWL must not also
have a SemSQL ``.db`` download, and vice versa: two independently-versioned
copies of the same ontology can drift with nothing to detect it, which is how
``po.db.gz`` came to be downloaded (and never decompressed) while PO's hierarchy
was actually built from ``po.owl``.
"""

from pathlib import Path

import yaml

from kg_microbe.transform_utils.ontologies_stubs.ontologies_stubs_transform import (
    STUB_ONTOLOGY_SOURCES,
)

DOWNLOAD_YAML = Path(__file__).parent.parent / "download.yaml"


def _local_names():
    """Return the set of local_name values declared in download.yaml."""
    with open(DOWNLOAD_YAML) as f:
        return {e["local_name"] for e in (yaml.safe_load(f) or [])}


class TestPoIsOwlOnly:

    """PO's hierarchy comes from the OWL; no SemSQL DB should be fetched."""

    def test_po_stub_uses_owl_mireot(self):
        """The invariant that makes po.db unnecessary."""
        po = STUB_ONTOLOGY_SOURCES["PO"]
        assert po["source_type"] == "owl_mireot"
        assert po["owl_filename"] == "po.owl"
        assert "db_filename" not in po

    def test_po_owl_is_downloaded(self):
        """The source PO actually reads must be declared."""
        assert "po.owl" in _local_names()

    def test_po_semsql_db_is_not_downloaded(self):
        """A PO SemSQL DB would be a second, ungated copy of PO."""
        assert "po.db.gz" not in _local_names()
        assert "po.db" not in _local_names()


class TestNoStubHasTwoSources:

    """Generalise the rule across every stub source."""

    def test_owl_backed_stubs_have_no_db_download(self):
        """An owl_mireot source must not also ship a SemSQL DB."""
        offenders = []
        names = _local_names()
        for prefix, cfg in STUB_ONTOLOGY_SOURCES.items():
            if cfg.get("source_type") != "owl_mireot":
                continue
            stem = Path(cfg["owl_filename"]).stem
            if f"{stem}.db.gz" in names or f"{stem}.db" in names:
                offenders.append(prefix)
        assert offenders == [], f"owl-backed stubs with a redundant .db download: {offenders}"

    def test_db_backed_stubs_have_no_owl_download(self):
        """A SemSQL-backed source must not also ship an OWL of the same ontology."""
        offenders = []
        names = _local_names()
        for prefix, cfg in STUB_ONTOLOGY_SOURCES.items():
            db_filename = cfg.get("db_filename")
            if not db_filename:
                continue
            stem = Path(db_filename).stem
            if f"{stem}.owl" in names or f"{stem}.owl.gz" in names:
                offenders.append(prefix)
        assert offenders == [], f"db-backed stubs with a redundant OWL download: {offenders}"

    def test_every_stub_declares_a_source(self):
        """No stub entry should be missing both an OWL and a DB."""
        missing = [
            prefix
            for prefix, cfg in STUB_ONTOLOGY_SOURCES.items()
            if not cfg.get("owl_filename") and not cfg.get("db_filename") and not cfg.get("nt_filename")
        ]
        assert missing == [], f"stub sources with nothing to read: {missing}"
