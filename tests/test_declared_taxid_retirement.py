"""Named source taxa require exact retirement proof before graph publication (#421)."""

import csv
import hashlib
import io
import json
import tarfile

import pytest

from kg_microbe.merge_utils.external_node_closure import resolve_external_references
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.source_finalization import (
    SourceFinalizationRequired,
    graph_rows,
    verify_finalized_source_files,
)


class _Dependent(Transform):
    """Declare the real ontology dependency so known IDs exercise the production branch."""

    TRANSFORM_INPUTS = ("ontologies",)


def _authority(raw, *, merged=None, deleted="30 |\n", overrides=None, duplicate=None):
    """Write exact immutable local proof, including live nonprokaryotic negative controls."""
    members = {
        "merged.dmp": "10 | 11 |\n11 | 12 |\n" if merged is None else merged,
        "delnodes.dmp": deleted,
        "nodes.dmp": "1 | 1 | no rank |\n2 | 1 | superkingdom |\n12 | 2 | species |\n20 | 1 | species |\n",
        "names.dmp": "12 | Accepted bacterium | | scientific name |\n20 | Live eukaryote | | scientific name |\n",
    }
    members.update(overrides or {})
    path = raw / "taxdump.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            if content is None:
                continue
            info = tarfile.TarInfo(name)
            data = content.encode()
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            if duplicate == name:
                archive.addfile(info, io.BytesIO(data))
    return path


def _source(tmp_path, *, dependent=False):
    """Prepare actual named node/edge output under an isolated selected raw root."""
    raw = tmp_path / "raw"
    raw.mkdir()
    _authority(raw)
    source = (_Dependent if dependent else Transform)("fixture", raw, tmp_path / "transformed")
    source.output_node_file.write_text(
        "id\tname\tcategory\tprovided_by\tdescription\tdeprecated\n"
        "NCBITaxon:10\tRetired ten\tbiolink:OrganismTaxon\tinfores:ten\tFirst source\ttrue\n"
        "NCBITaxon:11\tRetired eleven\tbiolink:OrganismTaxon\tinfores:eleven\tSecond source\ttrue\n"
        "NCBITaxon:12\tExisting canonical\tbiolink:OrganismTaxon\tinfores:canonical\tCanonical context\tfalse\n"
        "NCBITaxon:20\tSource eukaryote\tbiolink:OrganismTaxon\tinfores:source\tPreserve live\tfalse\n"
        "NCBITaxon:30\tDeleted taxon\tbiolink:OrganismTaxon\tinfores:source\tPreserve deleted\ttrue\n"
        "NCBITaxon:99\tUnresolved taxon\tbiolink:OrganismTaxon\tinfores:source\tPreserve unknown\tfalse\n"
        "fixture:1\tObservation\tbiolink:NamedThing\tinfores:source\t\tfalse\n"
    )
    source.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\tknowledge_level\tagent_type\tvalue\tpublications\n"
        + "".join(
            f"{subject}\tbiolink:related_to\t{obj}\tskos:related\tinfores:source\tobservation\tmanual_agent\t{value}\t\n"
            for subject, obj, value in (
                ("NCBITaxon:10", "fixture:1", "ten"),
                ("NCBITaxon:11", "fixture:1", "eleven"),
                ("fixture:1", "NCBITaxon:10", "object"),
                ("NCBITaxon:10", "NCBITaxon:11", "both"),
                ("NCBITaxon:20", "fixture:1", "live"),
                ("NCBITaxon:30", "fixture:1", "deleted"),
                ("NCBITaxon:99", "fixture:1", "unknown"),
            )
        )
    )
    if dependent:
        ontology = source.output_base_dir / "ontologies"
        ontology.mkdir()
        (ontology / "ncbitaxon_nodes.tsv").write_text(
            "id\tname\tcategory\nNCBITaxon:10\tUpstream old declaration\tbiolink:OrganismTaxon\n"
        )
    return source


def _rows(source, filename):
    """Read only these bounded fixtures with their declared audit dialect."""
    return list(graph_rows(source.output_dir / filename, quoting=csv.QUOTE_MINIMAL))


def _published(source):
    """Capture existing publication bytes so a failed finalizer cannot silently repair them."""
    return {path.name: path.read_bytes() for path in source.output_dir.iterdir() if path.is_file()}


