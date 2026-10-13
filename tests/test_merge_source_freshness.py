"""The public merge gate rejects stale prepared dependencies before KGX (#1092)."""

import gzip
import hashlib
import inspect
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml
from click.testing import CliRunner

from kg_microbe.merge_utils import merge_kg
from kg_microbe.run import main
from kg_microbe.transform import DATA_SOURCES
from kg_microbe.transform_utils.bacdive import (
    clinical_categories,
    ec_substrate_corrections,
    isolation_categories,
    ncit_category_claims,
    supplied_taxid_policy,
    taxonomy_evidence,
)
from kg_microbe.transform_utils.constants import DATA_KEY
from kg_microbe.transform_utils.madin_etal.madin_etal import (
    ENVIRONMENT_ID_CORRECTIONS_FILE,
    _apply_environment_id_corrections,
)
from kg_microbe.transform_utils.mediadive.bulk_inputs import load_bulk_payload
from kg_microbe.transform_utils.mediadive.material_scope_audit import (
    AUDIT_FILENAME,
    AUDIT_HEADER,
    POLICY_ROLE,
    REVIEWED_ROLE,
    MaterialScopeAudit,
)
from kg_microbe.transform_utils.mediadive.recipe_identity import (
    EVIDENCE_ROLE as RECIPE_EVIDENCE_ROLE,
)
from kg_microbe.transform_utils.mediadive.recipe_identity import (
    POLICY_ROLE as RECIPE_POLICY_ROLE,
)
from kg_microbe.transform_utils.mediadive.recipe_identity import RecipeIdentityGuard
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.ingredient_context import (
    CONTEXT_ROLE as INGREDIENT_CONTEXT_ROLE,
)
from kg_microbe.utils.ingredient_context import (
    HISTORICAL_ROLE as CATALASE_HISTORICAL_ROLE,
)
from kg_microbe.utils.ingredient_context import (
    NATIVE_ROLE as INGREDIENT_NATIVE_ROLE,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, verify_finalized_source_files
from kg_microbe.utils.transform_fingerprint import upstream_fingerprint, write_fingerprint
from kg_microbe.utils.tsv_io import tsv_dict_writer, tsv_writer
from tests.gold_fixtures import prepare_empty_gold_crosswalk_inputs
from tests.native_ro_fixtures import prepare_empty_native_ro_contract
from tests.prego_identity_fixtures import IDENTITY_FIXTURES, prepare_prego_empty_archive_inputs
from tests.rhea_fixtures import prepare_rhea_native_inputs

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "resources/merge_source_freshness"
pytestmark = pytest.mark.usefixtures("local_source_schema")


def read_mediadive_bulk_inputs(transform, *, create=False):
    """Read all five immutable JSON fixtures through the real required-input protocol."""
    paths = {
        "mediadive_media_list": "mediadive.json",
        "mediadive_media_detailed": "mediadive/media_detailed.json",
        "mediadive_media_strains": "mediadive/media_strains.json",
        "mediadive_solutions": "mediadive/solutions.json",
        "mediadive_compounds": "mediadive/compounds.json",
    }
    payloads = json.loads((FIXTURES.parent / "mediadive_bulk_inputs.json").read_text())
    # Create the whole fixture before retaining any input/optional-directory guards.
    # A restarted read epoch below reuses these exact files without rewriting them.
    if create:
        for role, relative in paths.items():
            path = transform.input_base_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(json.dumps(payloads[role], sort_keys=True) + "\n")
    loaded = {}
    for role, relative in paths.items():
        loaded[role] = load_bulk_payload(transform, role, transform.input_base_dir / relative)
        assert loaded[role] == payloads[role]
    assert payloads["mediadive_media_list"][DATA_KEY] == []
    transform.media_detailed = loaded["mediadive_media_detailed"]
    transform.media_strains = loaded["mediadive_media_strains"]
    transform.solutions_data = loaded["mediadive_solutions"]
    transform.compounds_data = loaded["mediadive_compounds"]
    transform._material_scope_audit = MaterialScopeAudit(transform, loaded["mediadive_media_list"])
    transform._recipe_identity_guard = RecipeIdentityGuard(transform, loaded["mediadive_media_list"])
    transform._recipe_identity_prepared = True
    assert transform._recipe_identity_guard.index["occurrences"] == {}
    return (
        *paths,
        REVIEWED_ROLE,
        POLICY_ROLE,
        INGREDIENT_CONTEXT_ROLE,
        INGREDIENT_NATIVE_ROLE,
        CATALASE_HISTORICAL_ROLE,
        RECIPE_POLICY_ROLE,
        RECIPE_EVIDENCE_ROLE,
    )


def write_empty_mediadive_audit(transform):
    """Run the actual audit writer only for the consumed immutable zero-cohort fixture."""
    payloads = json.loads((FIXTURES.parent / "mediadive_bulk_inputs.json").read_text())
    media_list = load_bulk_payload(transform, "mediadive_media_list", transform.input_base_dir / "mediadive.json")
    assert media_list == payloads["mediadive_media_list"]
    assert media_list[DATA_KEY] == [], "Nonempty media require the actual producer's occurrence processing"
    transform._material_scope_audit = MaterialScopeAudit(transform, media_list)
    transform._material_scope_audit.write()
    assert transform._recipe_identity_guard.index["occurrences"] == {}
    transform._recipe_identity_guard.write()


def prepare_bacdive_ec_correction_inputs(transform):
    """Bind a zero-cohort fixture through real policy/read/audit contracts, without claiming a producer run."""
    isolation_categories.prepare_policy(transform)
    native_mesh = transform.input_base_dir / "mesh2026.nt.gz"
    excerpt = FIXTURES.parent / "bacdive_clinical_mesh/mesh2026-clinical-excerpt.nt"
    expected = gzip.compress(excerpt.read_bytes(), mtime=0)
    if not native_mesh.exists():
        native_mesh.write_bytes(expected)
    assert native_mesh.read_bytes() == expected, "Do not replace an already selected native authority"
    clinical_categories.prepare_policy(transform)
    raw = transform.input_base_dir / "bacdive_strains.json"
    empty = FIXTURES / "bacdive_empty_records.json"
    if not raw.exists():
        shutil.copyfile(empty, raw)
    assert raw.read_bytes() == empty.read_bytes(), "Nonempty native records require actual producer emission"
    taxonomy_guard = taxonomy_evidence.prepare(transform)
    claim_guard, native = ncit_category_claims.prepare(
        transform,
        native_observer=lambda payload: taxonomy_guard.capture_native(payload, transform.consumed_input_snapshots),
    )
    assert native == []
    taxonomy_evidence.prepare_fallback(
        transform,
        transform.input_base_dir / "never-read-selected-ncbitaxon.tsv",
        lambda: pytest.fail("empty native source must not select a fallback authority"),
    )
    with (transform.output_dir / isolation_categories.AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        tsv_dict_writer(stream, fieldnames=isolation_categories.AUDIT_FIELDS).writeheader()
    transform.record_producer_audit(isolation_categories.AUDIT_FILE)
    with (transform.output_dir / clinical_categories.AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        tsv_dict_writer(stream, fieldnames=clinical_categories.AUDIT_FIELDS).writeheader()
    transform.record_producer_audit(clinical_categories.AUDIT_FILE)
    with (transform.output_dir / ncit_category_claims.AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        tsv_dict_writer(stream, fieldnames=ncit_category_claims.AUDIT_FIELDS).writeheader()
    transform.record_producer_audit(ncit_category_claims.AUDIT_FILE)
    claim_guard.finish(transform.consumed_input_snapshots)
    claim_guard.mark_output_ready(transform.consumed_input_snapshots)
    transform._ncit_claim_output_ready = True
    resolved, contested = taxonomy_guard.resolve_deposits({})
    assert resolved == [] and contested == []
    with (transform.output_dir / taxonomy_evidence.AUDIT_FILE).open("w", encoding="utf-8", newline="") as stream:
        writer = tsv_writer(stream)
        writer.writerow(taxonomy_evidence.AUDIT_FIELDS)
        taxonomy_guard.complete({}, resolved, contested, writer)
    taxonomy_guard.mark_output_ready(transform.consumed_input_snapshots)
    transform.record_producer_audit(taxonomy_evidence.AUDIT_FILE)
    legacy = transform.input_base_dir / "bacdive_ec_substrates.tsv"
    original = FIXTURES / "bacdive_ec_substrates.tsv"
    if not legacy.exists():
        shutil.copyfile(original, legacy)
    assert legacy.read_bytes() == original.read_bytes()
    transform.knowledge_source = "infores:bacdive"
    rows, audit, admission = ec_substrate_corrections.prepare_corrections(transform, legacy)
    assert rows == [] and audit == [], "Nonempty correction cohorts require the actual producer's graph/audit emission"
    header = (FIXTURES / "ec_substrate_corrections.tsv").read_bytes()
    assert header == ("\t".join(ec_substrate_corrections.AUDIT_FIELDS) + "\n").encode()
    (transform.output_dir / ec_substrate_corrections.AUDIT_FILE).write_bytes(header)
    transform.record_producer_audit(ec_substrate_corrections.AUDIT_FILE)
    admission.verify()
    transform.verify_consumed_inputs()
    return (
        ec_substrate_corrections.REQUIRED_INPUTS
        + isolation_categories.REQUIRED_INPUTS
        + clinical_categories.REQUIRED_INPUTS
        + (supplied_taxid_policy.ROLE,)
        + ncit_category_claims.REQUIRED_INPUTS
        + (isolation_categories.RAW_INPUT,)
    )


def prepare_madin_environment_correction_input(transform):
    """Parse real correction authority against an explicit zero-row native environment fixture."""
    role = "madin_environment_id_corrections"
    assert role in type(transform).REQUIRED_CONSUMED_INPUTS
    environments = pd.read_csv(FIXTURES.parent / "madin_foodon_retirement" / "environments.csv", nrows=0)
    expected = environments.copy(deep=True)
    with transform.consume_input(role, ENVIRONMENT_ID_CORRECTIONS_FILE) as reader:
        corrected = _apply_environment_id_corrections(environments, corrections_stream=reader)
    pd.testing.assert_frame_equal(corrected, expected)
    assert corrected.empty, "Nonempty source cohorts require actual producer emission"
    return (role,)


def prepare_prego_identity_inputs(transform):
    """Bind native authority and the real zero-observation producer audit without bypassing contracts."""
    from kg_microbe.transform_utils.prego.envo_identity import AUDIT_COLUMNS

    for name in ("envo.json", "foodon.json"):
        target = transform.input_base_dir / name
        source = IDENTITY_FIXTURES / name
        if not target.exists():
            shutil.copyfile(source, target)
        assert target.read_bytes() == source.read_bytes(), "Do not rewrite an already selected native authority"
    transform._prepare_identity_decisions()
    assert len(transform._identity_decisions) == 10
    prepare_prego_empty_archive_inputs(transform)
    audit_name = "prego_envo_identity.tsv"
    assert type(transform).REQUIRED_AUDIT_FILES == (audit_name,)
    # The graph fixture contains only fixture:1/fixture:2, never a PREGO source
    # observation. Its audit is deliberately empty, not a fake accepted cohort.
    with (transform.output_dir / audit_name).open("w", encoding="utf-8", newline="") as stream:
        tsv_dict_writer(stream, fieldnames=AUDIT_COLUMNS).writeheader()
    transform.record_producer_audit(audit_name)
    return ("prego_envo_policy", "prego_native_envo", "prego_native_foodon")


def record_source(transform):
    """Write the actual registered producer's metadata over the isolated fixture graph."""
    cls = type(transform)
    return write_fingerprint(
        transform.output_dir,
        Path(inspect.getsourcefile(cls)).parent,
        ROOT,
        cls.DATA_INPUTS,
        cls.TRANSFORM_INPUTS,
        input_dir=transform.input_base_dir,
        finalization_inputs=transform.finalization_inputs,
    )


def prepare_source(tmp_path, source, *, prefix="", marker=True, output_name=None):
    """Finalize immutable tiny TSVs with a real producer class, never its constructor or run method."""
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    cls = DATA_SOURCES[source].transform_class
    if "ontologies" in cls.TRANSFORM_INPUTS and not any((tmp_path / "transformed/ontologies").glob("*nodes.tsv")):
        # Such a source finalizes against the ontologies output, and the merge
        # gate checks that upstream, so give it a finalized one as a run would
        # (#1511). A test that prepared its own, even a scoped one, keeps it.
        prepare_source(tmp_path, "ontologies")
    transform = cls.__new__(cls)
    Transform.__init__(transform, output_name or source, raw, tmp_path / "transformed")
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", transform.output_dir / f"{prefix}{kind}.tsv")
    bulk_roles = read_mediadive_bulk_inputs(transform, create=True) if source == "mediadive" else ()
    correction_roles = prepare_bacdive_ec_correction_inputs(transform) if source == "bacdive" else ()
    madin_roles = prepare_madin_environment_correction_input(transform) if source == "madin_etal" else ()
    prego_roles = prepare_prego_identity_inputs(transform) if source == "prego" else ()
    ontology_roles = prepare_empty_native_ro_contract(transform) if source == "ontologies" else ()
    gold_roles = prepare_empty_gold_crosswalk_inputs(transform) if source == "gold" else ()
    rhea_roles = prepare_rhea_native_inputs(transform) if source == "rhea_mappings" else ()
    for role in getattr(cls, "REQUIRED_CONSUMED_INPUTS", ()):
        if role in (
            *bulk_roles,
            *correction_roles,
            *madin_roles,
            *prego_roles,
            *ontology_roles,
            *gold_roles,
            *rhea_roles,
        ):
            continue
        assert role == "bacdive_taxon_lookup", f"Fixture needs an explicit immutable input for {role}"
        lookup = tmp_path / f"{source}-bacdive-lookup.tsv"
        shutil.copyfile(FIXTURES / "lookup.tsv", lookup)
        with transform.consume_input(role, lookup) as reader:
            reader.read()
    for role, _ in cls.OPTIONAL_RAW_CONSUMED_INPUTS:
        with transform.consume_optional_input(role) as reader:
            if reader is not None:
                reader.read()
    if source == "mediadive":
        write_empty_mediadive_audit(transform)
    if source == "ontologies":
        # This helper finalizes only the immutable fixture:1/fixture:2 graph,
        # not a native ontology parse. Its metadata exclusion cohort is empty;
        # bind that explicit fixture audit, never weaken producer requirements.
        audit_name = "ontology_metadata_exclusions.tsv"
        assert cls.REQUIRED_AUDIT_FILES == (
            audit_name,
            "native_relation_dispositions.tsv",
            "foodon_kernel_quarantine.tsv",
            "ontology_parent_dispositions.tsv",
            "upa_route_review.tsv",
        )
        assert (FIXTURES / "nodes.tsv").read_text().count("fixture:") == 2
        shutil.copyfile(FIXTURES / audit_name, transform.output_dir / audit_name)
        transform.record_producer_audit(audit_name)
    transform.finalize(file_prefix=prefix, fresh_run=True)
    if marker:
        record_source(transform)
    return transform


def test_inert_rhea_fixture_binds_real_native_cohort_and_explicit_input_audit(tmp_path):
    """Generic merge fixtures consume native evidence without claiming to test Rhea graph emission."""
    from kg_microbe.transform_utils.rhea_mappings.rhea_mappings import REACTION_AUDIT, RheaMappingsTransform
    from kg_microbe.utils.source_finalization import graph_rows

    transform = prepare_source(tmp_path, "rhea_mappings", marker=False)
    report = json.loads((transform.output_dir / "source_finalization.json").read_text())
    assert set(report["consumed_inputs"]) == set(RheaMappingsTransform.REQUIRED_CONSUMED_INPUTS)
    assert report["consumed_inputs"] == transform.consumed_input_snapshots
    for identity in report["consumed_inputs"].values():
        assert identity in report["inputs"]
        assert Path(identity["path"]).is_relative_to(tmp_path)
        assert hashlib.sha256(Path(identity["path"]).read_bytes()).hexdigest() == identity["sha256"]
    audit = list(graph_rows(transform.output_dir / REACTION_AUDIT))
    assert {(row["reaction_id"], row["direction"]) for row in audit} == {
        ("RHEA:100", "UN"),
        ("RHEA:101", "LR"),
        ("RHEA:102", "RL"),
        ("RHEA:103", "BI"),
    }
    assert {row["disposition"] for row in audit} == {"fixture_validated_input_only"}
    assert {row["native_status"] for row in audit} == {"Approved"}
    assert report["producer_audit_members"][REACTION_AUDIT] == transform.producer_audit_snapshots[REACTION_AUDIT]
    assert {row["id"] for row in graph_rows(transform.output_node_file)} == {"fixture:1", "fixture:2"}
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize("changed", ["rhea_release_manifest", "rhea_directions", "rhea_rdf", "audit"])
def test_inert_rhea_fixture_drift_is_rejected_at_merge_admission(tmp_path, changed):
    """Neither generic output rows nor a prior marker exempt required native inputs or the producer audit."""
    from kg_microbe.transform_utils.rhea_mappings.rhea_mappings import REACTION_AUDIT

    transform = prepare_source(tmp_path, "rhea_mappings")
    paths = [transform.output_node_file, transform.output_edge_file]
    verify_finalized_source_files(paths)
    if changed == "audit":
        target = transform.output_dir / REACTION_AUDIT
    else:
        target = Path(transform.consumed_input_snapshots[changed]["path"])
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(SourceFinalizationRequired):
        verify_finalized_source_files(paths)


def test_empty_madin_fixture_binds_real_correction_table(tmp_path):
    """The inert graph fixture obeys the registered producer's required immutable correction read."""
    transform = prepare_source(tmp_path, "madin_etal", marker=False)
    identity = {
        "path": str(ENVIRONMENT_ID_CORRECTIONS_FILE.resolve()),
        "sha256": hashlib.sha256(ENVIRONMENT_ID_CORRECTIONS_FILE.read_bytes()).hexdigest(),
    }
    report = json.loads((transform.output_dir / "source_finalization.json").read_text())
    assert report["consumed_inputs"] == {"madin_environment_id_corrections": identity}
    assert transform.consumed_input_snapshots == report["consumed_inputs"]
    assert identity in report["inputs"]
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


def test_empty_ontology_fixture_binds_mandatory_metadata_audit(tmp_path):
    """The hermetic ontology fixture obeys registered mandatory evidence at finalization and admission."""
    transform = prepare_source(tmp_path, "ontologies", marker=False)
    filename = "ontology_metadata_exclusions.tsv"
    path = transform.output_dir / filename
    assert path.read_bytes() == (FIXTURES / filename).read_bytes()
    report = json.loads((transform.output_dir / "source_finalization.json").read_text())
    assert report["producer_audit_members"][filename] == transform.producer_audit_snapshots[filename]
    assert report["audit_members"][filename] == transform.producer_audit_snapshots[filename]
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


def test_empty_bacdive_fixture_has_real_correction_input_and_audit_contract(tmp_path):
    """An inert graph fixture still exercises actual policy preflight and immutable audit registration."""
    transform = prepare_source(tmp_path, "bacdive", marker=False)
    filename = ec_substrate_corrections.AUDIT_FILE
    path = transform.output_dir / filename
    assert path.read_bytes() == (FIXTURES / filename).read_bytes()
    identity = transform.producer_audit_snapshots[filename]
    report = json.loads((transform.output_dir / "source_finalization.json").read_text())
    assert set(report["consumed_inputs"]) == set(type(transform).REQUIRED_CONSUMED_INPUTS)
    assert report["producer_audit_members"][filename] == identity
    assert report["audit_members"][filename] == identity
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize("gss_present", [False, True])
def test_empty_bacdive_fixture_obeys_real_taxonomy_lifecycle(tmp_path, gss_present):
    """An empty graph fixture consumes real source bytes without inventing ancestry queries."""
    raw = tmp_path / "raw"
    raw.mkdir()
    gss = raw / "lpsn_gss.csv"
    if gss_present:
        shutil.copyfile(FIXTURES.parent / "bacdive_taxonomy_evidence/lpsn_gss.csv", gss)
    transform = prepare_source(tmp_path, "bacdive", marker=False)
    report = json.loads((transform.output_dir / "source_finalization.json").read_text())
    contract = report["producer_native_inputs"]["taxonomy"]
    assert contract["native_records"] == 0
    fallback = contract["fallback_native_evidence"]
    assert fallback["eligible_record_count"] == 0
    assert fallback["plans"] == {}
    assert fallback["native_queries"] is None and fallback["selected_input"] is None
    assert fallback["raw_role"]["name"] in report["consumed_inputs"]
    assert contract["audit_rows"] == 0
    assert contract["resolved_deposit_count"] == 0
    assert contract["ancestry"]["actual_queries"] is None
    assert contract["ancestry"]["callback_demand_counts"] == []
    assert report["consumed_inputs"][supplied_taxid_policy.ROLE] == {
        "path": str(supplied_taxid_policy.POLICY_PATH.resolve()),
        "sha256": supplied_taxid_policy.POLICY_SHA256,
    }
    assert (taxonomy_evidence.GSS_ROLE in report["consumed_inputs"]) == gss_present
    if gss_present:
        assert contract["optional_gss"]["sha256"] == hashlib.sha256(gss.read_bytes()).hexdigest()
    else:
        assert contract["optional_gss"]["sha256"] is None
    audit = transform.output_dir / taxonomy_evidence.AUDIT_FILE
    assert audit.read_bytes() == ("\t".join(taxonomy_evidence.AUDIT_FIELDS) + "\n").encode()
    assert report["producer_audit_members"][audit.name] == transform.producer_audit_snapshots[audit.name]
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])
    fresh = type(transform).__new__(type(transform))
    Transform.__init__(fresh, "bacdive", transform.input_base_dir, transform.output_base_dir)
    assert fresh.finalize() == report
    fresh.verify_native_inputs()


@pytest.mark.parametrize("damage", ["missing", "unrecorded", "changed"])
def test_empty_bacdive_fixture_cannot_omit_or_restamp_correction_audit(tmp_path, damage):
    """The merge fixture cannot bypass the same mandatory evidence checks as the actual producer."""
    transform = prepare_source(tmp_path, "bacdive", marker=False)
    path = transform.output_dir / ec_substrate_corrections.AUDIT_FILE
    if damage == "missing":
        path.unlink()
    elif damage == "changed":
        path.write_bytes(path.read_bytes() + b"changed\n")
    else:
        transform._producer_audit_snapshots.clear()
    before = {path.name: path.read_bytes() for path in transform.output_dir.iterdir()}
    with pytest.raises(SourceFinalizationRequired, match="audit"):
        transform.finalize(fresh_run=True)
    assert {path.name: path.read_bytes() for path in transform.output_dir.iterdir()} == before


def test_empty_mediadive_fixture_has_real_producer_audit(tmp_path):
    """An empty cohort still retains the writer's exact bytes through public source admission."""
    transform = prepare_source(tmp_path, "mediadive")
    path = transform.output_dir / AUDIT_FILENAME
    assert path.read_bytes() == ("\t".join(AUDIT_HEADER) + "\n").encode()
    identity = transform.producer_audit_snapshots[AUDIT_FILENAME]
    report = json.loads((transform.output_dir / "source_finalization.json").read_text())
    assert report["producer_audit_members"][AUDIT_FILENAME] == identity
    assert report["audit_members"][AUDIT_FILENAME] == identity
    verify_finalized_source_files([transform.output_node_file, transform.output_edge_file])


@pytest.mark.parametrize("damage", ["missing", "unrecorded"])
def test_empty_mediadive_fixture_cannot_omit_producer_evidence(tmp_path, damage):
    """Neither finalized metadata nor a header-only file replaces producer-time evidence."""
    transform = prepare_source(tmp_path, "mediadive")
    if damage == "missing":
        (transform.output_dir / AUDIT_FILENAME).unlink()
    else:
        transform._producer_audit_snapshots.clear()
    before = {path.name: path.read_bytes() for path in transform.output_dir.iterdir()}
    with pytest.raises(SourceFinalizationRequired, match="producer audit"):
        transform.finalize(fresh_run=True)
    assert {path.name: path.read_bytes() for path in transform.output_dir.iterdir()} == before


def merge_config(tmp_path, transforms, *, diagnostic=False):
    """Select explicit fixture paths, using unrelated config labels to prevent path-name inference."""
    config = tmp_path / "merge.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "configuration": {
                    "output_directory": str(tmp_path / "published"),
                    "allow_unfinalized_sources": diagnostic,
                },
                "merged_graph": {
                    "name": "fixture",
                    "source": {
                        f"selected_{index}": {
                            "input": {
                                "format": "tsv",
                                "filename": [str(path) for path in transform.output_dir.glob("*nodes.tsv")]
                                + [str(path) for path in transform.output_dir.glob("*edges.tsv")],
                            }
                        }
                        for index, transform in enumerate(transforms)
                    },
                    "destination": {"tsv": {"format": "tsv", "filename": "fixture"}},
                },
            }
        ),
        encoding="utf-8",
    )
    return config


