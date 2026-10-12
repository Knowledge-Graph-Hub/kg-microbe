"""Finite selected NCBI aliases require complete original GOLD and authority evidence."""

import copy
import json
from contextlib import ExitStack
from pathlib import Path

import pytest

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.gold import selected_taxon_aliases as aliases
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from tests.gold_selected_alias_fixtures import prepare, report, stage, write_rows, write_taxdump


def test_actual_native_three_aliases_eleven_records_and_all_incidents(tmp_path):
    """Conserve direct and convergent authority witnesses without asserting organism identity."""
    transform, _ = stage(tmp_path)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        assert resolver.resolve("NCBITaxon:53360") == "NCBITaxon:53362"
        assert resolver.resolve("NCBITaxon:659496") == "NCBITaxon:33920"
        assert resolver.resolve("NCBITaxon:1194211") == "NCBITaxon:4927"
        assert resolver.resolve("NCBITaxon:36030") == "NCBITaxon:36030"
        assert resolver.resolve("gold:Go0028995") == "gold:Go0028995"
        chain = json.loads(resolver.evidence_for("NCBITaxon:1194211")["resolution_steps_json"])
        assert {(step["from"], step["to"]) for step in chain} == {
            ("NCBITaxon:1194211", "NCBITaxon:36030"),
            ("NCBITaxon:1194211", "NCBITaxon:4927"),
            ("NCBITaxon:36030", "NCBITaxon:4927"),
        }
        resolver.finish(transform.output_dir)
        contract = resolver.contract()
        assert contract["eligible_record_count"] == 11
        assert contract["native_incident_count"] == 27
        assert contract["eligible_original_ids"] == sorted(aliases.FINITE_IDS)
        assert (transform.output_dir / aliases.AUDIT_FILE).read_text().count("\n") == 4
        saved = report(transform, resolver)
    # Private consumed-input snapshots have closed; only real original inputs remain bound.
    resolver.verify(transform.consumed_input_snapshots)
    admission = SourceAdmission()
    fresh = aliases.restore_recorded(saved, transform.output_dir / "source_finalization.json", admission=admission)
    assert fresh.contract() == contract
    assert fresh.evidence_for("NCBITaxon:53360") == resolver.evidence_for("NCBITaxon:53360")
    admission.verify()


def test_true_empty_native_cohort_consumes_policy_not_selected_authority(tmp_path):
    """No eligible native records means a real empty contract/audit without invented JSON reads."""
    transform, _ = stage(tmp_path, empty=True)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        with pytest.raises(SourceFinalizationRequired, match="has not completed"):
            resolver.contract()
        resolver.finish(transform.output_dir)
        assert resolver.contract()["eligible_record_count"] == 0
        assert aliases.JSON_ROLE not in transform.consumed_input_snapshots
        assert resolver.resolve("NCBITaxon:2") == "NCBITaxon:2"
        with pytest.raises(SourceFinalizationRequired, match="outside the read native cohort"):
            resolver.resolve("NCBITaxon:53360")
        saved = report(transform, resolver)
    aliases.restore_recorded(saved, transform.output_dir / "source_finalization.json").verify()


