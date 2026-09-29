"""Adversarial negative witnesses must never silently authorize quarantine."""

import base64
import gzip
import hashlib
import json

import pytest

from kg_microbe.transform_utils.microbedecoder.crosswalk_quarantine import QuarantinePolicy
from kg_microbe.transform_utils.microbedecoder.crosswalk_witnesses import WitnessObjects
from tests.microbedecoder_quarantine_fixtures import write_fixture_quarantine_policy
from tests.test_microbedecoder_crosswalk_quarantine import _load, _preflight, _source


def _edit_evidence(policy_path, change):
    policy = json.loads(policy_path.read_text())
    path = policy_path.parent / policy["evidence_file"]
    evidence = json.loads(path.read_text())
    change(evidence)
    path.write_text(json.dumps(evidence))
    policy["evidence_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    policy_path.write_text(json.dumps(policy))


def _mutate_witness(evidence, mutation):
    witness = next(iter(evidence["witnesses"].values()))
    context = witness["context"]
    support = context["bacdive_support"]
    target = witness["target"]
    if mutation == "classification_only":
        witness.pop("context")
    elif mutation == "no_explicit_bacdive_taxid":
        support["record"]["General"].pop("NCBI tax id")
    elif mutation == "wrong_bacdive_taxid":
        support["record"]["General"]["NCBI tax id"]["NCBI tax id"] = 1352
    elif mutation == "not_type_strain":
        support["record"]["Name and taxonomic classification"]["type strain"] = "no"
    elif mutation == "wrong_bacdive_lpsn":
        support["lpsn_edges"][0]["object"] = "lpsn:102"
    elif mutation == "wrong_bacdive_name":
        support["record"]["Name and taxonomic classification"]["LPSN"]["species"] = "Other species"
    elif mutation == "name_chain_ambiguous":
        witness["bacdive_name_authority"]["accepted_chains"][0][-1]["record_no"] = "102"
    elif mutation == "broken_source_lpsn_chain":
        context["gss_chain"][0]["record_no"] = "102"
    elif mutation == "wrong_lpsn_provenance":
        context["lpsn_expectation"]["crosswalk"]["primary_knowledge_source"] = "infores:microbedecoder"
    elif mutation == "broken_lpsn_path":
        context["lpsn_expectation"]["via"] = "lpsn:999"
    elif mutation == "unrelated_bacdive_native":
        support["native_explicit_taxa"][0]["input"] = "NCBITaxon:999"
    elif mutation == "not_cross_phylum":
        target["phylum"] = context["lpsn_expectation"]["native"]["phylum"]
    elif mutation == "native_name_agreement":
        target["nodes"][0]["name"] = "Synthetic species"
    elif mutation == "native_synonym_agreement":
        target["nodes"][0]["synonym"] = "SYNTHETIC species"
    elif mutation == "native_deprecated":
        target["nodes"][0]["deprecated"] = "true"
    elif mutation == "native_unlabelled":
        target["nodes"][0]["name"] = " "
    elif mutation == "native_wrong_category":
        target["nodes"][0]["category"] = "biolink:ChemicalEntity"
    elif mutation == "native_wrong_provider":
        target["nodes"][0]["provided_by"] = "infores:microbedecoder"
    elif mutation == "native_incomplete_root":
        target["nodes"].pop()
        target["edges"].pop()
    elif mutation == "native_broken_edge":
        target["edges"][0]["object"] = "NCBITaxon:999"
    elif mutation == "native_wrong_edge_tier":
        target["edges"][0]["knowledge_level"] = "prediction"
    elif mutation == "false_rank":
        evidence["taxonomy_rank_witnesses"][target["genus"]]["rank"] = "species"
    elif mutation == "missing_raw_rank":
        evidence["taxonomy_rank_witnesses"].pop(target["genus"])
    elif mutation == "raw_rank_false_bytes":
        evidence["taxonomy_rank_witnesses"][target["genus"]]["raw_line_base64"] = "eAo="
    elif mutation == "unwitnessed_alias":
        target["aliases"] = [{"original": target["input"], "replacement": target["resolved"]}]
    elif mutation in {"retired_self_cycle", "retired_two_hop_cycle"}:
        original = target["input"]
        pairs = [(original, original)]
        if mutation == "retired_two_hop_cycle":
            pairs = [(original, "NCBITaxon:999"), ("NCBITaxon:999", original)]
        target["aliases"] = [{"original": old, "replacement": new} for old, new in pairs]
        for ordinal, (old, new) in enumerate(pairs, 1):
            raw = f"{old.split(':')[1]}\t|\t{new.split(':')[1]}\t|\n".encode("ascii")
            evidence["retired_taxid_witnesses"][old] = {
                "authority_id": "taxdump",
                "member": "merged.dmp",
                "line_ordinal": ordinal,
                "raw_line_base64": base64.b64encode(raw).decode("ascii"),
                "replacement": new,
            }
    elif mutation == "lpsn_cycle_closes_at_subject":
        expected = context["lpsn_expectation"]
        subject = expected["via"]
        template = {**target["edges"][0], "primary_knowledge_source": "infores:lpsn"}
        expected["parent_edges"] = [
            {**template, "subject": subject, "object": "lpsn:999"},
            {**template, "subject": "lpsn:999", "object": subject},
        ]
    elif mutation == "phylum_below_genus":
        target["nodes"][1], target["nodes"][2] = target["nodes"][2], target["nodes"][1]
        ids = [node["id"] for node in target["nodes"]]
        template = target["edges"][0]
        target["edges"] = [
            {**template, "subject": subject, "object": parent}
            for subject, parent in zip(ids[:-1], ids[1:], strict=True)
        ]
    elif mutation == "missing_authority":
        evidence["authorities"].pop("bacdive_raw")
    elif mutation == "bad_original_claim":
        witness["original_emitted_edge"]["object"] = "NCBITaxon:999"
    elif mutation == "bad_original_claim_tier":
        witness["original_emitted_edge"]["knowledge_level"] = "prediction"
    else:
        raise AssertionError(mutation)


@pytest.mark.parametrize(
    "mutation",
    [
        "classification_only",
        "no_explicit_bacdive_taxid",
        "wrong_bacdive_taxid",
        "not_type_strain",
        "wrong_bacdive_lpsn",
        "wrong_bacdive_name",
        "name_chain_ambiguous",
        "broken_source_lpsn_chain",
        "wrong_lpsn_provenance",
        "broken_lpsn_path",
        "unrelated_bacdive_native",
        "not_cross_phylum",
        "native_name_agreement",
        "native_synonym_agreement",
        "native_deprecated",
        "native_unlabelled",
        "native_wrong_category",
        "native_wrong_provider",
        "native_incomplete_root",
        "native_broken_edge",
        "native_wrong_edge_tier",
        "false_rank",
        "missing_raw_rank",
        "raw_rank_false_bytes",
        "unwitnessed_alias",
        "retired_self_cycle",
        "retired_two_hop_cycle",
        "lpsn_cycle_closes_at_subject",
        "phylum_below_genus",
        "missing_authority",
        "bad_original_claim",
        "bad_original_claim_tier",
    ],
)
def test_rejected_native_or_independent_witnesses(tmp_path, mutation):
    """Even deliberately repinned malformed evidence fails scientific contract checks."""
    raw = _source(tmp_path)
    policy = write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")])
    _edit_evidence(policy, lambda evidence: _mutate_witness(evidence, mutation))
    with pytest.raises(ValueError):
        _load(policy)


@pytest.mark.parametrize("mutation", ["raw_target", "raw_xref", "fold_target", "native_edge", "native_provider"])
def test_gold_requires_original_raw_and_native_chain(tmp_path, mutation):
    """A reused or folded GOLD ID must still match explicit original source evidence."""
    raw = _source(tmp_path)
    policy = write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "GOLD_Organism_ID")])

    def change(evidence):
        """Corrupt one independent GOLD witness while retaining its outer pin."""
        gold = next(iter(evidence["witnesses"].values()))["gold"]
        if mutation == "raw_target":
            gold["raw_edge"]["object"] = "NCBITaxon:999"
        elif mutation == "raw_xref":
            gold["raw_node"]["xref"] = "NCBITaxon:999"
        elif mutation == "fold_target":
            gold["fold_target"] = "NCBITaxon:999"
        elif mutation == "native_edge":
            gold["native_edges"] = []
        else:
            gold["native_node"]["provided_by"] = "infores:microbedecoder"

    _edit_evidence(policy, change)
    with pytest.raises(ValueError):
        _load(policy)


