"""Named source taxa require exact retirement proof before graph publication (#421)."""

import csv
import hashlib
import io
import json
import tarfile

import pytest

from kg_microbe.merge_utils.external_node_closure import resolve_external_references
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.external_identifiers import load_taxid_merges, load_taxid_retirements
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


def _write_rows(path, rows):
    """Write bounded producer fixtures without changing their complete column inventory."""
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _place_canonical_companion(source, rows, canonical, companion, placement):
    """Place a canonical row before or after its anonymous donor in one or two members."""
    canonical_path = source.output_node_file
    if placement.endswith("row"):
        _write_rows(canonical_path, [companion, *rows] if placement == "first-row" else [*rows, companion])
    else:
        canonical_path = source.output_dir / ("a_nodes.tsv" if placement == "first-file" else "z_nodes.tsv")
        _write_rows(canonical_path, [canonical])
        _write_rows(source.output_node_file, [row for row in rows if row is not canonical] + [companion])
    return canonical_path


def _select_ten(source, *, endpoint, dependency_only):
    """Select only original 10 so replacement intermediates cannot enter through source rows."""
    nodes = [
        row
        for row in graph_rows(source.output_node_file)
        if row["id"] == "fixture:1" or (row["id"] == "NCBITaxon:10" and not dependency_only)
    ]
    edge = next(row for row in graph_rows(source.output_edge_file) if row["value"] == "ten")
    if endpoint == "object":
        edge["subject"], edge["object"] = edge["object"], edge["subject"]
    _write_rows(source.output_node_file, nodes)
    _write_rows(source.output_edge_file, [dict(edge, value=value) for value in ("first", "second")])


def _chain_authority(raw, intermediates, *, live=(), reverse=False):
    """Place nameless live contradictions only on the requested hidden native chain members."""
    chain = ["10", *intermediates, "12"]
    merged = [f"{old} | {new} |" for old, new in zip(chain[:-1], chain[1:], strict=True)]
    nodes = ["1 | 1 | no rank |", "2 | 1 | superkingdom |", "12 | 2 | species |"]
    nodes.extend(f"{taxid} | 2 | species |" for taxid in live)
    if reverse:
        merged.reverse()
        nodes.reverse()
    return _authority(
        raw,
        merged="\n".join(merged) + "\n",
        deleted="",
        overrides={
            "nodes.dmp": "\n".join(nodes) + "\n",
            "names.dmp": "12 | Accepted bacterium | | scientific name |\n",
        },
    )


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
        "infores:canonical",
        "infores:ten",
        "infores:eleven",
        "infores:ncbitaxon",
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
    assert (
        resolve_external_references(
            source.output_node_file, source.output_edge_file, source.input_base_dir, source.output_dir / "audit.tsv"
        )
        == {}
    )
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

    def mutate_after_read(path, **kwargs):
        """Change the real authority after parsing the private immutable snapshot."""
        result = original(path, **kwargs)
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
    source.output_node_file.write_text(
        "id\tname\tcategory\tprovided_by\nfixture:1\tEntity\tbiolink:NamedThing\tinfores:source\n"
    )
    source.output_edge_file.write_text(
        "subject\tpredicate\tobject\trelation\tprimary_knowledge_source\n"
        "fixture:1\tbiolink:related_to\tfixture:1\tskos:related\tinfores:source\n"
    )
    report = source.finalize()
    assert "ncbi_taxonomy_authority" not in report["consumed_inputs"]
    assert _rows(source, "source_reference_resolution.tsv") == []
    assert source.finalize() == report
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])