@pytest.mark.parametrize("mutation", ["new_record", "missing_record", "name", "xref", "incident", "taxon", "duplicate"])
def test_native_cohort_change_aborts_before_any_audit_write(tmp_path, mutation):
    """The finite exception cannot silently grow, shrink or change source observation meaning."""
    transform, evidence = stage(tmp_path)
    nodes = evidence["native_taxon_nodes"] + evidence["native_records"]
    edges = evidence["native_incident_rows"]
    if mutation == "new_record":
        nodes.append({**evidence["native_records"][0], "id": "gold:GoNEW"})
        parent = next(row for row in edges if row["predicate"] == "biolink:in_taxon")
        edges.append({**parent, "subject": "gold:GoNEW"})
    elif mutation == "missing_record":
        nodes.remove(evidence["native_records"][0])
    elif mutation in {"name", "xref"}:
        evidence["native_records"][0][mutation] = "invented"
    elif mutation == "incident":
        edges[0]["relation"] = "invented"
    elif mutation == "taxon":
        next(row for row in edges if row["predicate"] == "biolink:in_taxon")["object"] = "NCBITaxon:2"
    else:
        nodes.append(nodes[0])
    write_rows(transform.input_base_dir / "gold/GOLD_nodes.tsv", nodes, list(nodes[0]))
    write_rows(transform.input_base_dir / "gold/GOLD_edges.tsv", edges, list(edges[0]))
    with ExitStack() as stack, pytest.raises(SourceFinalizationRequired):
        prepare(transform, stack)
    assert not (transform.output_dir / aliases.AUDIT_FILE).exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "live_old",
        "ambiguous",
        "duplicate_alias",
        "deprecated",
        "missing_class",
        "missing_alias",
        "target_metadata",
        "target_cycle",
    ],
)
def test_selected_native_authority_negative_controls(tmp_path, mutation):
    """Neither a plausible name nor altered native claims may substitute for the reviewed witness."""
    transform, _ = stage(tmp_path)
    path = transform.input_base_dir / "ncbitaxon_removed_subset.json"
    payload = json.loads(path.read_text())
    nodes = payload["graphs"][0]["nodes"]
    target = next(node for node in nodes if node["id"].endswith("_53362"))
    assertion = next(prop for prop in target["meta"]["basicPropertyValues"] if prop["pred"] == aliases.ALT)
    if mutation == "live_old":
        nodes.append({"id": "http://purl.obolibrary.org/obo/NCBITaxon_53360", "type": "CLASS"})
    elif mutation == "ambiguous":
        nodes.append(
            {
                "id": "http://purl.obolibrary.org/obo/NCBITaxon_2",
                "type": "CLASS",
                "meta": {"basicPropertyValues": [assertion]},
            }
        )
    elif mutation == "duplicate_alias":
        target["meta"]["basicPropertyValues"].append(assertion)
    elif mutation == "deprecated":
        target["meta"]["deprecated"] = True
    elif mutation == "missing_class":
        target["type"] = "PROPERTY"
    elif mutation == "missing_alias":
        target["meta"]["basicPropertyValues"].remove(assertion)
    elif mutation == "target_metadata":
        target["lbl"] += " altered"
    else:
        nodes.append(
            {
                "id": "http://purl.obolibrary.org/obo/NCBITaxon_2",
                "type": "CLASS",
                "meta": {"basicPropertyValues": [{"pred": aliases.ALT, "val": "NCBITaxon:53362"}]},
            }
        )
    path.write_text(json.dumps(payload))
    with ExitStack() as stack, pytest.raises(SourceFinalizationRequired):
        prepare(transform, stack)


@pytest.mark.parametrize(
    "mutation", ["conflict", "cycle", "terminal_merge", "wrong_member", "duplicate_member", "missing"]
)
def test_taxdump_chain_negative_controls(tmp_path, mutation):
    """The reviewed convergence is not a blanket priority rule over contradictory taxdump evidence."""
    transform, evidence = stage(tmp_path)
    path = transform.input_base_dir / "taxdump.tar.gz"
    literal = "".join(item["literal"] for item in evidence["taxdump_merged_dmp"])
    if mutation == "conflict":
        literal += "53360\t|\t2\t|\n"
    elif mutation == "cycle":
        literal += "36030\t|\t1194211\t|\n"
    elif mutation == "terminal_merge":
        literal += "4927\t|\t2\t|\n"
    if mutation == "missing":
        path.unlink()
    else:
        write_taxdump(
            path,
            literal,
            member="wrong/merged.dmp" if mutation == "wrong_member" else "merged.dmp",
            duplicate=mutation == "duplicate_member",
        )
    with ExitStack() as stack, pytest.raises(SourceFinalizationRequired):
        prepare(transform, stack)


@pytest.mark.parametrize("mutation", ["missing", "category", "name", "deprecated", "old", "duplicate"])
def test_selected_sibling_negative_controls(tmp_path, mutation):
    """A full-ontology target without its consistent selected declaration is not eligible."""
    transform, evidence = stage(tmp_path)
    rows = evidence["projected_nodes"]
    target = next(row for row in rows if row["id"] == "NCBITaxon:53362")
    if mutation == "missing":
        rows.remove(target)
    elif mutation in {"category", "name", "deprecated"}:
        target[mutation] = "invalid"
    elif mutation == "old":
        rows.append({**target, "id": "NCBITaxon:53360"})
    else:
        rows.append(target)
    write_rows(transform.output_base_dir / "ontologies/ncbitaxon_nodes.tsv", rows, list(target))
    with ExitStack() as stack, pytest.raises(SourceFinalizationRequired):
        prepare(transform, stack)