@pytest.fixture
def prepared(tmp_path):
    """Provide every declared upstream marker, initially current with exact prepared bytes."""
    sources = {
        source: prepare_source(tmp_path, source) for source in ("ontologies", "bacdive", "mediadive", "bactotraits")
    }
    lookup = tmp_path / "bacdive.tsv"
    shutil.copyfile(FIXTURES / "lookup.tsv", lookup)
    sources["bacdive"].finalization_inputs = (*sources["bacdive"].finalization_inputs, str(lookup))
    for source in ("bacdive", "mediadive", "bactotraits"):
        record_source(sources[source])
    return sources


@pytest.mark.parametrize("source", ["mediadive", "bactotraits"])
def test_changed_upstream_marker_blocks_cli_and_api_before_kgx(tmp_path, monkeypatch, prepared, source):
    """An upstream-only change rejects unchanged consumer bytes and preserves a published archive."""
    consumer = prepared[source]
    config = merge_config(tmp_path, [consumer])
    merge_kg._assert_sources_finalized(str(config))
    original = {path.name: path.read_bytes() for path in consumer.output_dir.iterdir()}
    marker = json.loads((consumer.output_dir / "source_fingerprint.json").read_text())
    shutil.copyfile(FIXTURES / "changed_lookup.tsv", tmp_path / "bacdive.tsv")
    record_source(prepared["bacdive"])
    assert marker["upstream"] != upstream_fingerprint(consumer.output_base_dir, type(consumer).TRANSFORM_INPUTS)
    published = tmp_path / "published/fixture.tar.gz"
    published.parent.mkdir()
    published.write_bytes(b"previous complete archive")

    def unexpected_kgx(*args, **kwargs):
        """Fail if the required gate admits stale upstream evidence."""
        raise AssertionError("KGX must not run")

    monkeypatch.setattr(merge_kg, "merge", unexpected_kgx)
    with pytest.raises(SourceFinalizationRequired, match="upstream"):
        merge_kg.load_and_merge(str(config))
    result = CliRunner().invoke(main, ["merge", "-y", str(config)])
    assert isinstance(result.exception, SourceFinalizationRequired)
    assert "upstream" in str(result.exception)
    assert original == {path.name: path.read_bytes() for path in consumer.output_dir.iterdir()}
    assert published.read_bytes() == b"previous complete archive"