@pytest.mark.parametrize("dependent", [False, True])
@pytest.mark.parametrize("canonical_kind", ["named", "typed", "anonymous"])
@pytest.mark.parametrize("placement", ["first-row", "last-row", "first-file", "last-file"])
def test_existing_canonical_declaration_keeps_one_row_and_source_context(
    tmp_path, canonical_kind, placement, dependent
):
    """Canonical coalescing survives source/dependency declaration and bundle order (#1693, #1706)."""
    source = _source(tmp_path, dependent=dependent)
    dependency = source.output_base_dir / "ontologies" / "ncbitaxon_nodes.tsv"
    if dependent:
        dependency.write_text("id\tname\tcategory\nNCBITaxon:12\tUpstream canonical\tbiolink:OrganismTaxon\n")
    rows = list(graph_rows(source.output_node_file))
    for row in rows:
        row["xref"] = f"record:{row['id'].split(':')[-1]}"
    canonical = next(row for row in rows if row["id"] == "NCBITaxon:12")
    if canonical_kind != "named":
        canonical["name"] = ""
    if canonical_kind == "anonymous":
        canonical["category"] = "biolink:NamedThing"
    original_canonical = dict(canonical)
    donors = {row["id"]: dict(row) for row in rows if row["id"] in {"NCBITaxon:10", "NCBITaxon:11"}}
    others = [row for row in rows if row is not canonical]
    canonical_path = source.output_node_file
    if placement.endswith("row"):
        _write_rows(canonical_path, [canonical, *others] if placement == "first-row" else [*others, canonical])
    else:
        canonical_path = source.output_dir / ("a_nodes.tsv" if placement == "first-file" else "z_nodes.tsv")
        _write_rows(canonical_path, [canonical])
        _write_rows(source.output_dir / "middle_nodes.tsv", [donors["NCBITaxon:11"]])
        _write_rows(source.output_node_file, [row for row in others if row["id"] != "NCBITaxon:11"])
    original_edges = list(graph_rows(source.output_edge_file))
    report = source.finalize()
    node_paths = sorted(source.output_dir.glob("*nodes.tsv"))
    actual_rows = [(path, row) for path in node_paths for row in graph_rows(path)]
    canonical_rows = [(path, row) for path, row in actual_rows if row["id"] == "NCBITaxon:12"]
    assert len(canonical_rows) == 1
    actual_path, actual = canonical_rows[0]
    assert len(actual_rows) == len({row["id"] for _, row in actual_rows}) == 5
    if canonical_kind == "anonymous":
        assert actual["name"] == "Accepted bacterium"
        assert actual["deprecated"] == actual["xref"] == ""
    else:
        assert actual_path == canonical_path
        for field in ("name", "category", "deprecated", "xref"):
            assert actual[field] == original_canonical[field]
    assert actual["category"] == "biolink:OrganismTaxon"
    assert set(actual["provided_by"].split("|")) == {
        "infores:canonical",
        "infores:ten",
        "infores:eleven",
        "infores:ncbitaxon",
    }
    assert all(row["description"] in actual["description"] for row in [original_canonical, *donors.values()])
    edges = list(graph_rows(source.output_edge_file))
    assert len(edges) == len(original_edges)
    for original, actual_edge in zip(original_edges, edges, strict=True):
        for endpoint in ("subject", "object"):
            if original[endpoint] in donors:
                assert actual_edge[endpoint] == "NCBITaxon:12"
                assert actual_edge[f"original_{endpoint}"] == original[endpoint]
            else:
                assert actual_edge[endpoint] == original[endpoint]
        assert actual_edge["value"] == original["value"]
    audit = _rows(source, "source_reference_resolution.tsv")
    retired = [row for row in audit if row["disposition"] == "retired_id_replaced"]
    assert {row["original_id"] for row in retired} == set(donors)
    assert all(json.loads(row["original_node_json"]) == donors[row["original_id"]] for row in retired)
    assert all(json.loads(row["original_edge_json"]) in original_edges for row in retired)
    if canonical_kind != "anonymous":
        assert not any(row["original_id"] == "NCBITaxon:12" for row in audit)
    else:
        # Anonymous canonical rows use the same authority-only scalar policy
        # whether a dependency declares the ID or not; retain their full source
        # context and verbatim original in the audit, not the synthesized row.
        canonical_audit = [row for row in audit if row["original_id"] == "NCBITaxon:12"]
        assert canonical_audit
        assert all(json.loads(row["original_node_json"]) == original_canonical for row in canonical_audit)
        assert {row["disposition"] for row in canonical_audit} == {"authority_declaration"}
    if dependent:
        assert {
            "path": str(dependency.resolve()),
            "sha256": hashlib.sha256(dependency.read_bytes()).hexdigest(),
        } in report["inputs"]
    before = _published(source)
    assert source.finalize() == report
    assert _published(source) == before
    verify_finalized_source_files([*node_paths, source.output_edge_file])


