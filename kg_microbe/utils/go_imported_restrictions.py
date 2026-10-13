"""Quarantine finite unsupported imported class restrictions without changing observations."""

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from kg_microbe.transform_utils.constants import (
    GO_REFERENCE_CONTEXT_COLUMN,
    HAS_INPUT_PREDICATE,
    HAS_OUTPUT_PREDICATE,
    HAS_PARTICIPANT_PREDICATE,
    IN_TAXON_PREDICATE,
    OBJECT_COLUMN,
    OCCURS_IN_PREDICATE,
    ORIGINAL_SUBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    RELATED_TO_PREDICATE,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.release_binding import is_release_source, semsql_go_release

POLICY_FILE = Path(__file__).resolve().parents[2] / "mappings/go_imported_subject_restrictions.json"
REVIEWED_POLICY_SHA256 = "f8d02767086a378f3d983070ad0f4627614d3cda5dc399b94ab21d98574d2579"
# Version 5 binds go.db to its GO release and selected content, not its file bytes (#1420).
POLICY_VERSION = 5
RUNTIME_VERSION = 6
INVENTORY_KEY = "go_imported_restriction_inventory"
INPUTS_KEY = "go_imported_restriction_inputs"
POLICY_ROLE = "go_imported_restriction_policy"
OWL_ROLE = "go_imported_restriction_pato_owl"
GO_ROLE = "go_imported_restriction_go_db"
GO_SOURCE_ROLE = "go_imported_restriction_go_owl"
ORIGINAL_INPUT_ROLE_PREFIX = "go_imported_restriction_input:"
ORIGINAL_INPUT_DIRECTORY = ".go-restriction-inputs"
AUDIT_KIND = "quarantined_imported_subject_restriction"
DISPOSITION = "unsupported_imported_subject_restriction"
EVIDENCE_COLUMN = "native_restriction_context"
_SOURCE = "infores:pato"
# Exact native subject/relation/object -> emitted predicate/replacement. This is
# a reviewed finite set, not a general obsolete-subject replacement heuristic.
_CLAIMS = {
    ("GO:0006082", "RO:0004007", "CHEBI:64709"): (HAS_PARTICIPANT_PREDICATE, "GO:0008152"),
    ("GO:0043603", "RO:0004007", "CHEBI:32988"): (HAS_PARTICIPANT_PREDICATE, "GO:0008152"),
    ("GO:0006643", "BFO:0000066", "GO:0016020"): (OCCURS_IN_PREDICATE, "GO:0006629"),
    ("GO:0015695", "RO:0004009", "CHEBI:25697"): (HAS_INPUT_PREDICATE, "GO:0055085"),
    ("GO:0015711", "RO:0004009", "CHEBI:25696"): (HAS_INPUT_PREDICATE, "GO:0055085"),
    ("GO:0016053", "RO:0004008", "CHEBI:64709"): (HAS_OUTPUT_PREDICATE, "GO:0008152"),
    ("GO:0042886", "RO:0004009", "CHEBI:32988"): (HAS_INPUT_PREDICATE, "GO:0071705"),
    ("GO:0043604", "RO:0004008", "CHEBI:32988"): (HAS_OUTPUT_PREDICATE, "GO:0009058"),
    ("GO:0062023", "RO:0002162", "NCBITaxon:33208"): (IN_TAXON_PREDICATE, "GO:0031012"),
    ("GO:0098660", "RO:0004009", "CHEBI:36914"): (HAS_INPUT_PREDICATE, "GO:0055085"),
    ("GO:0098662", "RO:0004009", "CHEBI:36915"): (HAS_INPUT_PREDICATE, "GO:0055085"),
    ("GO:0055108", "RO:0002339", "GO:0030133"): (RELATED_TO_PREDICATE, "GO:0006893"),
    ("GO:0006903", "RO:0002162", "NCBITaxon:2759"): (IN_TAXON_PREDICATE, "GO:0016192"),
    ("GO:0048199", "RO:0004009", "GO:0005798"): (HAS_INPUT_PREDICATE, "GO:0048193"),
    ("GO:0055108", "BFO:0000066", "GO:0005737"): (OCCURS_IN_PREDICATE, "GO:0006893"),
}


def _compact_native(identifier):
    """Recognize only canonical OBO spellings needed by the exact reviewed claims."""
    for prefix in ("GO", "CHEBI", "RO", "BFO", "NCBITaxon"):
        iri = f"http://purl.obolibrary.org/obo/{prefix}_"
        if isinstance(identifier, str) and identifier.startswith(iri):
            return prefix + ":" + identifier[len(iri) :]
    return identifier


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate imported GO restriction evidence key: {key}")
        result[key] = value
    return result


def _original_input_role(member, quoting):
    """Encode the original member, literal dialect and digest in its immutable read role."""
    descriptor = {"file": member["file"], "sha256": member["sha256"], "quoting": quoting}
    role = ORIGINAL_INPUT_ROLE_PREFIX + base64.urlsafe_b64encode(_json(descriptor).encode()).decode()
    _original_input_descriptor(role)
    return role


def _original_input_descriptor(role):
    """Recover scope from an admitted read role, even when all its audit rows disappear."""
    if not isinstance(role, str) or not role.startswith(ORIGINAL_INPUT_ROLE_PREFIX):
        raise ValueError("Invalid original GO input role")
    encoded = role[len(ORIGINAL_INPUT_ROLE_PREFIX) :]
    descriptor = json.loads(base64.b64decode(encoded, altchars=b"-_", validate=True), object_pairs_hook=_unique_object)
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != {"file", "sha256", "quoting"}
        or not isinstance(descriptor["file"], str)
        or Path(descriptor["file"]).name != descriptor["file"]
        or descriptor["file"] in {"", ".", ".."}
        or any(character in descriptor["file"] for character in "\x00\r\n")
        or not isinstance(descriptor["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", descriptor["sha256"]) is None
        or type(descriptor["quoting"]) is not int
        or descriptor["quoting"] not in {csv.QUOTE_NONE, csv.QUOTE_MINIMAL, csv.QUOTE_ALL}
        or base64.urlsafe_b64encode(_json(descriptor).encode()).decode() != encoded
    ):
        raise ValueError("Malformed original GO input descriptor")
    return descriptor


def _original_input_path(role, identity):
    """Refuse rebased hashes and symlinked owned snapshot components without rewriting them."""
    descriptor = _original_input_descriptor(role)
    if not isinstance(identity, dict) or set(identity) != {"path", "sha256"}:
        raise ValueError("Malformed original GO input identity")
    path = Path(identity["path"])
    if (
        identity["sha256"] != descriptor["sha256"]
        or path.name != descriptor["sha256"] + ".tsv"
        or path.parent.name != ORIGINAL_INPUT_DIRECTORY
        or path.is_symlink()
        or path.parent.is_symlink()
        or not path.is_file()
    ):
        raise ValueError("Original GO input snapshot is missing, rebound or symlinked")
    return path


def _stream_original_rows(stream, quoting):
    """Parse exactly the admitted stream, preserving quoted records and original data-row ordinals."""
    reader = csv.DictReader(stream, delimiter="\t", quoting=quoting)
    if (
        not reader.fieldnames
        or len(reader.fieldnames) != len(set(reader.fieldnames))
        or not {SUBJECT_COLUMN, PREDICATE_COLUMN, OBJECT_COLUMN} <= set(reader.fieldnames)
    ):
        raise ValueError("Malformed original GO input header")
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Malformed original GO input record width")
        yield row


def _retain_original_input(source, expected_digest, directory):
    """Atomically publish one exact input object without overwriting or following owned symlinks."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission

    directory = Path(directory).absolute()
    if directory.name != ORIGINAL_INPUT_DIRECTORY:
        raise ValueError("Unexpected original GO snapshot directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Original GO snapshot directory is a symlink")
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".input-" + uuid.uuid4().hex
    destination = expected_digest + ".tsv"
    admission = SourceAdmission()
    created = False
    try:
        if admission.capture(source)["sha256"] != expected_digest:
            raise ValueError("Original GO member changed before snapshot capture")
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd
        )
        created = True
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as output, Path(source).open("rb") as input_stream:
            for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected_digest:
            raise ValueError("Original GO member changed while being captured")
        admission.verify(metadata_only=True)
        try:
            os.link(temporary, destination, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        except FileExistsError:
            existing_fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            with os.fdopen(existing_fd, "rb") as existing:
                if not stat.S_ISREG(os.fstat(existing.fileno()).st_mode):
                    raise ValueError("Original GO snapshot object is not a regular file") from None
                existing_digest = hashlib.sha256()
                for block in iter(lambda: existing.read(1024 * 1024), b""):
                    existing_digest.update(block)
                if existing_digest.hexdigest() != expected_digest:
                    raise ValueError("Original GO snapshot object conflicts with its digest") from None
        if directory.is_symlink() or (directory.stat().st_dev, directory.stat().st_ino) != (
            os.fstat(directory_fd).st_dev,
            os.fstat(directory_fd).st_ino,
        ):
            raise ValueError("Original GO snapshot directory changed during capture")
        os.fsync(directory_fd)
    finally:
        if created:
            os.unlink(temporary, dir_fd=directory_fd)
        os.close(directory_fd)
    return directory / destination


def load_policy(stream):
    """Anchor both native witnesses and all authority pins independently of mutable receipts."""
    policy = json.load(stream, object_pairs_hook=_unique_object)
    if _digest(_json(policy).encode()) != REVIEWED_POLICY_SHA256:
        raise ValueError("Unreviewed imported GO subject-restriction policy")
    if (
        policy["version"] != POLICY_VERSION
        or policy["disposition"] != DISPOSITION
        or {
            (
                row[SUBJECT_COLUMN],
                row[RELATION_COLUMN],
                row[OBJECT_COLUMN],
                row[PREDICATE_COLUMN],
                row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN],
                row["replacement"],
            )
            for row in policy["records"]
        }
        != {(*key, predicate, _SOURCE, replacement) for key, (predicate, replacement) in _CLAIMS.items()}
        or len(policy["records"]) != len(_CLAIMS)
        or len({(replacement, key[1], key[2]) for key, (_, replacement) in _CLAIMS.items()}) != len(_CLAIMS)
        or set(policy["sources"]) != {"pato.owl", "go.db"}
        or set(policy["sources"]["pato.owl"]) != {"sha256"}
        or set(policy["sources"]["go.db"]) != {"release", "source"}
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(policy["sources"]["go.db"]["release"]))
        or not is_release_source(policy["sources"]["go.db"]["source"])
        or policy["sources"]["go.db"]["source"]["file"] != "go.owl"
        or not _valid_blank_nodes(policy)
    ):
        raise ValueError("Invalid finite imported GO subject-restriction policy")
    return policy


def _reachable_blank_nodes(policy, blank_nodes):
    """Return every blank node the selected rows reach, directly or through recorded blank-node statements."""
    pending = [row["object"] for row in _metadata_rows(policy) if _is_blank(row["object"])]
    reached = set()
    while pending:
        label = pending.pop()
        if label not in reached:
            reached.add(label)
            statements = blank_nodes.get(label)
            if isinstance(statements, list):
                pending.extend(
                    statement["object"]
                    for statement in statements
                    if isinstance(statement, dict) and _is_blank(statement.get("object"))
                )
    return reached


def _valid_blank_nodes(policy):
    """Require the reviewed statements of exactly the blank nodes the selected rows reach, nested ones included."""
    blank_nodes = policy.get("blank_nodes")
    return (
        isinstance(blank_nodes, dict)
        and set(blank_nodes) == _reachable_blank_nodes(policy, blank_nodes)
        and all(
            isinstance(statements, list)
            and statements
            and all(
                isinstance(statement, dict)
                and set(statement) == {"predicate", "object", "value"}
                and isinstance(statement["predicate"], str)
                and all(statement[field] is None or isinstance(statement[field], str) for field in ("object", "value"))
                for statement in statements
            )
            for statements in blank_nodes.values()
        )
    )


def identify(row):
    """Recognize exact native claims and their canonical shadows, never a prefix-wide class."""
    if row.get(PRIMARY_KNOWLEDGE_SOURCE_COLUMN) != _SOURCE:
        return None
    subject, obj = _compact_native(row.get(SUBJECT_COLUMN)), _compact_native(row.get(OBJECT_COLUMN))
    relation = _compact_native(row.get(RELATION_COLUMN))
    key = (subject, relation, obj)
    if key in _CLAIMS:
        original, style = subject, "native_subject"
    else:
        matches = [
            claim
            for claim, (_, replacement) in _CLAIMS.items()
            if (replacement, claim[1], claim[2]) == (subject, relation, obj)
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("Ambiguous finite imported GO canonical shadow")
        key = matches[0]
        original, style = key[0], "previously_normalized"
    if row.get(PREDICATE_COLUMN) != _CLAIMS[key][0]:
        raise ValueError("Protected imported GO restriction has an unexpected predicate")
    return original, style


def _claim_key(row, original):
    """Select a complete finite claim; sharing a subject never selects a sibling relation."""
    return original, _compact_native(row.get(RELATION_COLUMN)), _compact_native(row.get(OBJECT_COLUMN))


def _policy_record(policy, row, original):
    """Recover the exact reviewed witness from the original full claim, not just its subject."""
    key = _claim_key(row, original)
    return next(
        record
        for record in policy["records"]
        if (record[SUBJECT_COLUMN], record[RELATION_COLUMN], record[OBJECT_COLUMN]) == key
    )


def _history_event(column, literal, canonical, chain, go_identity):
    """Describe one existing GO-normalizer event without changing any source assertion."""
    return {
        "column": column,
        "original_id": literal,
        "canonical_id": canonical,
        "replacement_chain": chain,
        "authority": go_identity["path"],
        "authority_sha256": go_identity["sha256"],
    }


def validate_history(row, original, style, go_identity):
    """Do not manufacture a historical subject from an unproven current-class assertion."""
    history = json.loads(row.get(GO_REFERENCE_CONTEXT_COLUMN) or "[]", object_pairs_hook=_unique_object)
    if not isinstance(history, list):
        raise ValueError("Malformed imported GO subject-replacement history")
    previous = row.get(ORIGINAL_SUBJECT_COLUMN, "")
    key = _claim_key(row, original)
    replacement = _CLAIMS[key][1]
    obj = key[2]
    if style == "native_subject":
        if (
            previous not in ("", row[SUBJECT_COLUMN])
            or history
            or (obj.startswith("GO:") and row.get("original_object", "") not in ("", row[OBJECT_COLUMN]))
        ):
            raise ValueError("Contradictory native imported GO subject-replacement history")
        return
    expected = [_history_event(SUBJECT_COLUMN, previous, replacement, [original, replacement], go_identity)]
    previous_object = row.get("original_object", "")
    if obj.startswith("GO:") and previous_object:
        if _compact_native(previous_object) != obj or previous_object == obj:
            raise ValueError("Contradictory imported GO object-spelling history")
        expected.append(_history_event(OBJECT_COLUMN, previous_object, obj, [obj], go_identity))
    if _compact_native(previous) != original or history != expected:
        raise ValueError("Missing or forged imported GO subject-replacement history")


def expected_candidate(row, original, style, go_identity):
    """Describe exactly the existing identifier projection, without asserting it is valid."""
    validate_history(row, original, style, go_identity)
    candidate = dict(row)
    key = _claim_key(row, original)
    replacement = _CLAIMS[key][1]
    projections = [
        (SUBJECT_COLUMN, replacement, [original, replacement] if style == "native_subject" else [replacement])
    ]
    if key[2].startswith("GO:"):
        projections.append((OBJECT_COLUMN, key[2], [key[2]]))
    history = json.loads(row.get(GO_REFERENCE_CONTEXT_COLUMN) or "[]")
    for column, canonical, chain in projections:
        if row[column] == canonical:
            continue
        candidate[column] = canonical
        candidate["original_" + column] = row.get("original_" + column) or row[column]
        history.append(_history_event(column, row[column], canonical, chain, go_identity))
        candidate[GO_REFERENCE_CONTEXT_COLUMN] = _json(history)
    return candidate


def _is_blank(value):
    """Return whether a statement object is an RDF blank node, as rdftab writes one (``_:riog00055663``)."""
    return isinstance(value, str) and value.startswith("_:")


def _blank_node_key(label, describe, seen=()):
    """
    Name a blank node by what it states, not by its label.

    rdftab numbers blank nodes as it reads (``_:riog00055663``), so a label belongs to one
    local build of go.db, not to GO. The key digests the node's own statements, with each
    nested blank node replaced by its key in turn, so every build of the same release
    gives the same key and a different restriction gives a different one (#1514).

    :param label: The blank node's label in one database or in the policy.
    :param describe: Returns that node's ``(predicate, object, value)`` statements.
    :param seen: Blank nodes already being keyed, to refuse a cycle.
    :return: A label-free ``_:``-prefixed key.
    :raises ValueError: When the node states nothing or is part of a cycle.
    """
    if label in seen:
        raise ValueError(f"Cyclic GO blank node: {label}")
    statements = describe(label)
    if not statements:
        raise ValueError(f"GO blank node has no statements: {label}")
    keyed = [
        [predicate, _blank_node_key(obj, describe, (*seen, label)) if _is_blank(obj) else obj, value]
        for predicate, obj, value in statements
    ]
    return "_:" + _digest(_json(sorted(keyed, key=_json)).encode())


def _label_free(rows, describe):
    """Replace each blank-node object with its key, so rows compare by content."""
    return [
        {**row, "object": _blank_node_key(row["object"], describe)} if _is_blank(row["object"]) else row for row in rows
    ]


def _metadata_rows(policy):
    """Use each complete native subject statement multiset once across shared targets."""
    by_subject = {}
    for block in [policy["canonical_go_metadata"], *[record["selected_go_metadata"] for record in policy["records"]]]:
        current = {}
        for row in block:
            current.setdefault(row[SUBJECT_COLUMN], []).append(row)
        for identifier, rows in current.items():
            if identifier in by_subject and sorted(map(_json, by_subject[identifier])) != sorted(map(_json, rows)):
                raise ValueError("Inconsistent complete imported GO metadata witnesses")
            by_subject[identifier] = rows
    return [row for identifier in sorted(by_subject) for row in by_subject[identifier]]


class ImportedGoRestrictionGuard:
    """Own exact admitted evidence and its live original-role binding through finalization."""

    def __init__(self, authority, *, consume_input=None, normalization_input_dir=None):
        """Remain inert for ordinary GO references and unrelated class axioms."""
        self.authority = authority
        self.consume_input = consume_input
        self.identities = {}
        self.policy = None
        self._prepared_bindings_json = None
        self._audit_contract_json = None
        self._audit_name = None
        self.normalization_input_dir = normalization_input_dir
        self._input_roles_by_member = {}
        self._fresh_input_members = set()
        self._inputs_sealed = False

    @contextmanager
    def _open(self, role, path):
        """Use producer snapshots, or an independently guarded private snapshot for direct callers."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        path = Path(path).resolve()
        if self.consume_input is not None:
            with self.consume_input(role, path) as stream:
                yield stream
            return
        guard = SourceAdmission()
        expected = guard.capture(path)
        with NamedTemporaryFile() as temporary:
            with path.open("rb") as source:
                shutil.copyfileobj(source, temporary)
            temporary.flush()
            with open(temporary.name, encoding="utf-8", newline="") as stream:
                if _digest(stream.buffer.read()) != expected["sha256"]:
                    raise ValueError("Imported GO native snapshot changed while being copied")
                stream.seek(0)
                yield stream
            guard.verify()

    def _remember(self, role, path, digest):
        identity = {"path": str(Path(path).resolve()), "sha256": digest}
        if role in self.identities and self.identities[role] != identity:
            raise ValueError("Imported GO restriction witness rebound during normalization")
        self.identities[role] = identity

    def prepare(self):
        """Read actual immutable OWL/SQLite evidence; filenames or an ID replacement are not proof."""
        if self.policy is not None:
            self.verify_prepared()
            return
        with self._open(POLICY_ROLE, POLICY_FILE) as stream:
            content = stream.buffer.read()
            policy = load_policy(io.StringIO(content.decode("utf-8")))
        self._remember(POLICY_ROLE, POLICY_FILE, _digest(content))
        database = Path(self.authority.authority_path)
        if not self.authority.authority_path or not database.is_file():
            raise ValueError("Imported GO restrictions require the selected native GO database")
        owl = database.parent / "pato.owl"
        with self._open(OWL_ROLE, owl) as stream:
            content = stream.buffer.read()
        if _digest(content) != policy["sources"]["pato.owl"]["sha256"]:
            raise ValueError("Imported GO restriction native PATO authority changed")
        self._remember(OWL_ROLE, owl, _digest(content))
        for record in policy["records"]:
            iri = ("http://purl.obolibrary.org/obo/" + record[SUBJECT_COLUMN].replace(":", "_")).encode()
            witnesses = re.findall(
                rb'<owl:Class rdf:about="' + re.escape(iri) + rb'">.*?\n    </owl:Class>', content, re.DOTALL
            )
            expected_literal = record["native_class_xml"].encode()
            if (
                witnesses != [expected_literal.strip()]
                or content.count(expected_literal) != 1
                or _digest(expected_literal) != record["native_class_sha256"]
            ):
                raise ValueError("Imported GO native class restriction witness changed")
        with self._open(GO_ROLE, database) as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.buffer.read(1024 * 1024), b""):
                digest.update(block)
            if digest.hexdigest() != self.authority.authority_sha256:
                raise ValueError("Imported GO selected database differs from reviewed authority")
            with sqlite3.connect(Path(stream.name).as_uri() + "?mode=ro", uri=True) as connection:
                # The database is built locally, so its bytes are not pinned. It must
                # record the reviewed GO release, and its selected statements are
                # compared below (#1420).
                if semsql_go_release(connection) != policy["sources"]["go.db"]["release"]:
                    raise ValueError("Imported GO selected database is not the reviewed GO release")
                expected = _metadata_rows(policy)
                identifiers = sorted({row[SUBJECT_COLUMN] for row in expected})
                placeholders = ",".join("?" for _ in identifiers)
                actual = [
                    dict(zip(("subject", "predicate", "object", "value"), row, strict=True))
                    for row in connection.execute(
                        f"SELECT subject,predicate,object,value FROM statements WHERE subject IN ({placeholders})",  # noqa: S608 - placeholders only
                        identifiers,
                    )
                ]
                reviewed = policy["blank_nodes"]

                def stored(label):
                    """Return a blank node's statements in this database."""
                    return connection.execute(
                        "SELECT predicate,object,value FROM statements WHERE subject=?", (label,)
                    ).fetchall()

                def recorded(label):
                    """Return a blank node's statements as the policy recorded them."""
                    if label not in reviewed:
                        raise ValueError(f"Unreviewed GO blank node: {label}")
                    return [(row["predicate"], row["object"], row["value"]) for row in reviewed[label]]

                # Blank nodes compare by what they state, not their build-local labels (#1514).
                if sorted(map(_json, _label_free(actual, stored))) != sorted(
                    map(_json, _label_free(expected, recorded))
                ):
                    raise ValueError("Imported GO replacement metadata differs from native evidence")
                for table in ("edge", "entailed_edge"):
                    for (_, relation, obj), (_, replacement) in _CLAIMS.items():
                        if connection.execute(
                            f"SELECT 1 FROM {table} WHERE subject=? AND predicate=? AND object=? LIMIT 1",  # noqa: S608 - fixed local table names
                            (replacement, relation, obj),
                        ).fetchone():
                            raise ValueError(
                                "Imported GO restriction now has authority support; review finite disposition"
                            )
        self._remember(GO_ROLE, database, digest.hexdigest())
        source = policy["sources"]["go.db"]["source"]
        release = database.parent / source["file"]
        with self._open(GO_SOURCE_ROLE, release) as stream:
            release_digest = hashlib.sha256()
            for block in iter(lambda: stream.buffer.read(1024 * 1024), b""):
                release_digest.update(block)
        if release_digest.hexdigest() != source["sha256"]:
            raise ValueError("Imported GO release file differs from the reviewed release")
        self._remember(GO_SOURCE_ROLE, release, release_digest.hexdigest())
        from kg_microbe.utils.go_authority import GoAuthority

        expected_authority = GoAuthority.from_statements(
            [(row["subject"], row["predicate"], row["object"], row["value"]) for row in expected]
        )
        if any(
            self.authority.records.get(identifier) != record
            for identifier, record in expected_authority.records.items()
        ):
            raise ValueError("Prepared GO metadata does not match the consumed native database")
        self.policy = policy
        self._prepared_bindings_json = _json(self.identities)

    def verify_prepared(self):
        """Reject mutation of interpreted witnesses, not just drift of their source files."""
        if self.policy is not None:
            load_policy(io.StringIO(_json(self.policy)))
            if _json(self.identities) != self._prepared_bindings_json:
                raise ValueError("Prepared imported GO original witness bindings changed")
            for role, identity in self.identities.items():
                if role.startswith(ORIGINAL_INPUT_ROLE_PREFIX):
                    _original_input_path(role, identity)

    def bind_original_input(self, path, member, quoting, report_path):
        """Retain an active pre-rewrite member, never adopt an already rewritten output on repeat."""
        self.prepare()
        if self._inputs_sealed:
            raise ValueError("Original GO input inventory was already sealed")
        role = _original_input_role(member, quoting)
        previous = self._input_roles_by_member.get(member["file"])
        if previous is not None and previous != role:
            raise ValueError("Ambiguous original GO input member")
        directory = self.normalization_input_dir or Path(report_path).parent / ORIGINAL_INPUT_DIRECTORY
        snapshot = _retain_original_input(path, member["sha256"], directory)
        self._admit_original_input(role, {"path": str(snapshot.resolve()), "sha256": member["sha256"]})
        self._fresh_input_members.add(member["file"])

    def _admit_original_input(self, role, identity):
        """Actually read a retained input through the same consumed-input hook as native authorities."""
        self.verify_prepared()
        if self._inputs_sealed and self.identities.get(role) != identity:
            raise ValueError("Original GO input binding changed after preparation")
        descriptor = _original_input_descriptor(role)
        snapshot = _original_input_path(role, identity)
        previous = self._input_roles_by_member.get(descriptor["file"])
        if previous is not None and previous != role:
            raise ValueError("Original GO input member has contradictory input epochs")
        with self._open(role, snapshot) as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.buffer.read(1024 * 1024), b""):
                digest.update(block)
            if digest.hexdigest() != identity["sha256"]:
                raise ValueError("Original GO input stream differs from its admitted identity")
        self._remember(role, snapshot, identity["sha256"])
        self._input_roles_by_member[descriptor["file"]] = role
        self._prepared_bindings_json = _json(self.identities)

    def restore_original_inputs(self, context):
        """Cold checkpoint reuse reads the existing original objects; it never snapshots current output."""
        self.prepare()
        for role in (POLICY_ROLE, OWL_ROLE, GO_ROLE):
            if context["inputs"].get(role) != self.identities[role]:
                raise ValueError("Original GO checkpoint authority differs from the selected authority")
        for role, identity in context["inputs"].items():
            if role.startswith(ORIGINAL_INPUT_ROLE_PREFIX):
                self._admit_original_input(role, identity)

    def seal_original_inputs(self):
        """Finish admission before any output or exclusion audit is built."""
        self.verify_prepared()
        self._inputs_sealed = True

    def original_rows(self, path, quoting):
        """Parse active members from their actual admitted immutable stream; leave zero members unchanged."""
        from kg_microbe.utils.go_authority import _rows

        role = self._input_roles_by_member.get(Path(path).name)
        if role is None or Path(path).name not in self._fresh_input_members:
            yield from _rows(path, quoting)
            return
        descriptor = _original_input_descriptor(role)
        if descriptor["quoting"] != quoting:
            raise ValueError("Original GO input dialect changed")
        identity = self.identities[role]
        snapshot = _original_input_path(role, identity)
        with self._open(role, snapshot) as stream:
            yield from _stream_original_rows(stream, quoting)

    def inspect(self, row):
        """Return a validated finite disposition candidate before any graph row is written."""
        match = identify(row)
        if match is not None:
            self.prepare()
            validate_history(row, *match, self.identities[GO_ROLE])
        return match

    def evidence(self, row, candidate, match, *, member, ordinal):
        """Preserve native quantifier context alongside complete original and candidate rows."""
        self.verify_prepared()
        if candidate != expected_candidate(row, *match, self.identities[GO_ROLE]):
            raise ValueError("Imported GO candidate changed fields beyond identifier projection")
        role = self._input_roles_by_member.get(member["file"])
        if not self._inputs_sealed or role is None:
            raise ValueError("Original GO input was not admitted before quarantine")
        descriptor = _original_input_descriptor(role)
        if member != {key: descriptor[key] for key in ("file", "sha256")}:
            raise ValueError("Original GO input member differs from the pre-rewrite identity")
        return _native_evidence(self.policy, row, match, self.identities, member, ordinal, role)

    def verify_bindings(self, snapshots):
        """Keep immutable interpreted witnesses distinct from current mutable receipt contents."""
        from kg_microbe.utils.source_finalization import SourceFinalizationRequired

        self.verify_prepared()
        if (
            self._audit_contract_json is not None
            and not json.loads(self._audit_contract_json)["quarantined_occurrences"]
            and {POLICY_ROLE, OWL_ROLE, GO_ROLE} & snapshots.keys()
        ):
            raise SourceFinalizationRequired("Imported GO native evidence cannot have an erased quarantine inventory")
        for role, identity in self.identities.items():
            if snapshots.get(role) != identity:
                raise SourceFinalizationRequired(f"Imported GO restriction binding missing or changed: {role}")

    def verify_files(self):
        """Direct normalizer callers also refuse evidence drift before publishing staged outputs."""
        from kg_microbe.merge_utils.source_admission import SourceAdmission

        self.verify_prepared()
        guard = SourceAdmission()
        for identity in self.identities.values():
            if guard.capture(identity["path"])["sha256"] != identity["sha256"]:
                raise ValueError("Imported GO restriction evidence changed during normalization")
        guard.verify(metadata_only=True)

    def bind_audit(self, path):
        """Keep the independently observed complete finite inventory across source publication."""
        contract = audit_inventory([Path(path)], self.identities)
        self._audit_contract_json = _json(contract)
        self._audit_name = Path(path).name
        return contract

    def verify_output(self, output_dir):
        """Refuse partial or complete quarantine loss after staging and before publication."""
        from kg_microbe.utils.source_finalization import SourceFinalizationRequired

        if self._audit_contract_json is not None:
            actual = audit_inventory([Path(output_dir) / self._audit_name], self.identities)
            if _json(actual) != self._audit_contract_json:
                raise SourceFinalizationRequired("Imported GO quarantine inventory changed after preparation")