@pytest.mark.parametrize("damage", ["missing", "unsupported"])
def test_missing_or_unsupported_upstream_marker_is_required(tmp_path, prepared, damage):
    """A recorded upstream cannot turn into an unknown absence accepted by production merge."""
    config = merge_config(tmp_path, [prepared["mediadive"]])
    marker = prepared["bacdive"].output_dir / "source_fingerprint.json"
    if damage == "missing":
        marker.unlink()
    else:
        payload = json.loads(marker.read_text())
        payload["version"] = 999
        marker.write_text(json.dumps(payload))
    with pytest.raises(SourceFinalizationRequired, match="upstream|fingerprint"):
        merge_kg._assert_sources_finalized(str(config))


def test_scoped_ontology_requires_whole_producer_schema_evidence(tmp_path, capsys):
    """A scoped graph record alone cannot prove missing producer or pinned-schema freshness."""
    ontology = prepare_source(tmp_path, "ontologies", prefix="pato_", marker=False)
    direct = merge_config(tmp_path, [ontology])
    with pytest.raises(SourceFinalizationRequired, match="whole producer/schema.*kg transform -s ontologies"):
        merge_kg._assert_sources_finalized(str(direct))
    diagnostic = merge_config(tmp_path, [ontology], diagnostic=True)
    merge_kg._assert_sources_finalized(str(diagnostic))
    assert "DIAGNOSTIC OPT-OUT" in capsys.readouterr().out
    consumer = prepare_source(tmp_path, "bacdive")
    config = merge_config(tmp_path, [consumer])
    with pytest.raises(SourceFinalizationRequired, match="upstream|whole|fingerprint"):
        merge_kg._assert_sources_finalized(str(config))