@pytest.mark.parametrize(
    "role",
    [
        aliases.POLICY_ROLE,
        aliases.JSON_ROLE,
        aliases.NODES_ROLE,
        aliases.EDGES_ROLE,
        aliases.NCBI_ROLE,
        aliases.TAXDUMP_ROLE,
    ],
)
def test_original_live_roles_are_mandatory_and_failure_sticky(tmp_path, role):
    """Restoring a removed role after a failed checkpoint must not certify the same run."""
    transform, _ = stage(tmp_path)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        original = transform._consumed_input_snapshots.pop(role)
        with pytest.raises(SourceFinalizationRequired):
            resolver.verify(metadata_only=True)
        transform._consumed_input_snapshots[role] = original
        with pytest.raises(SourceFinalizationRequired):
            resolver.finish(transform.output_dir)


@pytest.mark.parametrize("field", ["_baseline", "_targets", "_evidence", "_audit_bytes", "_contract_json"])
def test_parsed_cache_mutation_rejected(tmp_path, field):
    """Parsed caches cannot replace the actual native witness, even coherently."""
    transform, _ = stage(tmp_path)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        previous = getattr(resolver, field)
        setattr(resolver, field, b"" if field == "_audit_bytes" else "{}")
        with pytest.raises(SourceFinalizationRequired):
            resolver.resolve("NCBITaxon:53360")
        setattr(resolver, field, previous)
        with pytest.raises(SourceFinalizationRequired):
            resolver.verify(metadata_only=True)


@pytest.mark.parametrize(
    "mutation", ["contract", "false_zero", "role", "rebound_role", "audit", "audit_row", "raw_node"]
)
def test_recorded_rejoin_rejects_missing_or_coherently_forged_contract(tmp_path, mutation):
    """Actual native scope controls admission, not an empty or forged saved receipt."""
    transform, _ = stage(tmp_path)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        resolver.finish(transform.output_dir)
        saved = report(transform, resolver)
    if mutation == "contract":
        saved["producer_native_inputs"].clear()
    elif mutation == "false_zero":
        saved["producer_native_inputs"][aliases.CONTRACT_KEY]["eligible_original_ids"] = []
    elif mutation == "role":
        saved["consumed_inputs"].pop(aliases.JSON_ROLE)
    elif mutation == "rebound_role":
        saved["consumed_inputs"][aliases.JSON_ROLE] = saved["consumed_inputs"][aliases.NODES_ROLE]
    elif mutation == "audit":
        (transform.output_dir / aliases.AUDIT_FILE).unlink()
    elif mutation == "audit_row":
        path = transform.output_dir / aliases.AUDIT_FILE
        path.write_text(path.read_text().replace("Dactylosporangium", "invented"))
    else:
        path = transform.input_base_dir / "gold/GOLD_nodes.tsv"
        path.write_text(path.read_text().replace("Dactylosporangium", "invented"))
    with pytest.raises(SourceFinalizationRequired):
        aliases.restore_recorded(saved, transform.output_dir / "source_finalization.json")


@pytest.mark.parametrize("mutation", ["contract", "role", "native", "audit", "symlink"])
def test_retained_recorded_admission_guards_late_publication(tmp_path, mutation):
    """Keep native role/locator/contract/audit observations active after initial admission."""
    transform, _ = stage(tmp_path)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        resolver.finish(transform.output_dir)
        saved = report(transform, resolver)
    admission = SourceAdmission()
    aliases.restore_recorded(saved, transform.output_dir / "source_finalization.json", admission=admission)
    if mutation == "contract":
        saved["producer_native_inputs"].clear()
    elif mutation == "role":
        saved["consumed_inputs"].pop(aliases.NCBI_ROLE)
    elif mutation == "native":
        with (transform.input_base_dir / "gold/GOLD_nodes.tsv").open("a") as stream:
            stream.write("\n")
    elif mutation == "audit":
        (transform.output_dir / aliases.AUDIT_FILE).write_text("forged")
    else:
        path = transform.input_base_dir / "ncbitaxon_removed_subset.json"
        alternate = path.with_name("other.json")
        path.rename(alternate)
        path.symlink_to(alternate)
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)