@pytest.mark.parametrize("dependent", [False, True])
def test_named_taxids_forward_both_endpoints_preserve_evidence_and_repeat(tmp_path, dependent):
    """The actual finalizer forwards named/dependency-declared donors without pooling observations."""
    source = _source(tmp_path, dependent=dependent)
    originals = {row["id"]: row for row in graph_rows(source.output_node_file)}
    original_edges = list(graph_rows(source.output_edge_file))
    report = source.finalize()
    nodes = {row["id"]: row for row in graph_rows(source.output_node_file)}
    assert set(nodes) == {"NCBITaxon:12", "NCBITaxon:20", "NCBITaxon:30", "NCBITaxon:99", "fixture:1"}
    assert nodes["NCBITaxon:12"]["name"] == "Existing canonical"
    assert nodes["NCBITaxon:12"]["deprecated"] == "false"
    assert set(nodes["NCBITaxon:12"]["provided_by"].split("|")) == {
        "infores:canonical", "infores:ten", "infores:eleven", "infores:ncbitaxon"
    }
    edges = list(graph_rows(source.output_edge_file))
    assert len(edges) == len(original_edges)
    by_value = {row["value"]: row for row in edges}
    assert by_value["ten"]["subject"] == by_value["eleven"]["subject"] == "NCBITaxon:12"
    assert by_value["object"]["object"] == "NCBITaxon:12"
    assert by_value["both"]["subject"] == by_value["both"]["object"] == "NCBITaxon:12"
    assert by_value["both"]["original_subject"] == "NCBITaxon:10"
    assert by_value["both"]["original_object"] == "NCBITaxon:11"
    for identifier in ("NCBITaxon:20", "NCBITaxon:30", "NCBITaxon:99", "fixture:1"):
        assert all(nodes[identifier][key] == value for key, value in originals[identifier].items())
    audit = _rows(source, "source_reference_resolution.tsv")
    retired = [row for row in audit if row["disposition"] == "retired_id_replaced"]
    assert {row["original_id"] for row in retired} == {"NCBITaxon:10", "NCBITaxon:11"}
    assert all(json.loads(row["original_node_json"]) == originals[row["original_id"]] for row in retired)
    assert all(json.loads(row["original_edge_json"]) in original_edges for row in retired)
    assert {row["original_id"] for row in audit if row["disposition"] == "unresolved_deleted_taxid"} == {"NCBITaxon:30"}
    assert not any(row["original_id"] in {"NCBITaxon:20", "NCBITaxon:99"} for row in audit)
    authority = source.input_base_dir / "taxdump.tar.gz"
    identity = {"path": str(authority.resolve()), "sha256": hashlib.sha256(authority.read_bytes()).hexdigest()}
    assert report["consumed_inputs"]["ncbi_taxonomy_authority"] == identity
    assert {row["authority_sha256"] for row in audit} == {identity["sha256"]}
    before = _published(source)
    assert source.finalize() == report
    assert _published(source) == before
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])


def test_compatibility_resolver_does_not_reclassify_named_source_nodes(tmp_path):
    """The historical anonymous API remains separate from explicit source normalization."""
    source = _source(tmp_path)
    before = source.output_node_file.read_bytes(), source.output_edge_file.read_bytes()
    assert resolve_external_references(
        source.output_node_file, source.output_edge_file, source.input_base_dir, source.output_dir / "audit.tsv"
    ) == {}
    assert before == (source.output_node_file.read_bytes(), source.output_edge_file.read_bytes())


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"merged": "10 | 11 |\n11 | 10 |\n"}, "Cyclic"),
        ({"merged": "10 | 11 |\n10 | 12 |\n"}, "conflicting"),
        ({"merged": "10 | 300 |\n"}, "no live named target"),
        ({"deleted": "10 |\n"}, "both deleted"),
        ({"deleted": "12 |\n"}, "both deleted"),
        ({"deleted": "20 |\n"}, "also a live"),
        ({"overrides": {"delnodes.dmp": None}}, "missing or ambiguous"),
        ({"overrides": {"merged.dmp": None}}, "missing or ambiguous"),
        ({"duplicate": "merged.dmp"}, "missing or ambiguous"),
        ({"duplicate": "names.dmp"}, "missing or ambiguous"),
        ({"deleted": "not-a-taxid |\n"}, "invalid deleted"),
        ({"merged": "not-a-taxid | 12 |\n"}, "invalid taxid"),
    ],
)
def test_bad_retirement_proof_preserves_all_existing_outputs(tmp_path, kwargs, match):
    """Invalid or ambiguous native proof fails before publishing any partial repair/report."""
    source = _source(tmp_path)
    _authority(source.input_base_dir, **kwargs)
    (source.output_dir / "source_reference_resolution.tsv").write_text("previous complete audit\n")
    before = _published(source)
    with pytest.raises(ValueError, match=match):
        source.finalize(fresh_run=True)
    assert _published(source) == before


