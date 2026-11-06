"""Trusted NCBITaxon isolation-source targets must have a typed node (#790)."""

import csv
import json
from pathlib import Path
from unittest import TestCase

import ijson
import pytest

from kg_microbe.merge_utils.external_node_closure import resolve_external_reference_bundle
from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import LOCATION_OF, NCBI_CATEGORY, NCBI_TO_ISOLATION_SOURCE_EDGE
from kg_microbe.utils.isolation_source_mapping_utils import load_isolation_source_mappings
from kg_microbe.utils.source_finalization import graph_rows
from kg_microbe.utils.tsv_io import tsv_dict_writer
from tests.test_declared_taxid_retirement import _authority, _source, _write_rows

REPO_ROOT = Path(__file__).resolve().parents[1]
MAPPING_FILE = REPO_ROOT / "mappings" / "isolation_source_to_ontology.tsv"
NCBITAXON_NODES = REPO_ROOT / "data" / "transformed" / "ontologies" / "ncbitaxon_nodes.tsv"


def _trimmed_taxon_ids():
    """
    Ids present in the trimmed NCBITaxon extract.

    :return: Set of CURIEs, empty when the extract has not been built.
    """
    if not NCBITAXON_NODES.is_file():
        return set()
    ids = set()
    with NCBITAXON_NODES.open(encoding="utf-8") as handle:
        handle.readline()
        for line in handle:
            curie = line.split("\t", 1)[0]
            if curie.startswith("NCBITaxon:"):
                ids.add(curie)
    return ids


def _output_predates(output: Path, tracked_input: Path) -> bool:
    """
    Report whether an output was built before its tracked input last changed.

    Uses the input's git commit time, not its mtime: `git checkout` rewrites
    mtimes without changing content (#797).

    :param output: Build artifact to test.
    :param tracked_input: Tracked source file it depends on.
    :return: True when the output is older, or when the comparison is impossible.
    """
    import subprocess

    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, paths built by this module
            ["/usr/bin/git", "log", "-1", "--format=%ct", "--", str(tracked_input)],  # noqa: S607
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    if not out:
        return False
    return output.stat().st_mtime < int(out)


class NcbiTaxonStubTest(TestCase):
    """The trim drops host taxa the isolation-source mapping still points at."""

    def test_the_category_used_for_stubs_is_organism_taxon(self):
        """
        A taxon typed as an ontology class fails Biolink's domain check.

        `biolink:location_of` expects a biological entity; `OntologyClass` — the
        category used for the mesh/NCIT/BTO stubs — is not one. These are taxa,
        so they get the taxon category.
        """
        self.assertEqual(NCBI_CATEGORY, "biolink:OrganismTaxon")

    def test_some_trusted_targets_really_are_missing_from_the_trim(self):
        """
        Pin the premise, so the fix cannot outlive its reason.

        If the trim ever starts carrying these, this test fails and the stub
        path can be reconsidered rather than left as dead code nobody dares
        remove.
        """
        trimmed = _trimmed_taxon_ids()
        if not trimmed:
            self.skipTest("NCBITaxon extract not built")
        trusted = {v[0] for v in load_isolation_source_mappings(MAPPING_FILE).values() if v[0].startswith("NCBITaxon:")}
        self.assertTrue(trusted, "expected some trusted NCBITaxon targets in the mapping")
        missing = trusted - trimmed
        self.assertTrue(
            missing,
            "no trusted NCBITaxon target is missing from the trim — if this is now true, "
            "the stub path in bacdive.py is dead and should be removed",
        )


def _proof_header(path):
    """Stream only closure bindings from the potentially large finalization report."""
    selected = {
        "members",
        "audit_members",
        "consumed_inputs",
        "raw_input_directory",
        "raw_input_locator",
        "tsv_quoting",
    }
    with path.open("rb") as stream:
        events = (
            (prefix, event, value)
            for prefix, event, value in ijson.parse(stream)
            if (not prefix and (event != "map_key" or value in selected)) or prefix.split(".", 1)[0] in selected
        )
        return next(ijson.items(events, ""))


