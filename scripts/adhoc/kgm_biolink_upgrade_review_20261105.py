#!/usr/bin/env python3
"""
Retain local semantic evidence for the 2026-11-05 Biolink upgrade (#1724).

Inputs: complete old/new Biolink model, attributes and predicate-map bundles,
optional acquisition receipts, reviewed repository policies and an optional graph
archive or TSV pair. Outputs: a new evidence directory containing exact input
identities, complete parsed-document differences, policy/graph term comparisons
and a diagnostic-profile review plan. No input, policy, pin or fixture is edited.
This is comparison evidence, not scientific acceptance or release authorization.
"""

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "data/rebuild-evidence/20261105/upgrades/biolink"
TRIPLET = ("biolink-model.yaml", "attributes.yaml", "predicate_mapping.yaml")
RUNTIME_POLICIES = ("ncit_eight_categories.json", "mesh_finite_category_dispositions.json")
CARRIED_POLICIES = (
    "finite_envo_po_category_dispositions.json",
    "native_ro_predicate_dispositions.json",
    "ontology_parent_dispositions.json",
    "uberon_temporal_category_dispositions.json",
    "finite_import_category_dispositions.json",
    "foodon_anatomical_category_dispositions.json",
    "foodon_kernel_quarantine.json",
)
HISTORICAL_PROFILES = ("kgxval_dispositions_v1.json", "kgxval_reference_dispositions_v1.json")
CONTROL_CLASSES = (
    "organism taxon",
    "ontology class",
    "genome",
    "food",
    "thing with taxon",
    "life stage",
    "occurrent",
    "activity",
    "anatomical entity",
    "protein",
    "physical entity",
    "molecular activity",
    "attribute",
    "biological process",
    "environmental process",
    "phenotypic feature",
    "phenotypic quality",
)
CONTROL_SLOTS = (
    "subclass of",
    "in taxon",
    "participates in",
    "has participant",
    "temporally related to",
    "enables",
    "has attribute type",
    "has attribute",
    "has phenotype",
    "publications",
    "close match",
    "located in",
    "occurs in",
    "capable of",
    "has part",
    "part of",
    "has chemical role",
    "is about",
)


def require(condition, message):
    """Refuse incomplete or ambiguous evidence rather than inferring missing semantics."""
    if not condition:
        raise ValueError(message)


def digest(value):
    """Identify exact bytes or canonical parsed evidence without rewriting either input."""
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(value).hexdigest()