def _owned_inputs(snapshots):
    """Separate this finite guard's actual read roles from other producer dependencies."""
    if not isinstance(snapshots, dict) or any(not isinstance(role, str) for role in snapshots):
        raise ValueError("Malformed GO input roles")
    return {
        role: identity
        for role, identity in snapshots.items()
        if role in {POLICY_ROLE, OWL_ROLE, GO_ROLE, GO_SOURCE_ROLE} or role.startswith(ORIGINAL_INPUT_ROLE_PREFIX)
    }


def _native_evidence(policy, row, match, identities, member, ordinal, input_role):
    """Describe one original input occurrence and the independently pinned scientific witness."""
    record = _policy_record(policy, row, match[0])
    return _json(
        {
            "version": POLICY_VERSION,
            "original_subject": match[0],
            "input_style": match[1],
            "inputs": _owned_inputs(identities),
            "native_class_xml": record["native_class_xml"],
            "native_class_sha256": record["native_class_sha256"],
            "input_member": member,
            "input_record_ordinal": ordinal,
            "input_role": input_role,
        }
    )


def _expected_original_records(role, snapshots, policy, admission):
    """Stream the complete original member and reconstruct only its actual eligible occurrences."""
    from kg_microbe.utils.go_authority import _REPORT_FIELDS

    descriptor = _original_input_descriptor(role)
    identity = snapshots[role]
    path = admission.capture_resolution(_original_input_path, role, identity)
    if admission.capture(path)["sha256"] != descriptor["sha256"]:
        raise ValueError("Original GO snapshot bytes differ from the pre-rewrite member")
    member = {key: descriptor[key] for key in ("file", "sha256")}
    with path.open(encoding="utf-8", newline="") as stream:
        for ordinal, original in enumerate(_stream_original_rows(stream, descriptor["quoting"]), 1):
            match = identify(original)
            if match is None:
                continue
            candidate = expected_candidate(original, *match, snapshots[GO_ROLE])
            expected = dict.fromkeys(_REPORT_FIELDS, "")
            expected.update(
                {
                    "source_file": member["file"],
                    "record_kind": AUDIT_KIND,
                    "original_id": match[0],
                    "canonical_id": candidate[SUBJECT_COLUMN],
                    "disposition": DISPOSITION,
                    "authority": snapshots[GO_ROLE]["path"],
                    "authority_sha256": snapshots[GO_ROLE]["sha256"],
                    "original_record_json": json.dumps(original, ensure_ascii=False, sort_keys=True),
                    "candidate_record_json": json.dumps(candidate, ensure_ascii=False, sort_keys=True),
                    EVIDENCE_COLUMN: _native_evidence(policy, original, match, snapshots, member, ordinal, role),
                }
            )
            yield expected
    admission.verify(metadata_only=True)


