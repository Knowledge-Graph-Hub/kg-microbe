#!/usr/bin/env python3
"""Read-only Rhea label preview using actual family_rows and preserved local authorities."""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import ExitStack
from pathlib import Path


def identity(path):
    """Hash a selected local file without changing it."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def source_owl_missing(path, identifiers):
    """Distinguish absent declarations from DB-only gaps, without ontology adapters."""
    from lxml import etree

    rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    rdfs = "http://www.w3.org/2000/01/rdf-schema#"
    targets = {}
    for identifier in identifiers:
        prefix, local = identifier.split(":", 1)
        iri = (
            "https://bioregistry.io/eccode:" + local
            if prefix == "EC"
            else "http://purl.obolibrary.org/obo/" + prefix + "_" + local
        )
        targets[iri] = identifier
    result = {identifier: {"declaration_present": False, "labels": []} for identifier in identifiers}
    for _, element in etree.iterparse(
        str(path),
        events=("end",),
        tag="{http://www.w3.org/2002/07/owl#}Class",
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
    ):
        iri = element.get("{" + rdf + "}about")
        if iri in targets:
            result[targets[iri]] = {
                "declaration_present": True,
                "labels": [child.text or "" for child in element.findall("{" + rdfs + "}label")],
            }
        element.clear()
        while element.getprevious() is not None:
            del element.getparent()[0]
    return result


def preview(candidate, raw):
    """Exercise exact projection target selection, while making no toolchain-reuse claim."""
    from kg_microbe.transform_utils.rhea_mappings.label_inputs import (
        LABEL_DATABASES,
        _require_standalone,
        _validate_schema,
    )
    from kg_microbe.transform_utils.rhea_mappings.native_graph import family_rows
    from kg_microbe.transform_utils.rhea_mappings.native_rdf import load_native_rdf
    from kg_microbe.transform_utils.rhea_mappings.reaction_families import (
        load_reaction_families,
        validate_family_cohort,
    )

    paths = [candidate / "rhea-directions.tsv", candidate / "rhea.rdf.gz"]
    paths += [raw / filename for filename, _, _ in LABEL_DATABASES.values()]
    paths += [raw / filename for filename in ("chebi.owl", "go.owl", "ec.owl")]
    before = {str(path): identity(path) for path in paths}
    with (candidate / "rhea-directions.tsv").open() as stream:
        families = load_reaction_families(stream)
    with (candidate / "rhea.rdf.gz").open("rb") as stream:
        native = load_native_rdf(stream, compressed=True)
    cohort = validate_family_cohort(families, native.reactions)
    selected, missing, bad = {}, {}, {}
    rows = Counter()
    with ExitStack() as stack:
        connections = {}
        for filename, prefix, ontology in LABEL_DATABASES.values():
            path = raw / filename
            _require_standalone(path)
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
            stack.callback(connection.close)
            connection.execute("PRAGMA query_only=ON")
            _validate_schema(connection, ontology)
            connections[prefix] = connection

        def lookup(identifier):
            if identifier in selected:
                return selected[identifier]
            prefix = identifier.split(":", 1)[0] + ":"
            records = (
                connections[prefix]
                .execute(
                    "SELECT object, value FROM statements WHERE subject=? AND predicate='rdfs:label'", (identifier,)
                )
                .fetchall()
            )
            values = {value for _, value in records if value}
            if (
                any(
                    obj not in (None, "") or (value is not None and not isinstance(value, str))
                    for obj, value in records
                )
                or len(values) > 1
            ):
                bad[identifier] = records
            value = next(iter(values), "")
            selected[identifier] = value
            if not value:
                missing[identifier] = records
            return value

        for family in families:
            for kind, _ in family_rows(family, native, lookup):
                rows[kind] += 1
        for filename, _, _ in LABEL_DATABASES.values():
            _require_standalone(raw / filename)
    source_checks = {}
    for prefix, filename in [("CHEBI:", "chebi.owl"), ("GO:", "go.owl"), ("EC:", "ec.owl")]:
        identifiers = [identifier for identifier in missing if identifier.startswith(prefix)]
        source_checks.update(source_owl_missing(raw / filename, identifiers))
    after = {str(path): identity(path) for path in paths}
    if before != after:
        raise ValueError("Preview input changed")
    return {
        "inputs": before,
        "inputs_unchanged": True,
        "projection_function": "family_rows",
        "families": len(families),
        "cohort_family_count": cohort["families"],
        "projected_row_occurrences": dict(rows),
        "selected_label_counts": dict(Counter(identifier.split(":", 1)[0] for identifier in selected)),
        "missing_label_counts": dict(Counter(identifier.split(":", 1)[0] for identifier in missing)),
        "missing_labels": missing,
        "malformed_or_ambiguous_labels": bad,
        "source_owl_missing_label_assessment": source_checks,
        "all_selected_identifiers_have_unambiguous_labels": not missing and not bad,
        "database_build_or_reuse_receipts_validated": False,
        "raw_mutated": False,
        "production_run": False,
        "release_ready": False,
    }


def main():
    """Write new preview evidence; this does not admit a producer or activate a source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--authority-raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = preview(args.candidate_dir, args.authority_raw)
    result["helper_sha256"] = identity(Path(__file__))["sha256"]
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"inputs", "missing_labels", "source_owl_missing_label_assessment"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