def test_missing_selected_taxdump_fails_without_checkout_fallback(tmp_path):
    """A selected raw root cannot borrow the production authority from the checkout."""
    source = _source(tmp_path)
    (source.input_base_dir / "taxdump.tar.gz").unlink()
    before = _published(source)
    with pytest.raises(FileNotFoundError):
        source.finalize()
    assert _published(source) == before


def test_authority_mutation_during_parse_cannot_attest_old_decisions(tmp_path, monkeypatch):
    """Parsing uses immutable bytes and a changed selected authority prevents publication."""
    from kg_microbe.merge_utils import external_node_closure

    source = _source(tmp_path)
    original = external_node_closure.load_taxid_retirements

    def mutate_after_read(path):
        """Change the real authority after parsing the private immutable snapshot."""
        result = original(path)
        assert path != source.input_base_dir / "taxdump.tar.gz"
        _authority(source.input_base_dir, merged="10 | 20 |\n11 | 20 |\n")
        return result

    monkeypatch.setattr(external_node_closure, "load_taxid_retirements", mutate_after_read)
    before = _published(source)
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        source.finalize()
    assert _published(source) == before


def test_published_authority_or_audit_change_fails_admission(tmp_path):
    """Finalized source admission checks both bound authority bytes and the full original audit."""
    source = _source(tmp_path)
    source.finalize()
    audit = source.output_dir / "source_reference_resolution.tsv"
    original = audit.read_bytes()
    audit.write_bytes(original.replace(b"NCBITaxon:12", b"NCBITaxon:20"))
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    audit.write_bytes(original)
    _authority(source.input_base_dir, merged="10 | 20 |\n11 | 20 |\n")
    with pytest.raises(SourceFinalizationRequired, match="changed"):
        source.finalize()


@pytest.mark.parametrize("damage", ["erase-role", "same-bytes-new-locator"])
def test_receipt_requires_ncbi_role_and_original_selected_locator(tmp_path, damage):
    """Graph-derived authority demand and selected-path binding survive metadata tampering."""
    source = _source(tmp_path)
    selected = source.input_base_dir / "taxdump.tar.gz"
    if damage == "same-bytes-new-locator":
        first = source.input_base_dir / "first.tar.gz"
        selected.rename(first)
        second = source.input_base_dir / "second.tar.gz"
        second.write_bytes(first.read_bytes())
        selected.symlink_to(first.name)
    source.finalize()
    if damage == "erase-role":
        path = source.output_dir / "source_finalization.json"
        report = json.loads(path.read_text())
        del report["consumed_inputs"]["ncbi_taxonomy_authority"]
        path.write_text(json.dumps(report))
    else:
        selected.unlink()
        selected.symlink_to(second.name)
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    with pytest.raises(SourceFinalizationRequired):
        source.finalize()


def test_new_canonical_declared_once_without_retired_scalar_flags(tmp_path):
    """Named donors can converge on a new authority declaration without stale scalar metadata."""
    source = _source(tmp_path)
    source.output_node_file.write_text(
        "\n".join(
            line for line in source.output_node_file.read_text().splitlines() if not line.startswith("NCBITaxon:12\t")
        )
        + "\n"
    )
    source.finalize()
    nodes = [row for row in graph_rows(source.output_node_file) if row["id"] == "NCBITaxon:12"]
    assert len(nodes) == 1
    assert nodes[0]["name"] == "Accepted bacterium"
    assert nodes[0]["category"] == "biolink:OrganismTaxon"
    assert nodes[0]["deprecated"] == ""
    assert set(nodes[0]["provided_by"].split("|")) == {"infores:ten", "infores:eleven", "infores:ncbitaxon"}


