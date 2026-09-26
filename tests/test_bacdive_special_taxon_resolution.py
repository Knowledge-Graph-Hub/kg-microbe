"""Unclassified higher-rank names resolve exact, rank-validated synonyms (#1081)."""

from pathlib import Path

import pytest

from kg_microbe.transform_utils.bacdive import bacdive as module
from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
from kg_microbe.utils.ontology_utils import OntologyDbUnavailableError

FIXTURE = Path(__file__).parent / "resources/assay_reference_repairs/ncbitaxon_nodes.tsv"


@pytest.fixture
def transform(monkeypatch):
    """Load a tiny actual-schema index while keeping rank lookup entirely local."""
    result = BacDiveTransform.__new__(BacDiveTransform)
    result.ncbitaxon_labels = {}
    result.ncbitaxon_name_to_id = {}
    result.ncbitaxon_synonyms = {}
    result._ncbitaxon_rank_cache = {
        "NCBITaxon:356": "order",
        "NCBITaxon:203683": "class",
        "NCBITaxon:201174": "phylum",
        "NCBITaxon:561": "genus",
    }
    monkeypatch.setattr(module, "NCBITAXON_NODES_FILE", FIXTURE)
    result._load_ncbitaxon_labels()
    return result


def test_rhizobiales_resolves_stored_synonym_as_an_order(transform):
    """The label changed to Hyphomicrobiales; its exact synonym still identifies taxon356."""
    token, special = transform._normalize_special_taxon_names("Rhizobiales (not further classified)")
    assert special
    assert "rhizobiales" not in transform.ncbitaxon_name_to_id
    assert transform._resolve_special_taxon_parent(token) == "NCBITaxon:356"
    assert transform._get_ncbitaxon_rank("NCBITaxon:356") == "order"
    assert transform._genus_for_unmatched_name(token, special) is None


@pytest.mark.parametrize(
    "name,target",
    [
        ("Planctomycetia, not further classified", "NCBITaxon:203683"),
        ("Unidentified actinobacterium", "NCBITaxon:201174"),
        ("rhizobiales (not further classified)", "NCBITaxon:356"),
    ],
)
def test_existing_special_name_patterns_remain_supported(transform, name, target):
    """Exact labels, case-folded synonyms and curated common-noun candidates remain usable."""
    token, special = transform._normalize_special_taxon_names(name)
    assert special
    assert transform._resolve_special_taxon_parent(token) == target


def test_ambiguous_higher_rank_synonyms_do_not_select_the_first(transform, caplog):
    """Two valid order candidates require a visible gap, not arbitrary dictionary order."""
    transform.ncbitaxon_labels["NCBITaxon:999"] = "Other order"
    transform.ncbitaxon_synonyms["NCBITaxon:999"] = frozenset({"rhizobiales"})
    transform._ncbitaxon_rank_cache["NCBITaxon:999"] = "order"
    assert transform._resolve_special_taxon_parent("Rhizobiales") is None
    assert "Ambiguous higher-rank taxon" in caplog.text
    assert transform._genus_for_unmatched_name("Rhizobiales", True) is None


@pytest.mark.parametrize("rank", ["genus", "species", None])
def test_wrong_or_unknown_rank_is_not_promoted_to_higher_rank(transform, rank, caplog):
    """Even a matching name cannot provide an unverified order/class/phylum/family parent."""
    transform._ncbitaxon_rank_cache["NCBITaxon:356"] = rank
    assert transform._resolve_special_taxon_parent("Rhizobiales") is None
    assert "no genus inferred" in caplog.text


def test_unknown_special_token_stays_unmapped_without_changing_normal_genus_parsing(transform):
    """The conservative fallback affects unclassified tokens, not ordinary binomials."""
    assert transform._resolve_special_taxon_parent("Unknownales") is None
    assert transform._genus_for_unmatched_name("Unknownales", True) is None
    assert transform._genus_for_unmatched_name("Escherichia coli", False) == "Escherichia"


def test_rank_authority_failure_is_not_a_missing_taxon(transform, monkeypatch):
    """Infrastructure errors abort rather than fabricating an unresolved/genus fallback."""

    def fail_rank(_identifier):
        """Simulate an unreadable taxonomy authority."""
        raise OntologyDbUnavailableError("unreadable rank authority")

    monkeypatch.setattr(transform, "_get_ncbitaxon_rank", fail_rank)
    with pytest.raises(OntologyDbUnavailableError):
        transform._resolve_special_taxon_parent("Rhizobiales")