def _json(value):
    """Compare complete finite records independently of JSON key order."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _audit_key(row):
    """Retain every proof field, comparing embedded original records structurally."""
    return _json({key: json.loads(value) if key.endswith("_json") and value else value for key, value in row.items()})


def _write_literal(path, rows):
    """Write finite replay inputs without changing their complete source fields."""
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = tsv_dict_writer(stream, fieldnames=fields, quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writeheader()
        writer.writerows(rows)


def _assert_trusted_closure(source_dir, raw_dir, trusted, scratch, inherited_nodes=()):
    """
    Check referenced taxon closure, not whole-source freshness or scientific admission.

    The current graph/audit and selected authority must match their existing
    finalization bindings. Only finite original retirement witnesses are replayed
    through the production native-chain validator; all replay writes are temporary.
    Graphs and the finalization report are streamed, never materialized wholesale.
    """
    guard = SourceAdmission()
    report_path = source_dir / "source_finalization.json"
    guard.capture(report_path)
    report = _proof_header(report_path)
    assert report["tsv_quoting"] == "none", "expected the finalized literal TSV contract"
    assert Path(report["raw_input_directory"]).resolve() == raw_dir.resolve(), "wrong selected raw root"
    assert Path(report["raw_input_locator"]).absolute() == raw_dir.absolute(), "wrong selected raw locator"
    nodes, edges = source_dir / "nodes.tsv", source_dir / "edges.tsv"
    audit_path = source_dir / "source_reference_resolution.tsv"
    for path, kind in ((nodes, "members"), (edges, "members"), (audit_path, "audit_members")):
        assert guard.capture(path) == report[kind].get(path.name), f"unbound or changed member: {path.name}"
    selected = raw_dir / "taxdump.tar.gz"
    authority = report["consumed_inputs"].get("ncbi_taxonomy_authority")
    assert authority == {"path": str(selected.resolve()), "sha256": guard.capture(selected)["sha256"]}, (
        "missing, changed or foreign selected NCBI authority"
    )

    # Select proof using original assertions too: deleting the rewritten graph
    # edge must not shrink the cohort and turn a missing reference into a pass.
    witnesses = []
    for row in graph_rows(audit_path, quoting=csv.QUOTE_MINIMAL):
        original = json.loads(row["original_edge_json"]) if row["original_edge_json"] else {}
        if original.get("predicate") != NCBI_TO_ISOLATION_SOURCE_EDGE or original.get("subject") not in trusted:
            continue
        if row["original_id"] != original["subject"]:
            continue  # An independently normalized opposite endpoint is not this taxon's proof.
        if row["canonical_id"] == row["original_id"]:
            assert row["disposition"] != "retired_id_replaced", "retirement did not change the identifier"
            continue
        assert row["disposition"] == "retired_id_replaced", "unsupported retirement disposition"
        assert row["authority"] == "taxdump.tar.gz" and row["authority_sha256"] == authority["sha256"], (
            "retirement audit is not bound to the selected native authority"
        )
        node = json.loads(row["original_node_json"]) if row["original_node_json"] else {}
        assert node.get("id") == row["original_id"] and node.get("name"), "missing original named declaration"
        witnesses.append(row)

    expected_edges = []
    if witnesses:
        scratch.mkdir()
        replay_nodes, replay_edges, replay_audit = (scratch / name for name in ("nodes.tsv", "edges.tsv", "audit.tsv"))
        originals = {row["original_node_json"]: json.loads(row["original_node_json"]) for row in witnesses}
        original_edges = {row["original_edge_json"]: json.loads(row["original_edge_json"]) for row in witnesses}
        _write_literal(replay_nodes, list(originals.values()))
        _write_literal(replay_edges, list(original_edges.values()))
        resolve_external_reference_bundle(
            [replay_nodes],
            [replay_edges],
            raw_dir,
            replay_audit,
            discover_references=False,
            include_go=False,
            strict=True,
            quoting=csv.QUOTE_NONE,
            normalize_declared_ncbi=True,
            taxdump_path=selected,
        )
        actual_proof = {_audit_key(row) for row in graph_rows(replay_audit, quoting=csv.QUOTE_MINIMAL)}
        assert actual_proof == {_audit_key(row) for row in witnesses}, "audit disagrees with native retirement replay"
        expected_edges = list(graph_rows(replay_edges))

    # Compare full original context and both endpoint provenance columns. Later
    # finalizers may add empty columns; an added nonempty assertion is not ignored.
    def edge_key(row):
        """Retain every nonempty assertion field when comparing expanded headers."""
        return _json({key: value for key, value in row.items() if value != ""})

    expected = {edge_key(row) for row in expected_edges}
    canonical_targets = {row["subject"] for row in expected_edges}
    required = set(canonical_targets)
    found = set()
    for row in graph_rows(edges):
        if row["predicate"] != NCBI_TO_ISOLATION_SOURCE_EDGE:
            continue
        original = row.get("original_subject") or row["subject"]
        if row["subject"] in trusted:
            required.add(row["subject"])
        if original in trusted:
            required.add(row["subject"])
            if original != row["subject"]:
                assert edge_key(row) in expected, "rewritten taxon edge lacks exact native/audit proof"
        if row["subject"] in canonical_targets:
            found.add(edge_key(row))
    assert expected <= found, "missing rewritten edge or changed original endpoint/context"
    typed = set()
    for path in (nodes, *inherited_nodes):
        guard.capture(path)
        for row in graph_rows(path):
            if row["id"] in required and NCBI_CATEGORY in row.get("category", "").split("|"):
                typed.add(row["id"])
    assert not required - typed, f"referenced taxon lacks OrganismTaxon declaration: {sorted(required - typed)}"
    guard.verify(metadata_only=True)
    return required


def test_no_trusted_ncbitaxon_target_is_left_without_a_node(tmp_path):
    """
    Assert each referenced trusted target has a typed current declaration.

    Before the fix, 8 of 22 were in neither and reached the merged graph as
    `biolink:NamedThing` with no label. They were invisible to the
    dangling-edge check, because KGX materialises a row for any referenced
    endpoint — the signal is the missing category, not a missing node.
    """
    trimmed = _trimmed_taxon_ids()
    bacdive_nodes = REPO_ROOT / "data" / "transformed" / "bacdive" / "nodes.tsv"
    if not trimmed or not bacdive_nodes.is_file():
        pytest.skip("transform outputs not built")
    # The assertion is about the *output*, so it cannot pass until the
    # transform has run since both the mapping and the emit code last
    # changed. Skipping with a reason beats xfail: this re-arms itself after
    # the next rebuild instead of needing someone to remember to flip it
    # back (#812).
    #
    # Both inputs matter, and for different reasons. The mapping decides
    # *which* taxa are referenced; the transform decides whether a stub is
    # written for the ones the trim dropped. A run that predates either one
    # cannot demonstrate the invariant.
    transform_src = REPO_ROOT / "kg_microbe" / "transform_utils" / "bacdive" / "bacdive.py"
    if _output_predates(bacdive_nodes, MAPPING_FILE):
        pytest.skip(
            "data/transformed/bacdive/nodes.tsv predates the current "
            "isolation-source mapping; re-run `poetry run kg transform -s bacdive`"
        )
    if bacdive_nodes.stat().st_mtime < transform_src.stat().st_mtime:
        pytest.skip(
            "data/transformed/bacdive/nodes.tsv predates the current bacdive.py; "
            "re-run `poetry run kg transform -s bacdive`"
        )

    trusted = {v[0] for v in load_isolation_source_mappings(MAPPING_FILE).values() if v[0].startswith("NCBITaxon:")}
    _assert_trusted_closure(
        bacdive_nodes.parent,
        REPO_ROOT / "data" / "raw",
        trusted,
        tmp_path / "retirement-replay",
        inherited_nodes=(NCBITAXON_NODES,),
    )


def _closure_source(tmp_path, *, retired=True):
    """Use the existing actual-finalizer fixture, with explicit isolation-source observations."""
    source = _source(tmp_path)
    selected = {"NCBITaxon:20", "fixture:1"} | ({"NCBITaxon:10"} if retired else set())
    nodes = [row for row in graph_rows(source.output_node_file) if row["id"] in selected]
    edges = [
        row
        for row in graph_rows(source.output_edge_file)
        if row["subject"] in selected and row["value"] in {"ten", "live"}
    ]
    if retired:
        first = next(row for row in edges if row["value"] == "ten")
        edges.append(dict(first, value="ten-second", publications="https://example.org/second-observation"))
    for row in edges:
        row.update(
            predicate=NCBI_TO_ISOLATION_SOURCE_EDGE, relation=LOCATION_OF, primary_knowledge_source="infores:bacdive"
        )
    _write_rows(source.output_node_file, nodes)
    _write_rows(source.output_edge_file, edges)
    source.finalize()
    return source


@pytest.fixture
def closure_source(tmp_path):
    """Finalize a finite native retirement chain and a distinct direct taxon."""
    return _closure_source(tmp_path)


def _check_fixture(source, tmp_path, trusted=frozenset({"NCBITaxon:10", "NCBITaxon:20"})):
    """Run only this scoped assertion on a finalized temporary source."""
    return _assert_trusted_closure(source.output_dir, source.input_base_dir, trusted, tmp_path / "replay")


def _bind_mutated_fixture(source, path, *, kind):
    """Reseal one deliberate synthetic mutation so semantic controls reach beyond a hash mismatch."""
    report_path = source.output_dir / "source_finalization.json"
    report = json.loads(report_path.read_text())
    identity = SourceAdmission().capture(path)
    if kind == "authority":
        report["consumed_inputs"]["ncbi_taxonomy_authority"] = {
            "path": str(path.resolve()),
            "sha256": identity["sha256"],
        }
    else:
        report[kind][path.name] = identity
    report_path.write_text(json.dumps(report))


def test_scoped_closure_accepts_native_chain_and_unchanged_direct_target(closure_source, tmp_path):
    """Actual finalization preserves both distinct original observations and a live direct taxon."""
    before = {path: path.read_bytes() for path in closure_source.output_dir.iterdir() if path.is_file()}
    assert _check_fixture(closure_source, tmp_path) == {"NCBITaxon:12", "NCBITaxon:20"}
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("referenced", [False, True])
def test_scoped_closure_without_retirements_is_explicit(tmp_path, referenced):
    """No selected retirement is required for an unused mapping or an unchanged typed reference."""
    source = _closure_source(tmp_path, retired=False)
    assert not list(graph_rows(source.output_dir / "source_reference_resolution.tsv", quoting=csv.QUOTE_MINIMAL))
    trusted = {"NCBITaxon:20"} if referenced else {"NCBITaxon:999"}
    assert _check_fixture(source, tmp_path, trusted) == ({"NCBITaxon:20"} if referenced else set())
    assert not (tmp_path / "replay").exists()


@pytest.mark.parametrize("target", ["NCBITaxon:12", "NCBITaxon:20"])
@pytest.mark.parametrize("category", [None, "", "biolink:NamedThing", "biolink:OntologyClass"])
def test_scoped_closure_rejects_missing_or_untyped_target(closure_source, tmp_path, target, category):
    """Both direct and retired references require actual typed nodes, even after a fixture reseal."""
    source = closure_source
    rows = list(graph_rows(source.output_node_file))
    if category is None:
        rows = [row for row in rows if row["id"] != target]
    else:
        next(row for row in rows if row["id"] == target)["category"] = category
    _write_literal(source.output_node_file, rows)
    _bind_mutated_fixture(source, source.output_node_file, kind="members")
    with pytest.raises(AssertionError, match="lacks OrganismTaxon"):
        _check_fixture(source, tmp_path)


@pytest.mark.parametrize(
    "mutation", ["missing-audit", "wrong-canonical", "unsupported", "wrong-authority", "missing-node"]
)
def test_scoped_closure_rejects_unproved_retirement(closure_source, tmp_path, mutation):
    """An outer fixture audit hash cannot authorize a missing or invented retirement witness."""
    source = closure_source
    path = source.output_dir / "source_reference_resolution.tsv"
    rows = list(graph_rows(path, quoting=csv.QUOTE_MINIMAL))
    if mutation == "missing-audit":
        path.write_text("\t".join(rows[0]) + "\n")
    else:
        changes = {
            "wrong-canonical": ("canonical_id", "NCBITaxon:20"),
            "unsupported": ("disposition", "unresolved_no_exact_local_authority"),
            "wrong-authority": ("authority_sha256", "0" * 64),
            "missing-node": ("original_node_json", ""),
        }
        key, value = changes[mutation]
        rows[0][key] = value
        _write_rows(path, rows)
    _bind_mutated_fixture(source, path, kind="audit_members")
    with pytest.raises(AssertionError):
        _check_fixture(source, tmp_path)


@pytest.mark.parametrize(
    "mutation", ["missing-edge", "missing-original", "wrong-object", "wrong-predicate", "changed-publication"]
)
def test_scoped_closure_rejects_changed_assertion_context(closure_source, tmp_path, mutation):
    """The audit's complete original assertion must survive, not merely its target and edge count."""
    source = closure_source
    rows = list(graph_rows(source.output_edge_file))
    affected = next(row for row in rows if row.get("original_subject") == "NCBITaxon:10")
    if mutation == "missing-edge":
        rows.remove(affected)
    else:
        changes = {
            "missing-original": ("original_subject", ""),
            "wrong-object": ("object", "fixture:invented"),
            "wrong-predicate": ("predicate", "biolink:related_to"),
            "changed-publication": ("publications", "https://example.org/invented"),
        }
        key, value = changes[mutation]
        affected[key] = value
    _write_literal(source.output_edge_file, rows)
    _bind_mutated_fixture(source, source.output_edge_file, kind="members")
    with pytest.raises(AssertionError):
        _check_fixture(source, tmp_path)


