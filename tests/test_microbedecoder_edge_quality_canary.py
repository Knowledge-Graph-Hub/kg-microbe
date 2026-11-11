"""Keep the bounded native-source canary's recount and refusal behavior explicit."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/adhoc/kgm_microbedecoder_edge_quality_canary_20261110.py"
spec = importlib.util.spec_from_file_location("microbedecoder_edge_quality_canary", SCRIPT)
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


def test_plan_is_read_only_with_pending_native_prerequisites(tmp_path, monkeypatch):
    """Missing native authority is pending, never fabricated or silently written."""
    monkeypatch.setattr(canary, "RAW", tmp_path / "raw")
    monkeypatch.setattr(canary, "OUTPUT", tmp_path / "transformed")
    result = canary.plan()
    assert result["execute"] is False and result["snapshot_graph_mode"] is False
    assert all(item["pending"] for item in result["inputs"])
    assert list(tmp_path.iterdir()) == []


def test_counting_retains_multiple_img_memberships_without_inventing_identity(tmp_path):
    """Count complete literal rows and distinct declarations separately."""
    path = tmp_path / "edges.tsv"
    path.write_text(
        "subject\tpredicate\tobject\trelation\tsource_column\tvalue\n"
        "IMG:1\tbiolink:in_taxon\tlpsn:1\tRO:0002162\tIMG_Genome_ID\t1\n"
        "IMG:1\tbiolink:in_taxon\tlpsn:2\tRO:0002162\tIMG_Genome_ID\t1\n"
    )
    result = canary.table_counts(path, "edges")
    assert result["counts"]["rows"] == result["counts"]["img_subject_edges"] == 2
    assert result["img_ids"] == ["IMG:1"]
    assert result["identity"]["bytes"] == path.stat().st_size


@pytest.mark.parametrize(
    "bad",
    [
        "subject\tpredicate\tobject\trelation\nIMG:1\tbiolink:close_match\tlpsn:1\tskos:closeMatch\n",
        "subject\tpredicate\tobject\trelation\nIMG:1\tbiolink:in_taxon\tlpsn:1\n",
        "subject\tsubject\nIMG:1\tIMG:1\n",
    ],
)
def test_malformed_or_identity_relabelled_img_rows_fail_closed(tmp_path, bad):
    """Counts cannot hide invalid headers, missing cells or a changed membership predicate."""
    path = tmp_path / "edges.tsv"
    path.write_text(bad)
    with pytest.raises(ValueError):
        canary.table_counts(path, "edges")


@pytest.mark.parametrize(
    "rows",
    [
        "IMG:1\tbiolink:OrganismTaxon\n",
        "IMG:1\tbiolink:Genome\nIMG:1\tbiolink:Genome\n",
    ],
)
def test_img_declaration_category_and_uniqueness_are_required(tmp_path, rows):
    """A genome declaration must be real and unique, not an inferred taxon stub."""
    path = tmp_path / "nodes.tsv"
    path.write_text("id\tcategory\n" + rows)
    with pytest.raises(ValueError, match="IMG declaration"):
        canary.table_counts(path, "nodes")


def test_foreign_working_directory_refuses_before_receipt_creation(tmp_path, monkeypatch):
    """The explicit execution flag cannot authorize another checkout or output root."""
    monkeypatch.chdir(tmp_path)
    destination = tmp_path / "receipt"
    monkeypatch.setattr(canary, "RECEIPT_DIRECTORY", destination)
    with pytest.raises(ValueError, match="owned Python and working directory"):
        canary.execute()
    assert not destination.exists()


def test_historical_img_defects_are_reported_without_invalidating_current_output(tmp_path):
    """Historical recount retains wrong category/predicate evidence rather than applying new rules."""
    edges = tmp_path / "edges.tsv"
    edges.write_text("subject\tpredicate\tobject\trelation\nIMG:1\tbiolink:close_match\tlpsn:1\tskos:closeMatch\n")
    nodes = tmp_path / "nodes.tsv"
    nodes.write_text("id\tcategory\nIMG:1\tbiolink:OrganismTaxon\n")
    assert (
        canary.table_counts(edges, "edges", enforce_current=False)["counts"]["img_membership_semantics_violations"] == 1
    )
    assert canary.table_counts(nodes, "nodes", enforce_current=False)["counts"]["img_declaration_violations"] == 1


def test_genuine_direct_gold_finalization_does_not_require_dispatcher_marker(tmp_path, monkeypatch):
    """A real offline GOLD run/finalize is usable without fabricating a CLI fingerprint file."""
    import zipfile

    from tests.test_microbedecoder_transform import FIXTURE_DIR, _supply_gold_fold_report

    output = tmp_path / "transformed"
    raw = tmp_path / "raw"
    raw.mkdir()
    _supply_gold_fold_report(output)
    assert (output / "gold/source_finalization.json").is_file()
    assert not (output / "gold/source_fingerprint.json").exists()
    with zipfile.ZipFile(raw / "microbedecoder_database.zip", "w") as archive:
        archive.write(FIXTURE_DIR / "database.csv", "database.csv")
    (raw / "lpsn_gss.csv").write_text("record_no,record_lnk,status\n")
    (output / "lpsn").mkdir()
    (output / "lpsn/nodes.tsv").write_text("id\tcategory\tname\n")
    # These are explicit planning-only stand-ins, never passed to a native loader.
    for name in ("go.db", "go.owl", "go.db.toolchain.json", "robot", "robot.jar"):
        (raw / name).write_text("synthetic planning prerequisite " + name)
    monkeypatch.setattr(canary, "RAW", raw)
    monkeypatch.setattr(canary, "OUTPUT", output)
    result = canary.plan()
    assert not any(item.get("pending") for item in result["inputs"])
    assert not any(item["path"].endswith("source_fingerprint.json") for item in result["inputs"])


@pytest.mark.parametrize("attempt", ["", "../r2", "r0", "r01", "r2/other", "/r2", "r2\n"])
def test_attempt_rejects_unsafe_or_ambiguous_names_before_writes(tmp_path, monkeypatch, attempt):
    """A retry label cannot escape or alias the fixed evidence generation."""
    monkeypatch.setattr(canary, "RECEIPT_DIRECTORY", tmp_path / "microbedecoder-run-r1")
    with pytest.raises(ValueError, match="positive integer"):
        canary.plan(attempt)
    assert list(tmp_path.iterdir()) == []


def test_retry_plan_selects_new_receipts_without_changing_native_roots(tmp_path, monkeypatch):
    """GOLD remains at its actual admitted path and old failed receipt bytes remain intact."""
    old = tmp_path / "microbedecoder-run-r1"
    old.mkdir()
    (old / "failure.json").write_text("preserved failed original")
    monkeypatch.setattr(canary, "RECEIPT_DIRECTORY", old)
    monkeypatch.setattr(canary, "RAW", tmp_path / "raw")
    monkeypatch.setattr(canary, "OUTPUT", tmp_path / "transformed")
    result = canary.plan("r2")
    assert result["receipt_directory"] == str(tmp_path / "microbedecoder-run-r2")
    assert result["raw"] == str(tmp_path / "raw")
    assert result["output"] == str(tmp_path / "transformed/microbedecoder")
    assert (old / "failure.json").read_text() == "preserved failed original"
    assert not (tmp_path / "microbedecoder-run-r2").exists()
    names = {Path(item["path"]).name for item in result["inputs"]}
    assert {"go.db", "go.owl", "go.db.toolchain.json", "robot", "robot.jar"} <= names


def test_receipt_collision_cannot_overwrite_prior_evidence(tmp_path, monkeypatch):
    """Numbered attempts retain exclusive receipt creation, including failed generations."""
    monkeypatch.setattr(canary, "RECEIPT_DIRECTORY", tmp_path / "microbedecoder-run-r1")
    directory = canary.receipt_directory("r2")
    directory.mkdir()
    path = directory / "result.json"
    canary.write_json(path, {"prior": True})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        directory.mkdir()
    with pytest.raises(FileExistsError):
        canary.write_json(path, {"prior": False})
    assert path.read_bytes() == before


@pytest.mark.parametrize("mutation", [None, "database", "toolchain", "wrong_authority", "late_database"])
def test_go_preflight_binds_real_loader_result_and_guards_before_and_after(tmp_path, monkeypatch, mutation):
    """Offline loader controls prove current-byte binding and refusal before any producer construction."""
    from types import SimpleNamespace

    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils import go_authority

    for name in ("go.db", "go.owl", "go.db.toolchain.json", "robot", "robot.jar"):
        (tmp_path / name).write_text("synthetic owned authority " + name)
    calls = []
    monkeypatch.setenv("KG_SEMSQL_BUILD", "true")

    def load(raw):
        """Stand in for only the native loader, with deliberate isolated preparation drift."""
        assert raw == tmp_path
        calls.append(raw)
        if mutation in {"database", "toolchain"}:
            name = "go.db" if mutation == "database" else "go.db.toolchain.json"
            (raw / name).write_text("changed during preflight")
        return SimpleNamespace(
            authority_path=str(raw / ("foreign.db" if mutation == "wrong_authority" else "go.db")),
            authority_sha256=canary.identity(raw / "go.db")["sha256"],
        )

    monkeypatch.setattr(go_authority, "load_go_authority", load)
    guard = SourceAdmission()
    if mutation in {"database", "toolchain", "wrong_authority"}:
        with pytest.raises(ValueError, match="changed|another authority"):
            canary.verify_go_prerequisite(tmp_path, guard)
    else:
        result = canary.verify_go_prerequisite(tmp_path, guard)
        assert result["authority_sha256"] == canary.identity(tmp_path / "go.db")["sha256"]
        if mutation == "late_database":
            (tmp_path / "go.db").write_text("changed after preflight")
            with pytest.raises(ValueError, match="changed"):
                guard.verify()
        else:
            guard.verify()
    assert calls == [tmp_path]


@pytest.mark.parametrize("mode", ["false", "off", "0", "no", ""])
def test_go_preflight_refuses_toolchain_waiver_before_loading(tmp_path, monkeypatch, mode):
    """An inherited opt-out cannot silently admit an unverified prepared GO database."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils import go_authority

    def forbidden(raw):
        """Any loader call would cross the refused environment boundary."""
        pytest.fail("GO loader called under a forbidden SemSQL mode")

    monkeypatch.setattr(go_authority, "load_go_authority", forbidden)
    monkeypatch.setenv("KG_SEMSQL_BUILD", mode)
    with pytest.raises(ValueError, match="explicitly enabled"):
        canary.verify_go_prerequisite(tmp_path, SourceAdmission())
    assert list(tmp_path.iterdir()) == []
