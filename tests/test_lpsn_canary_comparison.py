"""Synthetic receipt-binding regressions for the bounded #1852 comparison (#1861)."""

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/adhoc/compare_lpsn_1852_canaries.py"
spec = importlib.util.spec_from_file_location("lpsn_canary_comparison", SCRIPT)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)

DEPOSITS = (
    ("kgmicrobe.strain:JCM-33998", "lpsn:18880"),
    ("kgmicrobe.strain:KCTC-25006", "lpsn:18880"),
    ("kgmicrobe.strain:LMG-31064", "lpsn:10674"),
    ("kgmicrobe.strain:LMG-31064", "lpsn:5244"),
)
GSS_EDGES = "transformed/lpsn/edges.tsv"
CACHE = "raw/lpsn/api_cache/18880.json"


def _write_json(path, value):
    """Serialize small synthetic evidence in the test's own directory."""
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _binding(directory, relative):
    """Build an independent digest with deliberately unavailable historical locators."""
    data = (directory / relative).read_bytes()
    return {
        "path": f"/historical/{directory.name}/{relative}",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _canary(directory, *, corrected):
    """Create structural controls only; these are not native biological evidence."""
    files = {
        "raw/lpsn_gss.csv": "record_no,label\n18880,Synthetic test row\n",
        CACHE: '{"id": 18880, "label": "Synthetic test cache"}\n',
        "transformed/lpsn/nodes.tsv": "id\tcategory\nlpsn:18880\tbiolink:OrganismTaxon\n",
        "transformed/lpsn_api/nodes.tsv": "id\tcategory\nINSDC:TEST\tbiolink:NucleicAcidEntity\n",
        "transformed/lpsn_api/edges.tsv": "subject\tpredicate\tobject\nINSDC:TEST\tbiolink:in_taxon\tlpsn:18880\n",
        "transformed/lpsn/lpsn_parent_dispositions.tsv": "subject\tdisposition\n",
        "transformed/lpsn_api/lpsn_api_records.tsv": f"kind\tpath\nsynthetic\t/historical/{directory.name}\n",
    }
    for relative, text in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    predicate, relation = (
        ("biolink:subclass_of", "rdfs:subClassOf") if corrected else ("biolink:in_taxon", "RO:0002162")
    )
    rows = [(subject, predicate, target, relation) for subject, target in DEPOSITS]
    rows.extend((f"lpsn:{number}", "biolink:subclass_of", "lpsn:10543", "rdfs:subClassOf") for number in range(4))
    with (directory / GSS_EDGES).open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["subject", "predicate", "object", "relation", "primary_knowledge_source"])
        writer.writerows((*row, "infores:lpsn") for row in rows)
    outputs = {
        relative: _binding(directory, relative)
        for relative in [GSS_EDGES, *files]
        if relative.startswith("transformed/")
    }
    original_cache = "/original/private-source/api_cache/18880.json"
    originals = {original_cache: {**_binding(directory, CACHE), "path": original_cache}}
    contract = {
        "version": 2,
        "gss": outputs["transformed/lpsn/nodes.tsv"],
        "gss_edges": outputs[GSS_EDGES],
        "records": {"18880": {**_binding(directory, CACHE), "state": "present"}},
    }
    consumed = {
        "lpsn_api_gss_nodes": contract["gss"],
        "lpsn_api_gss_edges": contract["gss_edges"],
        "lpsn_api_record_18880": _binding(directory, CACHE),
    }
    _write_json(
        directory / "receipt.json",
        {
            "status": "pass_bounded_native_lpsn_edges",
            "gss_rows": 1,
            "outputs": outputs,
            "native_contract": contract,
            "consumed_inputs": consumed,
            "original_inputs": originals,
        },
    )
    _write_json(
        directory / "selection.json",
        {
            "original_inputs": originals,
            "selected_csv": _binding(directory, "raw/lpsn_gss.csv"),
            "gss_complete_rows": [{"record_no": "18880", "label": "Synthetic test row"}],
        },
    )
    return directory


@pytest.fixture
def pair(tmp_path):
    """Return relocated before/after controls without touching any original locator."""
    return _canary(tmp_path / "before", corrected=False), _canary(tmp_path / "after", corrected=True)


def test_exact_four_edge_delta_accepts_relocated_receipt_bound_artifacts(pair):
    """The authorized delta passes despite unavailable original absolute paths."""
    result = comparison.compare(*pair)
    assert result["status"] == "pass_exact_lpsn_1852_delta"
    assert result["changed_deposit_edges"] == 4
    assert result["external_receipt_authenticity_claimed"] is False
    assert {entry["relative_path"] for entry in result["unchanged"]} >= {
        "raw/lpsn_gss.csv",
        CACHE,
        "transformed/lpsn/lpsn_parent_dispositions.tsv",
    }
    assert len(result["canary_receipts"]) == len(result["canary_selections"]) == 2