def test_unselected_dependency_declarations_remain_outside_retirement_coalescing(tmp_path):
    """Coalescing one selected canonical ID cannot resolve or trim other dependency-known rows."""
    source = _source(tmp_path, dependent=True)
    dependency = source.output_base_dir / "ontologies" / "ncbitaxon_nodes.tsv"
    dependency.write_text(
        "id\tname\tcategory\n"
        "NCBITaxon:12\tUpstream canonical\tbiolink:OrganismTaxon\n"
        "NCBITaxon:20\tUpstream eukaryote\tbiolink:OrganismTaxon\n"
        "NCBITaxon:99\tUpstream unknown\tbiolink:OrganismTaxon\n"
    )
    rows = list(graph_rows(source.output_node_file))
    for row in rows:
        if row["id"] in {"NCBITaxon:12", "NCBITaxon:20", "NCBITaxon:99"}:
            row["name"], row["category"] = "", "biolink:NamedThing"
    _write_rows(source.output_node_file, rows)
    untouched = {row["id"]: row for row in rows if row["id"] in {"NCBITaxon:20", "NCBITaxon:99"}}
    report = source.finalize()
    output_rows = list(graph_rows(source.output_node_file))
    assert len([row for row in output_rows if row["id"] == "NCBITaxon:12"]) == 1
    assert {row["id"]: row for row in output_rows if row["id"] in untouched} == untouched
    assert not any(row["original_id"] in untouched for row in _rows(source, "source_reference_resolution.tsv"))
    before = _published(source)
    assert source.finalize() == report
    assert _published(source) == before
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])


@pytest.mark.parametrize("anonymous_first", [False, True])
def test_typed_canonical_survives_same_id_anonymous_companion(tmp_path, anonymous_first):
    """A same-ID authority decision cannot discard an unnamed specific-category declaration."""
    source = _source(tmp_path)
    rows = list(graph_rows(source.output_node_file))
    canonical = next(row for row in rows if row["id"] == "NCBITaxon:12")
    canonical["name"] = ""
    companion = dict(canonical, category="biolink:NamedThing", provided_by="infores:companion", deprecated="true")
    _write_rows(source.output_node_file, [companion, *rows] if anonymous_first else [*rows, companion])
    source.finalize()
    actual = [row for row in graph_rows(source.output_node_file) if row["id"] == "NCBITaxon:12"]
    assert len(actual) == 1
    assert actual[0]["name"] == ""
    assert actual[0]["category"] == "biolink:OrganismTaxon"
    assert actual[0]["deprecated"] == "false"
    assert "infores:companion" in actual[0]["provided_by"].split("|")
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])