def test_content_addressed_objects_reject_missing_wrong_and_cyclic_references():
    """Shared evidence is lossless and cannot hide broken object references."""
    value = {"preserved": [1, "all values"]}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    objects = WitnessObjects({digest: value})
    assert objects.expand({"$ref": digest}) == value
    assert objects.expand({"$ref": digest}) is objects.expand({"$ref": digest})
    for pool, ref in [({}, digest), ({digest: ["changed"]}, digest), ({digest: {"$ref": digest}}, digest)]:
        with pytest.raises(ValueError):
            WitnessObjects(pool).expand({"$ref": ref})
    with pytest.raises(ValueError, match="mixed reference"):
        objects.expand({"$ref": digest, "ignored": "bad"})


def _two_hop_lpsn_authority(evidence):
    """Build a valid declared species-to-genus authority path with one intermediate."""
    witness = next(iter(evidence["witnesses"].values()))
    expected = witness["context"]["lpsn_expectation"]
    source = expected["via"]
    expected["via"] = "lpsn:103"
    expected["lpsn_nodes"] = [
        {**expected["lpsn_nodes"][0], "id": identifier} for identifier in (source, "lpsn:102", "lpsn:103")
    ]
    template = {**witness["target"]["edges"][0], "primary_knowledge_source": "infores:lpsn"}
    expected["parent_edges"] = [
        {**template, "subject": source, "object": "lpsn:102"},
        {**template, "subject": "lpsn:102", "object": "lpsn:103"},
    ]
    native = expected["native"]
    native["nodes"].pop(0)
    native["edges"].pop(0)
    native["input"] = native["resolved"] = native["genus"]
    expected["crosswalk"].update(subject="lpsn:103", object=native["input"])
    return expected