def read_yaml(payload):
    """Reject duplicate keys instead of silently discarding an upstream schema statement."""
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        """Preserve an unambiguous parsed source for structural comparison."""

    def mapping(loader, node, deep=False):
        """Construct mappings only when every literal key has one source occurrence."""
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            require(key not in result, f"Duplicate YAML key: {key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(payload, Loader=UniqueLoader)  # noqa: S506 - subclass of SafeLoader


def differences(old, new, path=()):
    """Retain every changed parsed field, including complete old/new list values."""
    if old == new:
        return []
    if isinstance(old, dict) and isinstance(new, dict):
        result = []
        for key in sorted(old.keys() | new.keys()):
            location = (*path, key)
            if key not in old:
                result.append({"path": list(location), "change": "added", "new": new[key]})
            elif key not in new:
                result.append({"path": list(location), "change": "removed", "old": old[key]})
            else:
                result.extend(differences(old[key], new[key], location))
        return result
    return [{"path": list(path), "change": "changed", "old": old, "new": new}]


def load_bundle(directory, expected_version, admission):
    """Read complete bundle bytes and every bare sibling import, never remote imports."""
    directory = directory.resolve()
    documents, identities, external = {}, {}, set()
    pending = list(TRIPLET)
    while pending:
        name = pending.pop(0)
        if name in documents:
            continue
        require(Path(name).name == name and name.endswith(".yaml"), f"Unsafe schema member: {name}")
        path = directory / name
        require(not path.is_symlink(), f"Schema input must be an independent regular file: {path}")
        content = admission.capture(path, retain=True)
        document = read_yaml(content)
        require(isinstance(document, dict), f"Expected schema object: {path}")
        documents[name] = document
        identities[name] = {"path": str(path), **admission.identities[path.resolve()]}
        imports = document.get("imports", [])
        imports = [imports] if isinstance(imports, str) else imports
        require(isinstance(imports, list), f"Malformed imports in {path}")
        for imported in imports:
            require(isinstance(imported, str) and imported, f"Malformed import in {path}")
            if ":" in imported:
                require(imported == "linkml:types", f"Unreviewed external import: {imported}")
                external.add(imported)
            else:
                require(Path(imported).name == imported, f"Unsafe sibling import: {imported}")
                pending.append(f"{imported}.yaml")
    require(
        documents[TRIPLET[0]].get("version") == expected_version, "Actual model version differs from requested epoch"
    )
    # Imports are read in dependency order; root declarations override imported
    # declarations as SchemaView does. Record collisions rather than hiding them.
    definitions, collisions, active, loaded = {"classes": {}, "slots": {}}, [], set(), set()

    def visit(name):
        """Flatten only local schema definitions while preserving import precedence evidence."""
        require(name not in active, f"Cyclic schema import: {name}")
        if name in loaded:
            return
        active.add(name)
        imports = documents[name].get("imports", [])
        imports = [imports] if isinstance(imports, str) else imports
        for imported in imports:
            if ":" not in imported:
                visit(f"{imported}.yaml")
        for section in definitions:
            for key, value in (documents[name].get(section) or {}).items():
                if key in definitions[section] and definitions[section][key] != value:
                    collisions.append({"section": section, "name": key, "selected_from": name})
                definitions[section][key] = value
        active.remove(name)
        loaded.add(name)

    visit(TRIPLET[0])
    return {
        "version": expected_version,
        "directory": str(directory),
        "members": identities,
        "documents": documents,
        "definitions": definitions,
        "import_collisions": collisions,
        "external_imports": sorted(external),
    }


def closure(name, definitions, active=None):
    """Retain exact declarations along every is_a and mixin ancestry path."""
    active = set() if active is None else active
    require(name not in active, f"Cyclic is_a/mixin ancestry at {name}")
    require(name in definitions, f"Missing is_a/mixin declaration: {name}")
    definition = definitions[name] or {}
    require(isinstance(definition, dict), f"Malformed definition: {name}")
    active.add(name)
    parents = list(definition.get("mixins") or [])
    if definition.get("is_a"):
        parents.append(definition["is_a"])
    result = {name: definition}
    for parent in parents:
        result.update(closure(parent, definitions, active))
    active.remove(name)
    return dict(sorted(result.items()))


def term_evidence(bundle, section, name):
    """Describe full ancestry and inherited slot declarations without claiming induced LinkML validation."""
    definitions = bundle["definitions"]
    if name not in definitions[section]:
        return {"present": False}
    ancestors = closure(name, definitions[section])
    result = {"present": True, "declaration": definitions[section][name], "ancestry": ancestors}
    if section == "classes":
        slots = set()
        for definition in ancestors.values():
            slots.update((definition.get("slots") or []))
            slots.update((definition.get("slot_usage") or {}))
            slots.update((definition.get("attributes") or {}))
        result["inherited_slot_declarations"] = {
            slot: closure(slot, definitions["slots"])
            if slot in definitions["slots"]
            else {"class_local_attribute": True}
            for slot in sorted(slots)
        }
    else:
        endpoints = {
            definition[key]
            for definition in ancestors.values()
            for key in ("domain", "range")
            if definition.get(key) in definitions["classes"]
        }
        result["domain_range_class_ancestry"] = {
            endpoint: closure(endpoint, definitions["classes"]) for endpoint in sorted(endpoints)
        }
    return result


def term_comparison(old, new, section, name):
    """Expose both complete term contexts and every changed context field."""
    before, after = term_evidence(old, section, name), term_evidence(new, section, name)
    changes = differences(before, after)
    return {"term": name, "section": section, "changed": bool(changes), "old": before, "new": after, "changes": changes}


def name_index(bundle, section):
    """Map conventional Biolink CURIE spellings without changing source identifiers."""
    result = {}
    for name in bundle["definitions"][section]:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        result.setdefault(key, []).append(name)
    return result


def referenced_terms(document):
    """Find literal Biolink identifiers throughout policy evidence, including controls and prose."""
    return set(re.findall(r"biolink:[A-Za-z][A-Za-z0-9_]*", json.dumps(document)))


def compare_identifiers(old, new, identifiers):
    """Keep unknown extensions visible and compare all resolvable category/predicate terms."""
    indexes = {
        (epoch, section): name_index(bundle, section)
        for epoch, bundle in (("old", old), ("new", new))
        for section in ("classes", "slots")
    }
    result = {}
    for identifier in sorted(identifiers):
        key = re.sub(r"[^a-z0-9]", "", identifier.removeprefix("biolink:").lower())
        matches = []
        for section in ("classes", "slots"):
            names = set(indexes["old", section].get(key, [])) | set(indexes["new", section].get(key, []))
            if len(names) > 1:
                matches.append({"normalized_name_ambiguity": sorted(names), "review_required": True})
            matches.extend(term_comparison(old, new, section, name) for name in sorted(names))
        result[identifier] = matches or [{"unresolved_in_both_models": True, "review_required": True}]
    return result


def native_relation_mappings(bundle, relations):
    """Keep mapping strengths and full qualified predicate-map records for native relations."""
    result = {}
    for relation in sorted(relations):
        slots = []
        for name, definition in bundle["definitions"]["slots"].items():
            for field in ("exact_mappings", "narrow_mappings", "broad_mappings", "close_mappings", "related_mappings"):
                if relation in ((definition or {}).get(field) or []):
                    slots.append({"slot": name, "mapping_field": field, "declaration": definition})
        records = [
            record
            for record in bundle["documents"]["predicate_mapping.yaml"].get("predicate mappings", [])
            if any(
                relation in record.get(field, [])
                for field in ("exact matches", "narrow matches", "broad matches", "close matches", "related matches")
            )
        ]
        result[relation] = {"slot_mappings": slots, "predicate_map_records": records}
    return result


def native_relation_comparison(old, new, relations):
    """Expose mapping loss, strengthening and qualified mapping changes separately from names."""
    before = native_relation_mappings(old, relations)
    after = native_relation_mappings(new, relations)
    return {"old": before, "new": after, "changes": differences(before, after)}


def policy_comparison(old, new, root, admission):
    """Review runtime policy classes and retain historical policy attribution independently."""
    result = {"runtime": {}, "carry_forward": {}, "historical_profiles": {}}
    for filename in (*RUNTIME_POLICIES, *CARRIED_POLICIES, *HISTORICAL_PROFILES):
        path = root / "mappings" / filename
        policy = admission.read_json(path)
        evidence = {"path": str(path), "identity": admission.identities[path.resolve()], "scientific_acceptance": False}
        if filename in RUNTIME_POLICIES:
            selected = policy["model_classes"]
            require(
                policy["model_version"] == old["version"]
                and policy["model_sha256"] == old["members"][TRIPLET[0]]["sha256"],
                f"Runtime policy is not bound to supplied old model: {filename}",
            )
            require(
                all(old["definitions"]["classes"].get(name) == definition for name, definition in selected.items()),
                f"Runtime policy definitions differ from actual old model: {filename}",
            )
            comparisons = {name: term_comparison(old, new, "classes", name) for name in selected}
            evidence.update(
                model_classes=comparisons,
                native_record_count=len(policy["records"]),
                changed_classes=[name for name, item in comparisons.items() if item["changed"]],
                required_action=(
                    "Independent native-decision assessment before changing model fields or canonical "
                    "policy code anchor."
                ),
            )
            result["runtime"][filename] = evidence
        elif filename in CARRIED_POLICIES:
            comparisons = compare_identifiers(old, new, referenced_terms(policy))
            evidence.update(
                original_model_attribution=policy.get("reviewed_model", policy.get("category_rationale")),
                referenced_terms=comparisons,
                native_relation_mappings=native_relation_comparison(old, new, set(policy.get("relations", {}))),
                required_action=(
                    "Preserve historical attribution; review changed contexts and replay the existing "
                    "finite native cohort under the new model."
                ),
            )
            result["carry_forward"][filename] = evidence
        else:
            evidence.update(
                reference=policy["reference"],
                profile_id=policy["profile_id"],
                required_action=(
                    "Preserve this historical graph/schema/CSV epoch. Do not transfer its reference "
                    "assessments to new diagnostics."
                ),
            )
            result["historical_profiles"][filename] = evidence
    profile_path = root / "kg_microbe/profiles/ingredient_kgx_v1.yaml"
    ingredient = read_yaml(admission.capture(profile_path, retain=True))
    result["ingredient_profile"] = {
        "identity": admission.identities[profile_path.resolve()],
        "profile": ingredient,
        "required_action": (
            "Assess pairing with the new schema separately; retain the old v1 acceptance "
            "epoch and keep MIM explicit-only."
        ),
    }
    return result


def inventory_table(binary, kind):
    """Stream category incidence or literal predicate/relation frequencies with bounded memory."""
    totals, relations, rows = Counter(), Counter(), 0
    key = "category" if kind == "nodes" else "predicate"
    stream = (line.decode("utf-8") for line in binary)
    reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
    require(key in (reader.fieldnames or []), f"Graph lacks {key} column")
    for row in reader:
        require(None not in row and all(value is not None for value in row.values()), "Malformed graph TSV row")
        values = set(filter(None, row[key].split("|"))) if kind == "nodes" else {row[key]}
        totals.update(values or {"(blank)"})
        if kind == "edges":
            relations[row.get("relation", "") or "(blank)"] += 1
        rows += 1
    require(rows > 0, f"Empty graph {kind} inventory")
    return {"rows": rows, "counts": dict(sorted(totals.items())), "relations": dict(sorted(relations.items()))}


def graph_inventory(archive_path, nodes_path, edges_path, admission):
    """Bind reference graph bytes and stream members without extracting or loading whole TSVs."""
    if archive_path is None and nodes_path is None and edges_path is None:
        return {"status": "not_supplied", "scientific_acceptance": False}
    require(bool(archive_path) != bool(nodes_path or edges_path), "Supply an archive or a nodes/edges pair")
    # A description field can exceed csv's conservative default. Memory still
    # scales with one record and distinct categories/predicates, never all rows.
    prior_limit = csv.field_size_limit()
    csv.field_size_limit(64 * 1024 * 1024)
    result = {"status": "inventoried", "inputs": {}, "scientific_acceptance": False}
    try:
        if archive_path:
            identity = admission.capture(archive_path)
            result["inputs"][str(archive_path.resolve())] = identity
            seen, graph_members = set(), {}
            with gzip.open(archive_path, "rb") as compressed:
                with tarfile.open(fileobj=compressed, mode="r|") as archive:
                    for member in archive:
                        require(
                            member.isfile() and Path(member.name).name == member.name and member.name not in seen,
                            f"Unsafe/nonregular/duplicate archive member: {member.name}",
                        )
                        seen.add(member.name)
                        kind = (
                            "nodes"
                            if member.name.endswith("_nodes.tsv")
                            else "edges"
                            if member.name.endswith("_edges.tsv")
                            else None
                        )
                        if kind:
                            require(kind not in graph_members, f"Ambiguous archive {kind} member")
                            graph_members[kind] = member.name
                            with archive.extractfile(member) as stream:
                                result[kind] = inventory_table(stream, kind)
                while compressed.read(1024 * 1024):
                    pass
            require(set(graph_members) == {"nodes", "edges"}, "Archive does not contain one complete graph pair")
            require(graph_members["nodes"][:-10] == graph_members["edges"][:-10], "Archive graph names differ")
            result["members"] = graph_members
        else:
            require(nodes_path and edges_path, "Both --nodes and --edges are required")
            for kind, path in (("nodes", nodes_path), ("edges", edges_path)):
                result["inputs"][str(path.resolve())] = admission.capture(path)
                with path.open("rb") as stream:
                    result[kind] = inventory_table(stream, kind)
    finally:
        csv.field_size_limit(prior_limit)
    admission.verify(metadata_only=True)
    return result


def diagnostic_profile_plan(new, policies):
    """Define a new review epoch without cloning old signatures, dispositions or acceptance claims."""
    return {
        "status": "plan_only_not_a_profile",
        "proposed_profile_id": f"kgm-kgxval-dispositions-{new['version']}-v2",
        "model_identity": new["members"],
        "historical_profiles_preserved": policies["historical_profiles"],
        "diagnostics": [],
        "scientific_acceptance": False,
        "release_authorized": False,
        "required_evidence": [
            (
                "New completed validator run against the rebuilt archive using exact local target "
                "model/map/imports and recorded installed toolchain."
            ),
            (
                "Archive SHA, six-cell CSV SHA, exact validator invocation, completion/exit "
                "evidence and all diagnostic multiplicities."
            ),
            (
                "New per-signature review and original graph-row joins with endpoint "
                "IDs/categories, relation, knowledge source and native evidence; CSV cells alone "
                "do not establish edge acceptance."
            ),
            (
                "Retain new/changed/unregistered diagnostics explicitly. No automatic copying of "
                "historical profile classifications or reference assessments."
            ),
            (
                "Implement explicitly versioned loader/CLI selection with mutation-rejection "
                "tests; keep existing v1 defaults/history truthful until reviewed adoption."
            ),
        ],
    }


def compare(old, new, root, admission, graph):
    """Assemble complete comparison evidence; any semantic acceptance remains separately reviewable."""
    policy = policy_comparison(old, new, root, admission)
    all_documents = {}
    for name in sorted(old["documents"].keys() | new["documents"].keys()):
        all_documents[name] = differences(old["documents"].get(name), new["documents"].get(name))
    controls = {
        section: {name: term_comparison(old, new, section, name) for name in names}
        for section, names in (("classes", CONTROL_CLASSES), ("slots", CONTROL_SLOTS))
    }
    graph_comparison = {}
    if graph["status"] == "inventoried":
        identifiers = set(graph["nodes"]["counts"]) | set(graph["edges"]["counts"])
        graph_comparison = compare_identifiers(
            old, new, {value for value in identifiers if value.startswith("biolink:")}
        )
        graph["native_relation_mappings"] = native_relation_comparison(
            old, new, set(graph["edges"]["relations"]) - {"(blank)"}
        )
    return {
        "comparison_version": 1,
        "status": "comparison_complete_review_required",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "old_bundle": {key: value for key, value in old.items() if key not in {"documents", "definitions"}},
        "new_bundle": {key: value for key, value in new.items() if key not in {"documents", "definitions"}},
        "document_differences": all_documents,
        "policies": policy,
        "semantic_controls": controls,
        "graph_inventory": graph,
        "graph_term_comparisons": graph_comparison,
        "diagnostic_profile_plan": diagnostic_profile_plan(new, policy),
        "scientific_acceptance": False,
        "release_authorized": False,
        "limitations": [
            (
                "Acquisition receipts are bound input evidence; this local comparison does not "
                "independently authenticate an upstream server."
            ),
            (
                "Exact declared ancestry/slot evidence is compared, not a substitute for "
                "BMT/LinkML induced-slot behavior or actual KGX conversion tests."
            ),
            (
                "linkml:types remains an installed-runtime import; compare resolver-selected "
                "runtime changes and exercise fresh offline Toolkits separately."
            ),
            (
                "Graph inventory binds source bytes and counts; it is not endpoint-level "
                "domain/range validation or native claim review."
            ),
            "Unchanged declarations do not by themselves authorize updated policy digests, new profiles or release.",
        ],
    }


def write_outputs(output, result):
    """Write one new task-owned comparison directory without overwriting earlier evidence."""
    output = output.resolve()
    require(output.is_relative_to(EVIDENCE.resolve()), f"Output must be under {EVIDENCE}")
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (
        ("comparison.json", result),
        ("diagnostic-profile-plan.json", result["diagnostic_profile_plan"]),
    ):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    summary = {
        "status": result["status"],
        "old_version": result["old_bundle"]["version"],
        "new_version": result["new_bundle"]["version"],
        "changed_document_fields": {name: len(changes) for name, changes in result["document_differences"].items()},
        "runtime_policy_changed_classes": {
            name: item["changed_classes"] for name, item in result["policies"]["runtime"].items()
        },
        "graph_status": result["graph_inventory"]["status"],
        "scientific_acceptance": False,
        "comparison": str(output / "comparison.json"),
    }
    with (output / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    selected = {"classes": set(CONTROL_CLASSES), "slots": set(CONTROL_SLOTS)}
    for item in result["policies"]["runtime"].values():
        selected["classes"].update(item["model_classes"])
    comparisons = list(result["graph_term_comparisons"].values())
    for item in result["policies"]["carry_forward"].values():
        comparisons.extend(item["referenced_terms"].values())
    for entries in comparisons:
        for entry in entries:
            if "section" in entry:
                selected[entry["section"]].add(entry["term"])
    native = result["policies"]["carry_forward"]["native_ro_predicate_dispositions.json"]["native_relation_mappings"][
        "old"
    ]
    spec = {key: sorted(values) for key, values in selected.items()}
    spec.update(
        native_relations=sorted(native),
        comparison_sha256=digest((output / "comparison.json").read_bytes()),
        conversion_fixtures=[
            "tests/resources/ontology_relations/relations.json",
            "tests/resources/ontology_offline_context/prefixes.json",
            *[f"tests/resources/native_ro_retention/{name}.json" for name in ("pato", "uberon", "envo", "mondo")],
        ],
    )
    with (output / "runtime-probe-spec.json").open("x", encoding="utf-8") as stream:
        json.dump(spec, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return summary


def runtime_probe(argv):
    """Exercise actual installed BMT/LinkML/KGX against local candidate bytes in a fresh offline process."""
    import importlib.metadata
    import os
    import socket

    parser = argparse.ArgumentParser(description=runtime_probe.__doc__)
    parser.add_argument("--schema-dir", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    require(output.is_relative_to(EVIDENCE.resolve()), f"Probe output must be under {EVIDENCE}")
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT))
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    admission = SourceAdmission()
    specification = admission.read_json(args.spec)
    model_path = args.schema_dir.resolve() / "biolink-model.yaml"
    model = read_yaml(admission.capture(model_path, retain=True))
    bundle = load_bundle(args.schema_dir, model["version"], admission)
    implementation = {}
    for relative in (
        "kg_microbe/utils/biolink_model.py",
        "kg_microbe/merge_utils/local_context.py",
        "kg_microbe/transform_utils/ontologies/ontologies_transform.py",
        "kg_microbe/transform_utils/constants.py",
    ):
        implementation[relative] = admission.capture(ROOT / relative)
    implementation[str(Path(__file__).relative_to(ROOT))] = admission.capture(Path(__file__))
    versions = {
        name: importlib.metadata.version(name)
        for name in ("biolink-model", "bmt", "kgx", "linkml", "linkml-runtime", "click")
    }
    result = {
        "status": "running",
        "python": sys.version,
        "executable": sys.executable,
        "packages": versions,
        "implementation": implementation,
        "schema": {key: value for key, value in bundle.items() if key not in {"documents", "definitions"}},
        "specification_identity": admission.identities[args.spec.resolve()],
        "network_attempts": [],
        "classes": {},
        "slots": {},
        "native_mappings": {},
        "strict_predicates": {},
        "conversions": {},
        "scientific_acceptance": False,
        "release_authorized": False,
    }

    def deny_network(*arguments, **kwargs):
        """Fail and retain any network attempt instead of satisfying it with fabricated data."""
        result["network_attempts"].append(repr(arguments)[:300])
        raise RuntimeError("Network prohibited in Biolink runtime compatibility probe")

    socket.getaddrinfo = deny_network
    socket.gethostbyname = deny_network
    socket.gethostbyname_ex = deny_network
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    os.environ["KG_MICROBE_BIOLINK_MODEL"] = str(model_path)
    os.environ["KG_MICROBE_BIOLINK_PREDICATE_MAP"] = str(args.schema_dir.resolve() / "predicate_mapping.yaml")
    try:
        import requests

        requests.sessions.Session.request = deny_network
        from kg_microbe.utils.biolink_model import prepare_kgx

        prepare_kgx()
        from bmt import Toolkit
        from linkml_runtime.dumpers import json_dumper

        toolkit = Toolkit()

        def serialized(element):
            """Retain the runtime's induced definition, with absence separate from an empty record."""
            return json.loads(json_dumper.dumps(element)) if element is not None else None

        for name in specification["classes"]:
            element = toolkit.get_element(name)
            slots = toolkit.view.class_slots(name) if element is not None else []
            result["classes"][name] = {
                "element": serialized(element),
                "ancestors_with_mixins": sorted(toolkit.get_ancestors(name, reflexive=True, mixin=True)),
                "induced_slots": {slot: serialized(toolkit.view.induced_slot(slot, name)) for slot in sorted(slots)},
            }
        for name in specification["slots"]:
            element = toolkit.get_element(name)
            result["slots"][name] = {
                "element": serialized(element),
                "ancestors_with_mixins": sorted(toolkit.get_ancestors(name, reflexive=True, mixin=True)),
                "induced_slot": serialized(toolkit.view.induced_slot(name)) if element is not None else None,
            }
        for relation in specification["native_relations"]:
            result["native_mappings"][relation] = {
                "selected": toolkit.get_element_by_mapping(relation, formatted=False),
                "all": sorted(toolkit.get_all_elements_by_mapping(relation)),
            }
        from kgx.validator import Validator

        from kg_microbe.merge_utils.local_context import local_prefix_context
        from kg_microbe.transform_utils.ontologies.ontologies_transform import _run_kgx_transform

        with local_prefix_context():
            validator = Validator()
        predicates = set(specification["native_relations"]) | {
            "biolink:" + name.replace(" ", "_") for name in specification["slots"]
        }
        for predicate in sorted(predicates):
            validator.clear_errors()
            validator.validate_edge_predicate(
                "fixture:subject", "fixture:object", {"predicate": predicate}, toolkit=toolkit
            )
            result["strict_predicates"][predicate] = json.loads(json.dumps(validator.errors, default=str))
        for relative in specification["conversion_fixtures"]:
            source = ROOT / relative
            admission.capture(source)
            require(
                source.resolve().is_relative_to(ROOT / "tests/resources"),
                "Probe conversion input must be a committed test fixture",
            )
            target = output / "conversions" / source.parent.name / source.stem
            target.parent.mkdir(parents=True, exist_ok=True)
            _run_kgx_transform(inputs=[source], input_format="obojson", output=target, output_format="tsv")
            members = {}
            for kind in ("nodes", "edges"):
                path = target.with_name(f"{target.name}_{kind}.tsv")
                with path.open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.DictReader(stream, delimiter="\t"))
                members[kind] = {
                    "path": str(path),
                    "identity": admission.capture(path),
                    "rows": len(rows),
                    "semantic_rows": sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)),
                }
            result["conversions"][relative] = {"input": admission.identities[source.resolve()], "outputs": members}
        admission.verify()
        require(not result["network_attempts"], "Runtime attempted network access")
        result.update(status="completed_review_required", inputs_unchanged=True)
    except Exception as error:  # noqa: BLE001 - retain real compatibility failures with no fallback
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    with (output / "runtime-probe.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {"status": result["status"], "output": str(output / "runtime-probe.json"), "error": result.get("error")}
        )
    )
    return int(result["status"] == "failed")