@pytest.mark.parametrize("canonical_kind", ["named", "typed"])
@pytest.mark.parametrize("placement", ["first-row", "last-row", "first-file", "last-file"])
@pytest.mark.parametrize("endpoint", ["subject", "object"])
def test_explicit_nonprokaryote_canonical_keeps_companion_context(tmp_path, canonical_kind, placement, endpoint):
    """Anonymous companions cannot erase a declared retirement target or its observations (#1700)."""
    source = _source(tmp_path)
    authority = _authority(source.input_base_dir, merged="10 | 20 |\n11 | 20 |\n")
    rows = list(graph_rows(source.output_node_file))
    canonical = next(row for row in rows if row["id"] == "NCBITaxon:20")
    if canonical_kind == "typed":
        canonical["name"] = ""
    original_canonical = dict(canonical)
    companion = dict(
        canonical,
        name="",
        category="biolink:NamedThing",
        provided_by="infores:companion",
        description="Anonymous companion context",
        deprecated="true",
    )
    canonical_path = _place_canonical_companion(source, rows, canonical, companion, placement)
    donors = {row["id"]: row for row in rows if row["id"] in {"NCBITaxon:10", "NCBITaxon:11"}}
    original_edges = list(graph_rows(source.output_edge_file))
    if endpoint == "object":
        for row in original_edges:
            row["subject"], row["object"] = row["object"], row["subject"]
        _write_rows(source.output_edge_file, original_edges)
    report = source.finalize()
    node_paths = sorted(source.output_dir.glob("*nodes.tsv"))
    published_rows = [(path, row) for path in node_paths for row in graph_rows(path)]
    matches = [(path, row) for path, row in published_rows if row["id"] == "NCBITaxon:20"]
    assert len(matches) == 1
    actual_path, actual = matches[0]
    assert actual_path == canonical_path
    for field in ("id", "name", "category", "deprecated"):
        assert actual[field] == original_canonical[field]
    assert set(actual["provided_by"].split("|")) == {
        "infores:source",
        "infores:companion",
        "infores:ten",
        "infores:eleven",
        "infores:ncbitaxon",
    }
    for row in [original_canonical, companion, *donors.values()]:
        assert row["description"] in actual["description"]
    edges = list(graph_rows(source.output_edge_file))
    node_ids = {row["id"] for _, row in published_rows}
    assert len(edges) == len(original_edges)
    for original, actual_edge in zip(original_edges, edges, strict=True):
        for field, value in original.items():
            if field in {"subject", "object"} and value in donors:
                assert actual_edge[field] == "NCBITaxon:20"
                assert actual_edge[f"original_{field}"] == value
            else:
                assert actual_edge[field] == value
        assert actual_edge["subject"] in node_ids
        assert actual_edge["object"] in node_ids
    audit = _rows(source, "source_reference_resolution.tsv")
    assert not any(row["disposition"].startswith("excluded") for row in audit)
    for original in [companion, *donors.values()]:
        assert any(json.loads(row["original_node_json"]) == original for row in audit if row["original_node_json"])
    identity = {"path": str(authority.resolve()), "sha256": hashlib.sha256(authority.read_bytes()).hexdigest()}
    assert report["consumed_inputs"]["ncbi_taxonomy_authority"] == identity
    assert {row["authority_sha256"] for row in audit} == {identity["sha256"]}
    before = _published(source)
    assert source.finalize() == report
    assert _published(source) == before
    verify_finalized_source_files([*node_paths, source.output_edge_file])