@pytest.mark.parametrize(
    "mutation", ["changed-bytes", "unrelated", "cycle", "live-intermediate", "missing-terminal", "deleted-original"]
)
def test_scoped_closure_rejects_stale_or_contradictory_native_proof(closure_source, tmp_path, mutation):
    """Reuse production chain validation; even synchronized synthetic hashes cannot invent proof."""
    source = closure_source
    kwargs = {
        "changed-bytes": {"merged": "10 | 12 |\n"},
        "unrelated": {"merged": "77 | 12 |\n"},
        "cycle": {"merged": "10 | 11 |\n11 | 10 |\n"},
        "live-intermediate": {
            "overrides": {
                "nodes.dmp": "1 | 1 | no rank |\n2 | 1 | superkingdom |\n11 | 2 | species |\n12 | 2 | species |\n"
            }
        },
        "missing-terminal": {"merged": "10 | 300 |\n"},
        "deleted-original": {"merged": "", "deleted": "10 |\n"},
    }[mutation]
    path = _authority(source.input_base_dir, **kwargs)
    if mutation != "changed-bytes":
        _bind_mutated_fixture(source, path, kind="authority")
        audit = source.output_dir / "source_reference_resolution.tsv"
        rows = list(graph_rows(audit, quoting=csv.QUOTE_MINIMAL))
        for row in rows:
            row["authority_sha256"] = SourceAdmission().capture(path)["sha256"]
        _write_rows(audit, rows)
        _bind_mutated_fixture(source, audit, kind="audit_members")
    with pytest.raises((AssertionError, ValueError)):
        _check_fixture(source, tmp_path)