def test_named_retired_nonprokaryote_is_forwarded_without_anonymous_trim(tmp_path):
    """Exact replacement is independent of the anonymous-node prokaryote exclusion policy."""
    source = _source(tmp_path)
    _authority(source.input_base_dir, merged="10 | 20 |\n11 | 20 |\n")
    # A duplicate anonymous source row cannot turn a declared taxon into trim scope.
    with source.output_node_file.open("a") as stream:
        stream.write("NCBITaxon:10\t\tbiolink:NamedThing\tinfores:donor\t\t\n")
    source.finalize()
    edges = list(graph_rows(source.output_edge_file))
    assert len(edges) == 7
    assert {row["subject"] for row in edges if row["value"] in {"ten", "eleven"}} == {"NCBITaxon:20"}
    assert not any(
        row["disposition"].startswith("excluded") for row in _rows(source, "source_reference_resolution.tsv")
    )


@pytest.mark.parametrize("erase_inventory", [False, True])
def test_erased_authority_role_cannot_hide_all_excluded_taxon_references(tmp_path, erase_inventory):
    """An empty taxon result still has an authority-dependent exclusion in its audit."""
    source = _source(tmp_path)
    source.output_node_file.write_text(
        "id\tname\tcategory\tprovided_by\n"
        "fixture:1\tObserved entity\tbiolink:NamedThing\tinfores:source\n"
        "NCBITaxon:20\t\tbiolink:NamedThing\t\n"
    )
    source.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "fixture:1\tbiolink:related_to\tNCBITaxon:20\tskos:related\tinfores:source\n"
    )
    report = source.finalize()
    assert not list(graph_rows(source.output_edge_file))
    assert not any(row["id"].startswith("NCBITaxon:") for row in graph_rows(source.output_node_file))
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    assert source.finalize() == report
    del report["consumed_inputs"]["ncbi_taxonomy_authority"]
    if erase_inventory:
        del report["audit_members"]["source_reference_resolution.tsv"]
        report["inputs"] = [item for item in report["inputs"] if not item["path"].endswith("/taxdump.tar.gz")]
        (source.input_base_dir / "taxdump.tar.gz").unlink()
    (source.output_dir / "source_finalization.json").write_text(json.dumps(report))
    with pytest.raises(SourceFinalizationRequired, match="Missing"):
        verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    with pytest.raises(SourceFinalizationRequired, match="Missing"):
        source.finalize()


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("conflict", ["parent", "ancestor", "rank", "scientific-name"])
def test_conflicting_selected_native_taxonomy_cannot_win_by_row_order(tmp_path, conflict, reverse):
    """Competing selected declarations/lineage evidence fail before touching any source publication."""
    source = _source(tmp_path)
    nodes = ["1 | 1 | no rank |", "2 | 1 | superkingdom |", "12 | 2 | species |", "20 | 1 | species |"]
    names = ["12 | Accepted bacterium | | scientific name |", "20 | Live eukaryote | | scientific name |"]
    if conflict == "parent":
        nodes.append("12 | 1 | species |")
    elif conflict == "ancestor":
        nodes[nodes.index("12 | 2 | species |")] = "12 | 50 | species |"
        nodes.extend(["50 | 2 | genus |", "50 | 1 | genus |"])
    elif conflict == "rank":
        nodes.append("12 | 2 | genus |")
    else:
        names.append("12 | Conflicting bacterium | | scientific name |")
    if reverse:
        nodes.reverse()
        names.reverse()
    _authority(
        source.input_base_dir,
        overrides={"nodes.dmp": "\n".join(nodes) + "\n", "names.dmp": "\n".join(names) + "\n"},
    )
    (source.output_dir / "source_reference_resolution.tsv").write_text("previous complete audit\n")
    before = _published(source)
    with pytest.raises(ValueError, match="conflicting NCBI"):
        source.finalize(fresh_run=True)
    assert _published(source) == before


def test_no_taxonomy_bundle_keeps_honestly_empty_external_audit(tmp_path):
    """Mandatory audit identity does not invent a taxdump requirement when the source has no taxa."""
    source = _source(tmp_path)
    (source.input_base_dir / "taxdump.tar.gz").unlink()
    source.output_node_file.write_text("id\tname\tcategory\tprovided_by\nfixture:1\tEntity\tbiolink:NamedThing\tinfores:source\n")
    source.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "fixture:1\tbiolink:related_to\tfixture:1\tskos:related\tinfores:source\n"
    )
    report = source.finalize()
    assert "ncbi_taxonomy_authority" not in report["consumed_inputs"]
    assert _rows(source, "source_reference_resolution.tsv") == []
    assert source.finalize() == report
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