@pytest.mark.parametrize("canonical_kind", ["named", "typed"])
@pytest.mark.parametrize("placement", ["first-row", "last-row", "first-file", "last-file"])
@pytest.mark.parametrize("taxid", ["30", "99"])
def test_unresolved_canonical_keeps_companion_context(tmp_path, canonical_kind, placement, taxid):
    """Unresolved companion coalescing preserves source context without inventing native proof (#1701)."""
    source = _source(tmp_path)
    identifier = f"NCBITaxon:{taxid}"
    rows = list(graph_rows(source.output_node_file))
    canonical = next(row for row in rows if row["id"] == identifier)
    if canonical_kind == "typed":
        canonical["name"] = ""
    original_canonical = dict(canonical)
    companion = dict(
        canonical,
        name="",
        category="biolink:NamedThing",
        provided_by="infores:companion",
        description="Additional unresolved source context",
        deprecated="opposite scalar value",
    )
    canonical_path = _place_canonical_companion(source, rows, canonical, companion, placement)
    original_edges = [
        row for row in graph_rows(source.output_edge_file) if identifier in (row["subject"], row["object"])
    ]
    report = source.finalize()
    node_paths = sorted(source.output_dir.glob("*nodes.tsv"))
    matches = [(path, row) for path in node_paths for row in graph_rows(path) if row["id"] == identifier]
    assert len(matches) == 1
    actual_path, actual = matches[0]
    assert actual_path == canonical_path
    for field in ("id", "name", "category", "deprecated"):
        assert actual[field] == original_canonical[field]
    assert set(actual["provided_by"].split("|")) == {"infores:source", "infores:companion"}
    assert original_canonical["description"] in actual["description"]
    assert companion["description"] in actual["description"]
    actual_edges = [row for row in graph_rows(source.output_edge_file) if identifier in (row["subject"], row["object"])]
    assert len(actual_edges) == len(original_edges) == 1
    assert all(actual_edges[0][field] == value for field, value in original_edges[0].items())
    assert actual_edges[0]["original_subject"] == actual_edges[0]["original_object"] == ""
    audit = [row for row in _rows(source, "source_reference_resolution.tsv") if row["original_id"] == identifier]
    disposition = "unresolved_deleted_taxid" if taxid == "30" else "unresolved_no_exact_local_authority"
    assert {row["disposition"] for row in audit} == {disposition}
    assert {row["canonical_id"] for row in audit} == {identifier}
    originals = [json.loads(row["original_node_json"]) for row in audit]
    assert companion in originals
    if taxid == "30":
        assert original_canonical in originals
    else:
        assert all(row["authority"] == row["authority_sha256"] == "" for row in audit)
    assert all(json.loads(row["original_edge_json"]) in original_edges for row in audit)
    before = _published(source)
    assert source.finalize() == report
    assert _published(source) == before
    verify_finalized_source_files([*node_paths, source.output_edge_file])


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("endpoint", ["subject", "object"])
@pytest.mark.parametrize("dependency_only", [False, True])
@pytest.mark.parametrize(
    "intermediates,live",
    [
        (("11",), ("10",)),
        (("11",), ("11",)),
        (("11", "13"), ("11",)),
        (("11", "13"), ("13",)),
        (("11", "13"), ("11", "13")),
    ],
)
def test_hidden_live_chain_members_preserve_complete_previous_publication(
    tmp_path, reverse, endpoint, dependency_only, intermediates, live
):
    """Every selected nonterminal must be absent from nodes.dmp before any publication (#1695)."""
    source = _source(tmp_path, dependent=dependency_only)
    _select_ten(source, endpoint=endpoint, dependency_only=dependency_only)
    # Establish a genuine complete earlier publication where 10 is live. A new
    # producer instance then selects new native bytes without reusing snapshots.
    _authority(
        source.input_base_dir,
        merged="",
        deleted="",
        overrides={
            "nodes.dmp": "1 | 1 | no rank |\n2 | 1 | superkingdom |\n10 | 2 | species |\n",
            "names.dmp": "10 | Earlier live taxon | | scientific name |\n",
        },
    )
    source.finalize()
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])
    (source.output_dir / "transform.complete").write_text("previous complete producer marker\n")
    (source.output_dir / "transform_fingerprint.json").write_text('{"previous": "complete"}\n')
    before = _published(source)
    _chain_authority(source.input_base_dir, intermediates, live=live, reverse=reverse)
    current = type(source)("fixture", source.input_base_dir, source.output_base_dir)
    with pytest.raises(ValueError, match=r"retired/deleted taxid (10|11|13) is also a live declaration"):
        current.finalize(fresh_run=True)
    assert _published(current) == before


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("endpoint", ["subject", "object"])
@pytest.mark.parametrize("dependency_only", [False, True])
@pytest.mark.parametrize("intermediates", [("11",), ("11", "13")])
def test_clean_selected_chain_preserves_observations_evidence_and_admission(
    tmp_path, reverse, endpoint, dependency_only, intermediates
):
    """Valid hidden chains forward every observation and keep exact authority/original-row evidence."""
    source = _source(tmp_path, dependent=dependency_only)
    _select_ten(source, endpoint=endpoint, dependency_only=dependency_only)
    authority = _chain_authority(source.input_base_dir, intermediates, reverse=reverse)
    original_nodes = {row["id"]: row for row in graph_rows(source.output_node_file)}
    original_edges = list(graph_rows(source.output_edge_file))
    report = source.finalize()
    edges = list(graph_rows(source.output_edge_file))
    assert len(edges) == len(original_edges) == 2
    assert {row["value"] for row in edges} == {"first", "second"}
    assert all(row[endpoint] == "NCBITaxon:12" and row[f"original_{endpoint}"] == "NCBITaxon:10" for row in edges)
    nodes = [row for row in graph_rows(source.output_node_file) if row["id"] == "NCBITaxon:12"]
    assert len(nodes) == 1
    assert nodes[0]["name"] == "Accepted bacterium"
    assert nodes[0]["deprecated"] == ""
    audit = _rows(source, "source_reference_resolution.tsv")
    assert len(audit) == 2
    assert {row["original_id"] for row in audit} == {"NCBITaxon:10"}
    assert {row["disposition"] for row in audit} == {"retired_id_replaced"}
    assert [json.loads(row["original_edge_json"]) for row in audit] == original_edges
    if dependency_only:
        assert all(row["original_node_json"] == "" for row in audit)
    else:
        assert all(json.loads(row["original_node_json"]) == original_nodes["NCBITaxon:10"] for row in audit)
    identity = {"path": str(authority.resolve()), "sha256": hashlib.sha256(authority.read_bytes()).hexdigest()}
    assert report["consumed_inputs"]["ncbi_taxonomy_authority"] == identity
    assert {row["authority_sha256"] for row in audit} == {identity["sha256"]}
    before = _published(source)
    assert source.finalize() == report
    assert _published(source) == before
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])