def main(argv=None):
    """Compare supplied local epochs and preserve a fresh evidence set only after unchanged-input checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-dir", type=Path, required=True)
    parser.add_argument("--new-dir", type=Path, required=True)
    parser.add_argument("--old-version", default="4.4.2")
    parser.add_argument("--new-version", default="4.4.6")
    parser.add_argument("--old-receipt", type=Path)
    parser.add_argument("--new-receipt", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--nodes", type=Path)
    parser.add_argument("--edges", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    admission = SourceAdmission()
    try:
        require(args.old_dir.resolve() != args.new_dir.resolve(), "Old and new schema directories must differ")
        old, new = (
            load_bundle(directory, version, admission)
            for directory, version in ((args.old_dir, args.old_version), (args.new_dir, args.new_version))
        )
        graph = graph_inventory(args.archive, args.nodes, args.edges, admission)
        result = compare(old, new, ROOT, admission, graph)
        result["acquisition_receipts"] = {
            name: {"path": str(path.resolve()), "identity": admission.capture(path)}
            for name, path in (("old", args.old_receipt), ("new", args.new_receipt))
            if path
        }
        result["implementation"] = {
            "path": str(Path(__file__).resolve()),
            "identity": admission.capture(Path(__file__)),
        }
        admission.verify()
        result["inputs_unchanged"] = True
        print(json.dumps(write_outputs(args.output_dir, result), indent=2, sort_keys=True))
        return 0
    except Exception as error:  # noqa: BLE001 - a failed comparison cannot produce acceptance evidence
        print(
            json.dumps(
                {"status": "failed", "error": f"{type(error).__name__}: {error}", "scientific_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(runtime_probe(sys.argv[2:]) if sys.argv[1:2] == ["runtime-probe"] else main())