def test_supplied_private_snapshot_cannot_replace_consumed_original(tmp_path):
    """Existing role receipts do not authorize a caller-supplied different payload."""
    transform, _ = stage(tmp_path)
    with ExitStack() as stack:
        locators = aliases._locators(transform.input_base_dir, transform.output_base_dir)
        paths = {
            role: Path(stack.enter_context(transform.consume_input(role, locators[role])).name)
            for role in (aliases.NODES_ROLE, aliases.EDGES_ROLE, aliases.NCBI_ROLE, aliases.TAXDUMP_ROLE)
        }
        false_nodes = tmp_path / "false_nodes.tsv"
        false_nodes.write_text("id\tcategory\tname\n")
        with pytest.raises(SourceFinalizationRequired, match="supplied snapshot differs"):
            aliases.prepare(
                transform,
                stack,
                false_nodes,
                paths[aliases.EDGES_ROLE],
                paths[aliases.NCBI_ROLE],
                paths[aliases.TAXDUMP_ROLE],
            )


def test_evidence_and_contract_accessors_are_independent_copies(tmp_path):
    """Callers can inspect evidence without gaining a mutable native cache reference."""
    transform, _ = stage(tmp_path)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        resolver.finish(transform.output_dir)
        original = copy.deepcopy(resolver.evidence_for("NCBITaxon:53360"))
        changed = resolver.evidence_for("NCBITaxon:53360")
        changed["selected_target"] = "NCBITaxon:2"
        resolver.contract()["eligible_original_ids"].clear()
        assert resolver.evidence_for("NCBITaxon:53360") == original
        assert resolver.resolve("NCBITaxon:53360") == "NCBITaxon:53362"


def test_policy_complete_cohort_anchor_cannot_be_erased(tmp_path, monkeypatch):
    """Policy consumption is real and an empty policy does not waive finite membership."""
    transform, _ = stage(tmp_path)
    policy = json.loads(aliases.POLICY_PATH.read_text())
    policy["rules"].clear()
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    monkeypatch.setattr(aliases, "POLICY_PATH", path)
    with ExitStack() as stack, pytest.raises(SourceFinalizationRequired, match="policy changed"):
        prepare(transform, stack)


def test_private_snapshot_mutation_during_parse_rejected(tmp_path, monkeypatch):
    """Check the exact transient parse files again before trusting their cached evidence."""
    transform, _ = stage(tmp_path)
    original = aliases._cohort

    def changed(nodes, edges, policy):
        """Mutate the private native snapshot while the parser is using it."""
        result = original(nodes, edges, policy)
        with Path(nodes).open("a") as stream:
            stream.write("\n")
        return result

    monkeypatch.setattr(aliases, "_cohort", changed)
    with ExitStack() as stack, pytest.raises(SourceFinalizationRequired):
        prepare(transform, stack)


@pytest.mark.parametrize("field", ["contract", "role"])
def test_external_admission_failure_stays_failed_after_receipt_restore(tmp_path, field):
    """A retained raw SourceAdmission cannot be healed by restoring a forged receipt."""
    transform, _ = stage(tmp_path)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        resolver.finish(transform.output_dir)
        saved = report(transform, resolver)
    admission = SourceAdmission()
    aliases.restore_recorded(saved, transform.output_dir / "source_finalization.json", admission=admission)
    container = saved["producer_native_inputs"] if field == "contract" else saved["consumed_inputs"]
    key = aliases.CONTRACT_KEY if field == "contract" else aliases.JSON_ROLE
    original = container.pop(key)
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)
    container[key] = original
    with pytest.raises(SourceFinalizationRequired):
        admission.verify(metadata_only=True)


def test_unrelated_taxdump_behavior_is_not_broadened_to_selected_aliases(tmp_path):
    """Preserve baseline remaps while declining any unreviewed selected-ontology alias policy."""
    transform, evidence = stage(tmp_path)
    literal = "".join(item["literal"] for item in evidence["taxdump_merged_dmp"])
    write_taxdump(transform.input_base_dir / "taxdump.tar.gz", literal + "7777\t|\t8888\t|\n")
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        assert resolver.resolve("NCBITaxon:7777") == "NCBITaxon:8888"
        assert resolver.evidence_for("NCBITaxon:7777") is None
        assert resolver.resolve("NCBITaxon:8888") == "NCBITaxon:8888"