@pytest.mark.parametrize("damage", [None, "missing", "deprecated", "provider", "conflicting", "unexpected"])
def test_every_lpsn_ancestor_requires_its_own_active_declaration(tmp_path, damage):
    """Endpoints do not stand in for the declarations of intermediate authority taxa."""
    raw = _source(tmp_path)
    policy = write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")])

    def change(evidence):
        """Alter declarations on an otherwise valid multi-hop LPSN authority path."""
        expected = _two_hop_lpsn_authority(evidence)
        nodes = expected["lpsn_nodes"]
        if damage == "missing":
            nodes.pop(1)
        elif damage == "deprecated":
            nodes[1]["deprecated"] = "true"
        elif damage == "provider":
            nodes[1]["provided_by"] = "infores:microbedecoder"
        elif damage == "conflicting":
            nodes.insert(1, {**nodes[1], "name": "Contradictory declaration"})
        elif damage == "unexpected":
            nodes.insert(1, {**nodes[1], "id": "lpsn:999"})

    _edit_evidence(policy, change)
    if damage is None:
        _load(policy)
    else:
        with pytest.raises(ValueError, match="LPSN|native"):
            _load(policy)


def test_identical_endpoint_declarations_for_zero_hop_authority_remain_valid(tmp_path):
    """Historical evidence repeats the same subject/via declaration for direct crosswalks."""
    raw = _source(tmp_path)
    policy = write_fixture_quarantine_policy(raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")])

    def change(evidence):
        """Repeat the unchanged declaration used as both direct-path endpoints."""
        expected = next(iter(evidence["witnesses"].values()))["context"]["lpsn_expectation"]
        expected["lpsn_nodes"].append(dict(expected["lpsn_nodes"][0]))

    _edit_evidence(policy, change)
    _load(policy)


def test_compressed_policy_uses_both_exact_pins_and_real_binary_snapshot(tmp_path):
    """The same source policy works through path and producer-owned binary-backed readers."""
    raw = _source(tmp_path)
    policy_path = write_fixture_quarantine_policy(
        raw, tmp_path / "policy", selected=[(1, "NCBI_Taxonomy_ID")], canonical_names=True
    )
    quarantine = _load(policy_path)
    assert _preflight(quarantine, raw)
    assert quarantine.policy.evidence_uncompressed_bytes > 0


@pytest.mark.parametrize(
    "mutation",
    [
        "compressed_sha",
        "decoded_sha",
        "decoded_short",
        "decoded_long",
        "too_large",
        "boolean_size",
        "missing_pin",
        "crc",
    ],
)
def test_compressed_evidence_corruption_fails_before_json_admission(tmp_path, mutation):
    """Bound decompression and require compressed hash, decoded hash/length and gzip CRC."""
    raw = _source(tmp_path)
    policy_path = write_fixture_quarantine_policy(raw, tmp_path / "policy", canonical_names=True)
    policy = json.loads(policy_path.read_text())
    evidence = policy_path.parent / policy["evidence_file"]
    if mutation == "compressed_sha":
        policy["evidence_sha256"] = "f" * 64
    elif mutation == "decoded_sha":
        policy["evidence_uncompressed_sha256"] = "f" * 64
    elif mutation == "decoded_short":
        policy["evidence_uncompressed_bytes"] -= 1
    elif mutation == "decoded_long":
        policy["evidence_uncompressed_bytes"] += 1
    elif mutation == "too_large":
        policy["evidence_uncompressed_bytes"] = 256 * 1024 * 1024 + 1
    elif mutation == "boolean_size":
        policy["evidence_uncompressed_bytes"] = True
    elif mutation == "missing_pin":
        policy.pop("evidence_uncompressed_sha256")
    else:
        payload = bytearray(evidence.read_bytes())
        payload[-8] ^= 1
        evidence.write_bytes(payload)
        policy["evidence_sha256"] = hashlib.sha256(payload).hexdigest()
    policy_path.write_text(json.dumps(policy))
    with pytest.raises((ValueError, gzip.BadGzipFile)):
        _load(policy_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("source_records", True),
        ("decisions_file", "../escape.tsv"),
        ("evidence_file", "/absolute.json"),
    ],
)
def test_policy_shape_and_safe_sibling_paths(tmp_path, field, value):
    """No path traversal, permissive bool counts or unknown policy versions."""
    raw = _source(tmp_path)
    policy_path = write_fixture_quarantine_policy(raw, tmp_path / "policy")
    policy = json.loads(policy_path.read_text())
    policy[field] = value
    policy_path.write_text(json.dumps(policy))
    with pytest.raises(ValueError):
        QuarantinePolicy.load(policy_path)