@pytest.mark.parametrize("sides", [(0,), (1,), (0, 1)], ids=["before-only", "after-only", "identical-both"])
@pytest.mark.parametrize(
    "relative",
    [
        "raw/lpsn_gss.csv",
        CACHE,
        GSS_EDGES,
        "transformed/lpsn/nodes.tsv",
        "transformed/lpsn_api/nodes.tsv",
        "transformed/lpsn_api/edges.tsv",
        "transformed/lpsn/lpsn_parent_dispositions.tsv",
        "transformed/lpsn_api/lpsn_api_records.tsv",
    ],
)
def test_unreceipted_mutations_fail_even_when_both_copies_agree(pair, sides, relative):
    """Pairwise equality cannot conceal independently stale output or input hashes."""
    for index in sides:
        with (pair[index] / relative).open("a") as stream:
            stream.write("identical unrecorded mutation\n")
    with pytest.raises(ValueError, match="SHA256 binding"):
        comparison.compare(*pair)


@pytest.mark.parametrize("relative", ["receipt.json", "selection.json"])
def test_missing_evidence_record_refuses_comparison(pair, relative):
    """An otherwise correct pair needs both original evidence records."""
    (pair[1] / relative).unlink()
    with pytest.raises(FileNotFoundError):
        comparison.compare(*pair)


@pytest.mark.parametrize(
    "section,keys",
    [
        ("outputs", ("transformed/lpsn/nodes.tsv",)),
        ("native_contract", ("gss",)),
        ("native_contract", ("records", "18880")),
        ("consumed_inputs", ("lpsn_api_gss_edges",)),
        ("consumed_inputs", ("lpsn_api_record_18880",)),
        ("original_inputs", ("/original/private-source/api_cache/18880.json",)),
    ],
)
def test_each_receipt_binding_is_required(pair, section, keys):
    """Duplicated roles must each bind their artifact, rather than masking a missing digest."""
    path = pair[1] / "receipt.json"
    receipt = json.loads(path.read_text())
    binding = receipt[section]
    for key in keys:
        binding = binding[key]
    del binding["sha256"]
    _write_json(path, receipt)
    with pytest.raises(ValueError, match="SHA256 binding"):
        comparison.compare(*pair)


def test_selected_gss_requires_its_own_recorded_hash(pair):
    """The whole-source original hash cannot substitute for the selected CSV hash."""
    path = pair[1] / "selection.json"
    selection = json.loads(path.read_text())
    del selection["selected_csv"]["sha256"]
    _write_json(path, selection)
    with pytest.raises(ValueError, match="selection/selected_csv"):
        comparison.compare(*pair)


def test_output_without_receipt_binding_is_rejected(pair):
    """Even reports excluded from cross-run equality must appear in each output inventory."""
    path = pair[1] / "receipt.json"
    receipt = json.loads(path.read_text())
    del receipt["outputs"]["transformed/lpsn_api/lpsn_api_records.tsv"]
    _write_json(path, receipt)
    with pytest.raises(ValueError, match="output membership"):
        comparison.compare(*pair)


def test_identical_unbound_cache_members_fail(pair):
    """An extra file on both sides cannot silently enlarge the consumed native selection."""
    for directory in pair:
        (directory / "raw/lpsn/api_cache/999.json").write_text("{}")
    with pytest.raises(ValueError, match="cache membership"):
        comparison.compare(*pair)


def test_receipted_gss_change_beyond_four_pairs_still_fails(pair):
    """Valid independent receipts cannot authorize a broader semantic delta."""
    after = pair[1]
    path = after / GSS_EDGES
    path.write_text(path.read_text().replace("infores:lpsn", "infores:unexpected", 1))
    receipt_path = after / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    changed = _binding(after, GSS_EDGES)
    receipt["outputs"][GSS_EDGES] = changed
    receipt["native_contract"]["gss_edges"] = changed
    receipt["consumed_inputs"]["lpsn_api_gss_edges"] = changed
    _write_json(receipt_path, receipt)
    with pytest.raises(ValueError, match="beyond the approved"):
        comparison.compare(*pair)


def test_drift_after_initial_binding_cannot_produce_a_passing_result(pair, monkeypatch):
    """Recheck the preserved evidence after table accounting has finished."""
    original = comparison.table

    def read_then_change(path):
        """Mutate an already-compared artifact during the edge-table phase."""
        result = original(path)
        if path == pair[0] / GSS_EDGES:
            with (pair[0] / "transformed/lpsn/nodes.tsv").open("a") as stream:
                stream.write("late change\n")
        return result

    monkeypatch.setattr(comparison, "table", read_then_change)
    with pytest.raises(ValueError, match="changed during comparison"):
        comparison.compare(*pair)


def test_cli_failure_does_not_write_acceptance_receipt(pair, monkeypatch, tmp_path):
    """Missing evidence fails before publishing the new comparison receipt."""
    (pair[1] / "receipt.json").unlink()
    output = tmp_path / "accepted.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--before", str(pair[0]), "--after", str(pair[1]), "--output", str(output)],
    )
    with pytest.raises(FileNotFoundError):
        comparison.main()
    assert not output.exists()