@pytest.mark.parametrize("mutation", ["missing-role", "foreign-locator", "missing-authority"])
def test_scoped_closure_requires_selected_consumed_authority(closure_source, tmp_path, mutation):
    """A native-looking witness cannot use an absent role or a different authority locator."""
    source = closure_source
    report_path = source.output_dir / "source_finalization.json"
    report = json.loads(report_path.read_text())
    if mutation == "missing-role":
        del report["consumed_inputs"]["ncbi_taxonomy_authority"]
    elif mutation == "foreign-locator":
        original = source.input_base_dir / "taxdump.tar.gz"
        foreign = tmp_path / "same-bytes.tar.gz"
        foreign.write_bytes(original.read_bytes())
        report["consumed_inputs"]["ncbi_taxonomy_authority"]["path"] = str(foreign)
    else:
        (source.input_base_dir / "taxdump.tar.gz").unlink()
    report_path.write_text(json.dumps(report))
    with pytest.raises((AssertionError, ValueError)):
        _check_fixture(source, tmp_path)


def test_unused_mapping_becomes_required_when_referenced(closure_source, tmp_path):
    """Selecting expected references from emitted nodes would incorrectly hide this missing stub."""
    source = closure_source
    rows = list(graph_rows(source.output_edge_file))
    rows.append(dict(rows[-1], subject="NCBITaxon:999", original_subject=""))
    _write_literal(source.output_edge_file, rows)
    _bind_mutated_fixture(source, source.output_edge_file, kind="members")
    with pytest.raises(AssertionError, match="NCBITaxon:999"):
        _check_fixture(source, tmp_path, {"NCBITaxon:999"})


def test_untrusted_original_endpoint_cannot_hide_a_referenced_trusted_target(closure_source, tmp_path):
    """Forged endpoint provenance cannot remove a current trusted target from the closure scope."""
    source = closure_source
    rows = list(graph_rows(source.output_edge_file))
    next(row for row in rows if row["subject"] == "NCBITaxon:20")["original_subject"] = "NCBITaxon:999"
    _write_literal(source.output_edge_file, rows)
    _bind_mutated_fixture(source, source.output_edge_file, kind="members")
    nodes = [row for row in graph_rows(source.output_node_file) if row["id"] != "NCBITaxon:20"]
    _write_literal(source.output_node_file, nodes)
    _bind_mutated_fixture(source, source.output_node_file, kind="members")
    with pytest.raises(AssertionError, match="lacks OrganismTaxon"):
        _check_fixture(source, tmp_path)