def test_only_explicit_diagnostic_opt_out_bypasses_dependency_gate(tmp_path, prepared, capsys):
    """The documented diagnostic flag remains conspicuous, never inferred from fixture paths."""
    (prepared["bacdive"].output_dir / "source_fingerprint.json").unlink()
    config = merge_config(tmp_path, [prepared["mediadive"]], diagnostic=True)
    merge_kg._assert_sources_finalized(str(config))
    assert "DIAGNOSTIC OPT-OUT" in capsys.readouterr().out


def test_prego_alias_uses_producer_metadata_not_directory_or_config_label(tmp_path):
    """Habitat-only PREGO output belongs to the registered prego producer."""
    prepare_source(tmp_path, "ontologies")
    source = prepare_source(tmp_path, "prego", output_name="prego_habitat")
    config = merge_config(tmp_path, [source])
    merge_kg._assert_sources_finalized(str(config))


def test_bakta_selected_dataset_uses_parent_producer_marker(tmp_path):
    """The explicit dataset protocol keeps local graph evidence and aggregate producer freshness."""
    raw = tmp_path / "raw"
    raw.mkdir()
    cls = DATA_SOURCES["bakta"].transform_class
    source = cls.__new__(cls)
    Transform.__init__(source, "bakta", raw, tmp_path / "transformed")
    dataset = source.output_dir / "selected_dataset"
    dataset.mkdir()
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", dataset / f"{kind}.tsv")
    source.finalization_output_dirs = [dataset]
    source.finalize(fresh_run=True)
    record_source(source)
    config = merge_config(tmp_path, [source])
    payload = yaml.safe_load(config.read_text())
    payload["merged_graph"]["source"]["selected_0"]["input"]["filename"] = [
        str(dataset / "nodes.tsv"),
        str(dataset / "edges.tsv"),
    ]
    config.write_text(yaml.safe_dump(payload))
    merge_kg._assert_sources_finalized(str(config))