def _verify_audit_metadata(row, snapshots, *, admission=None):
    """Verify finite metadata separately so whole-member admission scans each input only once."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    guard = admission if admission is not None else SourceAdmission()
    try:
        context = json.loads(row[EVIDENCE_COLUMN], object_pairs_hook=_unique_object)
        if set(context) != {
            "version",
            "original_subject",
            "input_style",
            "inputs",
            "native_class_xml",
            "native_class_sha256",
            "input_member",
            "input_record_ordinal",
            "input_role",
        }:
            raise ValueError("unexpected evidence fields")
        if (
            context["version"] != POLICY_VERSION
            or not {POLICY_ROLE, OWL_ROLE, GO_ROLE, GO_SOURCE_ROLE} < context["inputs"].keys()
            or context["inputs"] != _owned_inputs(snapshots)
        ):
            raise ValueError("missing evidence roles")
        descriptor = _original_input_descriptor(context["input_role"])
        _original_input_path(context["input_role"], context["inputs"][context["input_role"]])
        member = context["input_member"]
        if (
            set(member) != {"file", "sha256"}
            or member["file"] != row["source_file"]
            or not re.fullmatch(r"[0-9a-f]{64}", member["sha256"])
            or type(context["input_record_ordinal"]) is not int
            or context["input_record_ordinal"] < 1
            or member != {key: descriptor[key] for key in ("file", "sha256")}
        ):
            raise ValueError("missing original input occurrence identity")
        for role, identity in context["inputs"].items():
            if snapshots.get(role) != identity or set(identity) != {"path", "sha256"}:
                raise ValueError("missing or rebound original evidence")
            if guard.capture(identity["path"])["sha256"] != identity["sha256"]:
                raise ValueError("changed native evidence")
        policy_bytes = guard.capture(context["inputs"][POLICY_ROLE]["path"], retain=True)
        policy = load_policy(io.StringIO(policy_bytes.decode("utf-8")))
        if (
            context["inputs"][OWL_ROLE]["sha256"] != policy["sources"]["pato.owl"]["sha256"]
            or context["inputs"][GO_SOURCE_ROLE]["sha256"] != policy["sources"]["go.db"]["source"]["sha256"]
        ):
            raise ValueError("native evidence differs from reviewed pin")
        original = json.loads(row["original_record_json"], object_pairs_hook=_unique_object)
        candidate = json.loads(row["candidate_record_json"], object_pairs_hook=_unique_object)
        match = identify(original)
        if match is None or match != (context["original_subject"], context["input_style"]):
            raise ValueError("quarantine no longer describes the exact finite claim")
        if candidate != expected_candidate(original, *match, context["inputs"][GO_ROLE]):
            raise ValueError("quarantine candidate is not the recorded identifier projection")
        native = _policy_record(policy, original, match[0])
        if (
            context["native_class_xml"] != native["native_class_xml"]
            or context["native_class_sha256"] != native["native_class_sha256"]
        ):
            raise ValueError("native class quantifier evidence changed")
        if row["record_kind"] != AUDIT_KIND or row["disposition"] != DISPOSITION:
            raise ValueError("finite quarantine disposition changed")
        guard.verify(metadata_only=True)
        return context, policy
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        raise SourceFinalizationRequired("Invalid imported GO restriction quarantine evidence") from exc


def verify_audit_record(row, snapshots, *, admission=None):
    """Independently rejoin one original occurrence, including every native source field."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    guard = admission if admission is not None else SourceAdmission()
    context, policy = _verify_audit_metadata(row, snapshots, admission=guard)
    found = False
    try:
        for expected in _expected_original_records(context["input_role"], snapshots, policy, guard):
            occurrence = json.loads(expected[EVIDENCE_COLUMN])["input_record_ordinal"]
            if occurrence == context["input_record_ordinal"]:
                if row != expected:
                    raise ValueError("original source occurrence fields differ")
                found = True
        if not found:
            raise ValueError("original source occurrence is absent")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise SourceFinalizationRequired("Imported GO quarantine differs from its original input occurrence") from exc
    guard.verify(metadata_only=True)