@pytest.mark.parametrize("role", [aliases.NCBI_ROLE, aliases.TAXDUMP_ROLE, aliases.JSON_ROLE])
@pytest.mark.parametrize("route", ["live", "supplied", "recorded", "late_recorded"])
def test_originally_absent_roles_cannot_be_added_at_any_checkpoint(tmp_path, role, route):
    """A genuine empty native cohort cannot gain invented authority-read claims (#1333)."""
    transform, _ = stage(tmp_path, empty=True)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        resolver.finish(transform.output_dir)
        saved = report(transform, resolver)
    admission = SourceAdmission()
    if route == "late_recorded":
        aliases.restore_recorded(saved, transform.output_dir / "source_finalization.json", admission=admission)
    current = (
        transform._consumed_input_snapshots
        if route == "live"
        else copy.deepcopy(transform.consumed_input_snapshots)
        if route == "supplied"
        else saved["consumed_inputs"]
    )
    assert role not in current
    current[role] = dict(current[aliases.POLICY_ROLE])

    def checkpoint():
        """Exercise the selected lifecycle checkpoint after adding an absent role."""
        if route == "live":
            resolver.verify(metadata_only=True)
        elif route == "supplied":
            resolver.verify(current, metadata_only=True)
        elif route == "recorded":
            aliases.restore_recorded(saved, transform.output_dir / "source_finalization.json")
        else:
            admission.verify(metadata_only=True)

    with pytest.raises(SourceFinalizationRequired):
        checkpoint()
    current.pop(role)
    if route != "recorded":
        with pytest.raises(SourceFinalizationRequired):
            checkpoint()


def test_unrelated_consumer_roles_remain_permitted(tmp_path):
    """Finite-role integrity does not prohibit other real readers in the same producer."""
    transform, _ = stage(tmp_path, empty=True)
    with ExitStack() as stack:
        resolver = prepare(transform, stack)
        with transform.consume_input("other_reader", aliases.POLICY_PATH) as stream:
            assert stream.read()
        resolver.finish(transform.output_dir)
        saved = report(transform, resolver)
    admission = SourceAdmission()
    aliases.restore_recorded(saved, transform.output_dir / "source_finalization.json", admission=admission)
    admission.verify()


@pytest.mark.parametrize("key", ["type", "escaped_type", "same_type", "id", "meta", "graphs", "nodes", "pred"])
def test_duplicate_native_object_keys_abort_before_last_key_wins(tmp_path, key):
    """Preserve all native evidence, including structural/nested/escaped contradictions (#1334)."""
    transform, _ = stage(tmp_path)
    path = transform.input_base_dir / "ncbitaxon_removed_subset.json"
    original = path.read_text()
    substitutions = {
        "type": ('"type": "CLASS"', '"type": "PROPERTY", "type": "CLASS"'),
        "escaped_type": ('"type": "CLASS"', '"t\\u0079pe": "PROPERTY", "type": "CLASS"'),
        "same_type": ('"type": "CLASS"', '"type": "CLASS", "type": "CLASS"'),
        "id": ('"id":', '"id": "NCBITaxon:invented", "id":'),
        "meta": ('"meta":', '"meta": {"deprecated": true}, "meta":'),
        "graphs": ('"graphs":', '"graphs": [], "graphs":'),
        "nodes": ('"nodes":', '"nodes": [], "nodes":'),
        "pred": ('"pred":', '"pred": "contradiction", "pred":'),
    }
    old, new = substitutions[key]
    assert old in original
    changed = original.replace(old, new, 1)
    assert json.loads(changed) == json.loads(original)
    path.write_text(changed)
    with ExitStack() as stack, pytest.raises(SourceFinalizationRequired, match="duplicate JSON object key"):
        prepare(transform, stack)
    assert not (transform.output_dir / aliases.AUDIT_FILE).exists()


def test_duplicate_policy_key_cannot_hide_changed_reviewed_scope(tmp_path, monkeypatch):
    """The small policy also refuses discarded duplicate-key evidence before its semantic hash."""
    transform, _ = stage(tmp_path, empty=True)
    original = aliases.POLICY_PATH.read_text()
    changed = original.replace('"rules":', '"rules": [], "rules":', 1)
    assert changed != original and json.loads(changed) == json.loads(original)
    path = tmp_path / "policy.json"
    path.write_text(changed)
    monkeypatch.setattr(aliases, "POLICY_PATH", path)
    with ExitStack() as stack, pytest.raises(SourceFinalizationRequired, match="duplicate JSON object key"):
        prepare(transform, stack)