def test_valid_scoped_record_supersedes_stale_whole_ontology_record(tmp_path):
    """A stale full record must not shadow a current explicitly selected ontology bundle."""
    source = prepare_source(tmp_path, "ontologies", prefix="pato_", marker=False)
    source.finalize(fresh_run=True)
    record_source(source)
    nodes = source.output_dir / "pato_nodes.tsv"
    nodes.write_text(nodes.read_text().replace("One", "Updated"))
    source.finalize(file_prefix="pato_", fresh_run=True)
    config = merge_config(tmp_path, [source])
    merge_kg._assert_sources_finalized(str(config))


@pytest.mark.parametrize("schema", [None, {"version": "unknown", "digest": "matching-but-unproven"}])
def test_scoped_ontology_rejects_matching_unknown_schema(tmp_path, monkeypatch, schema):
    """Two matching unknown schema values cannot supply affirmative schema provenance."""
    from kg_microbe.merge_utils import source_freshness

    source = prepare_source(tmp_path, "ontologies", prefix="pato_")
    marker_path = source.output_dir / "source_fingerprint.json"
    marker = json.loads(marker_path.read_text())
    marker["schema"] = schema
    marker_path.write_text(json.dumps(marker))
    monkeypatch.setattr(source_freshness, "schema_fingerprint", lambda root: schema)
    config = merge_config(tmp_path, [source])
    with pytest.raises(SourceFinalizationRequired, match="schema"):
        merge_kg._assert_sources_finalized(str(config))


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_real_schema_fixture_damage_blocks_public_merge(tmp_path, monkeypatch, local_source_schema, damage):
    """Hermetic schema selection still rejects actual missing or changed bytes before KGX."""
    from kg_microbe.utils.transform_fingerprint import schema_fingerprint

    source = prepare_source(tmp_path, "rhea_mappings")
    config = merge_config(tmp_path, [source])
    marker = json.loads((source.output_dir / "source_fingerprint.json").read_text())
    assert marker["schema"] == schema_fingerprint(ROOT)
    assert marker["schema"]["version"] == "4.4.2"
    merge_kg._assert_sources_finalized(str(config))
    model = local_source_schema[0]
    if damage == "missing":
        model.unlink()
    else:
        model.write_text(model.read_text() + "\n# a different schema input\n")
    assert schema_fingerprint(ROOT) != marker["schema"]

    def no_kgx(*args, **kwargs):
        """Reject any attempt to publish after schema evidence changed."""
        pytest.fail("KGX must not run with missing or changed schema inputs")

    monkeypatch.setattr(merge_kg, "merge", no_kgx)
    with pytest.raises(SourceFinalizationRequired, match="schema"):
        merge_kg.load_and_merge(str(config))


def test_unknown_producer_metadata_is_not_a_silent_exemption(tmp_path):
    """Unregistered external graphs require the explicit diagnostic opt-out, not guessed freshness."""
    raw = tmp_path / "raw"
    raw.mkdir()
    source = Transform("unknown", raw, tmp_path / "transformed")
    for kind in ("nodes", "edges"):
        shutil.copyfile(FIXTURES / f"{kind}.tsv", source.output_dir / f"{kind}.tsv")
    source.finalize(fresh_run=True)
    config = merge_config(tmp_path, [source])
    with pytest.raises(SourceFinalizationRequired, match="Unsupported producer metadata"):
        merge_kg._assert_sources_finalized(str(config))