def inventory_contract(count, digest):
    """Serialize a versioned exact finite-row inventory, including truthful empty cohorts."""
    return {"version": RUNTIME_VERSION, "quarantined_occurrences": count, "records_sha256": digest}


def _valid_inventory(value):
    return (
        isinstance(value, dict)
        and set(value) == {"version", "quarantined_occurrences", "records_sha256"}
        and type(value["version"]) is int
        and value["version"] == RUNTIME_VERSION
        and type(value["quarantined_occurrences"]) is int
        and value["quarantined_occurrences"] >= 0
        and isinstance(value["records_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", value["records_sha256"]) is not None
    )


def audit_inventory(paths, snapshots, *, admission=None):
    """Join actual finite rows to their whole-bundle checkpoint before certifying conservation."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    guard = admission if admission is not None else SourceAdmission()
    seen, digest, count = set(), hashlib.sha256(), 0
    actual_inputs = {}
    for path in paths:
        local_digest, local_count, checkpoint = hashlib.sha256(), 0, None
        guard.capture(path)
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t"):
                if None in row or None in row.values():
                    raise SourceFinalizationRequired("Malformed imported GO audit row")
                if row.get("record_kind") == "bundle_checkpoint":
                    if checkpoint is not None:
                        raise SourceFinalizationRequired("Duplicate GO bundle checkpoint")
                    try:
                        checkpoint = json.loads(row["bundle_fingerprint"], object_pairs_hook=_unique_object)
                        if not isinstance(checkpoint, dict):
                            raise ValueError("checkpoint is not an object")
                    except (TypeError, ValueError, KeyError) as exc:
                        raise SourceFinalizationRequired("Malformed GO bundle checkpoint") from exc
                if (
                    row.get("record_kind") == AUDIT_KIND
                    or row.get("disposition") == DISPOSITION
                    or row.get(EVIDENCE_COLUMN)
                ):
                    context, _ = _verify_audit_metadata(row, snapshots, admission=guard)
                    occurrence = (_json(context["input_member"]), context["input_record_ordinal"])
                    if occurrence in seen:
                        raise SourceFinalizationRequired("Duplicate imported GO restriction audit occurrence")
                    seen.add(occurrence)
                    encoded = (_json(row) + "\n").encode()
                    digest.update(encoded)
                    local_digest.update(encoded)
                    count += 1
                    local_count += 1
                    role = context["input_role"]
                    input_digest, input_count = actual_inputs.get(role, (hashlib.sha256(), 0))
                    input_digest.update(encoded)
                    actual_inputs[role] = (input_digest, input_count + 1)
        expected = inventory_contract(local_count, local_digest.hexdigest())
        stored = checkpoint.get(INVENTORY_KEY) if isinstance(checkpoint, dict) else None
        # Old empty GO reports remain readable during an explicit reprocessing,
        # but a nonempty finite audit requires its conservation checkpoint.
        new_runtime = bool(
            isinstance(checkpoint, dict)
            and isinstance(checkpoint.get("authority"), dict)
            and checkpoint.get("authority", {}).get("imported_subject_restriction_runtime_version") == RUNTIME_VERSION
        )
        legacy_empty = bool(
            not new_runtime
            and not local_count
            and not _owned_inputs(snapshots)
            and isinstance(stored, dict)
            and set(stored) == set(expected)
            and type(stored["version"]) is int
            and 0 < stored["version"] < RUNTIME_VERSION
            and type(stored["quarantined_occurrences"]) is int
            and stored["quarantined_occurrences"] == 0
            and stored["records_sha256"] == expected["records_sha256"]
        )
        if (stored is not None and not legacy_empty and (not _valid_inventory(stored) or stored != expected)) or (
            (local_count or new_runtime) and stored is None
        ):
            raise SourceFinalizationRequired("Imported GO quarantine checkpoint inventory changed or missing")
        if new_runtime and checkpoint.get(INPUTS_KEY) != _owned_inputs(snapshots):
            raise SourceFinalizationRequired("Original GO checkpoint read-role bindings changed or missing")
    try:
        owned = _owned_inputs(snapshots)
        roles = {role for role in owned if role.startswith(ORIGINAL_INPUT_ROLE_PREFIX)}
        if actual_inputs.keys() - roles:
            raise ValueError("quarantined member has no original input read role")
        if roles:
            policy_identity = owned[POLICY_ROLE]
            policy_bytes = guard.capture(policy_identity["path"], retain=True)
            if _digest(policy_bytes) != policy_identity["sha256"]:
                raise ValueError("original input policy identity changed")
            policy = load_policy(io.StringIO(policy_bytes.decode("utf-8")))
            for role in sorted(roles):
                expected_digest, expected_count = hashlib.sha256(), 0
                for expected in _expected_original_records(role, owned, policy, guard):
                    expected_digest.update((_json(expected) + "\n").encode())
                    expected_count += 1
                actual_digest, actual_count = actual_inputs.get(role, (hashlib.sha256(), 0))
                if not expected_count or (expected_count, expected_digest.hexdigest()) != (
                    actual_count,
                    actual_digest.hexdigest(),
                ):
                    raise ValueError("original finite occurrence set or complete source fields changed")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise SourceFinalizationRequired("Imported GO quarantine does not conserve original input occurrences") from exc
    guard.verify(metadata_only=True)
    return inventory_contract(count, digest.hexdigest())


def verify_recorded_restriction_inputs(report, report_path, *, admission=None):
    """Inspect actual mandatory GO audit bytes at admission without editing any graph."""
    from kg_microbe.merge_utils.source_admission import SourceAdmission
    from kg_microbe.utils.source_finalization import SourceFinalizationRequired

    guard = admission if admission is not None else SourceAdmission()
    paths = [
        Path(report_path).parent / name
        for name in report.get("audit_members", {})
        if name.endswith("go_reference_resolution.tsv")
    ]
    snapshots = report.get("consumed_inputs", {})
    actual = audit_inventory(paths, snapshots, admission=guard)
    try:
        for role, identity in _owned_inputs(snapshots).items():
            if not role.startswith(ORIGINAL_INPUT_ROLE_PREFIX):
                continue
            descriptor = _original_input_descriptor(role)
            expected = Path(report_path).parent / ORIGINAL_INPUT_DIRECTORY / (descriptor["sha256"] + ".tsv")
            if (
                descriptor["file"] not in report.get("members", {})
                or not descriptor["file"].endswith("edges.tsv")
                or Path(identity["path"]).absolute() != expected.absolute()
            ):
                raise ValueError("original GO input belongs to another member or source bundle")
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceFinalizationRequired("Original GO input source scope changed") from exc
    # An active canonical-shadow assertion cannot be made acceptable by
    # omitting its quarantine audit or original consumed-input roles.
    for name in report.get("members", {}):
        if not name.endswith("edges.tsv"):
            continue
        path = Path(report_path).parent / name
        guard.capture(path)
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
                try:
                    match = identify(row)
                except ValueError as exc:
                    raise SourceFinalizationRequired("Invalid finalized imported GO restriction predicate") from exc
                if match is not None:
                    raise SourceFinalizationRequired("Unsupported imported GO restriction remains in finalized graph")
    if not _valid_inventory(report.get(INVENTORY_KEY)) or report[INVENTORY_KEY] != actual:
        raise SourceFinalizationRequired("Imported GO quarantine source inventory changed or missing")
    if not actual["quarantined_occurrences"] and {POLICY_ROLE, OWL_ROLE, GO_ROLE} & snapshots.keys():
        raise SourceFinalizationRequired("Imported GO native evidence cannot have an erased quarantine inventory")
    if (
        report.get("summaries", {}).get("go", {}).get("quarantined_imported_subject_restrictions", 0)
        > actual["quarantined_occurrences"]
    ):
        raise SourceFinalizationRequired("Imported GO quarantine count contradicts source summary")
    guard.verify(metadata_only=True)
    return guard