def test_live_nonterminal_outside_selected_chain_is_not_new_validation_scope(tmp_path):
    """An unrelated live/retired contradiction is not proof for the selected replacement."""
    source = _source(tmp_path)
    _select_ten(source, endpoint="subject", dependency_only=False)
    _authority(
        source.input_base_dir,
        merged="10 | 11 |\n11 | 12 |\n40 | 41 |\n41 | 12 |\n",
        deleted="",
        overrides={"nodes.dmp": "1 | 1 | no rank |\n2 | 1 | superkingdom |\n12 | 2 | species |\n41 | 2 | species |\n"},
    )
    source.finalize()
    assert all(row["subject"] == "NCBITaxon:12" for row in graph_rows(source.output_edge_file))
    verify_finalized_source_files([source.output_node_file, source.output_edge_file])


@pytest.mark.parametrize("flatten", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_retirement_loader_preserves_flattened_default_and_validated_native_links(tmp_path, flatten, reverse):
    """Optional direct links retain chain proof while existing producer consumers get terminal IDs."""
    path = _chain_authority(tmp_path, ("11", "13"), reverse=reverse)
    flattened = {"10": "12", "11": "12", "13": "12"}
    direct = {"10": "11", "11": "13", "13": "12"}
    assert load_taxid_merges(tmp_path) == flattened
    assert load_taxid_retirements(path) == (flattened, set())
    assert load_taxid_retirements(path, flatten=flatten) == (flattened if flatten else direct, set())


@pytest.mark.parametrize("flatten", [False, True])
@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"merged": "10 | 11 |\n11 | 10 |\n"}, "Cyclic"),
        ({"merged": "10 | 11 |\n10 | 12 |\n"}, "conflicting"),
        ({"deleted": "11 |\n"}, "both deleted"),
    ],
)
def test_retirement_loader_keeps_structural_checks_in_both_modes(tmp_path, flatten, kwargs, match):
    """Retaining native links never bypasses cycle, conflicting-map or intermediate-deletion checks."""
    path = _authority(tmp_path, **kwargs)
    with pytest.raises(ValueError, match=match):
        load_taxid_retirements(path, flatten=flatten)
