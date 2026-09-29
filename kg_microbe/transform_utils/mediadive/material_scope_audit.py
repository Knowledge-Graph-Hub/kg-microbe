"""Preserve finite Potato/extract grounding candidates separately from identity (#1236)."""

import csv
import gzip
import hashlib
import io
import json
import re
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import (
    CAS_RN_KEY,
    CAS_RN_PREFIX,
    COMPOUND_ID_KEY,
    COMPOUND_KEY,
    DATA_KEY,
    ID_COLUMN,
    RECIPE_KEY,
    SOLUTION_KEY,
    SOLUTIONS_KEY,
    SOURCE_ASSERTION_ID_COLUMN,
    SOURCE_RECORD_COLUMN,
)
from kg_microbe.utils.ingredient_identity import (
    IDENTITY_POLICY,
    _policy_target_key,
    _scope_key,
    ingredient_mapping_allowed,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.sssom_identity_policy import classify_mapping_row
from kg_microbe.utils.transform_fingerprint import _repo_root
from kg_microbe.utils.tsv_io import tsv_writer

AUDIT_FILENAME = "mediadive_material_scope_quarantine.tsv"
TARGET = "cas:93348-51-7"
AUTHORITY_LABEL = "zemiak, Solanum tuberosum aegrotans, extrakt"
AUTHORITY_URI = "https://www.mhsr.sk/uploads/files/Zwx10C5G.pdf#page=21"
UNIFIED_ROLE = "material_scope_unified"
POLICY_ROLE = "material_scope_policy"
AUDIT_HEADER = (
    SOURCE_ASSERTION_ID_COLUMN,
    SOURCE_RECORD_COLUMN,
    "source_record_sha256",
    "source_input_path",
    "source_input_sha256",
    "retained_target",
    "disposition",
    "reason",
    "qualifier_evidence",
    "candidate_route",
    "candidate_input_path",
    "candidate_input_sha256",
    "candidate_record_locator",
    "candidate_target",
    "candidate_record",
    "policy_input_path",
    "policy_input_sha256",
    "authority_label",
    "authority_uri",
)


def _json(value):
    """Encode evidence without changing null, false, zero, missing fields or literal pipes."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _potato(value):
    """Match only the reviewed bare source spelling, using the policy's normalization."""
    return isinstance(value, str) and _scope_key(re.sub(r"[^\w\s-]", "", value)) == "potato"


def _reason(raw):
    """Recognize only reviewed explicit forms; unknown qualifiers do not imply fresh tuber."""
    qualifiers = {key: raw[key] for key in ("condition", "attribute") if key in raw}
    explicit = (isinstance(raw.get("condition"), str) and raw["condition"].strip().casefold() == "peeled and cut") or (
        isinstance(raw.get("attribute"), str)
        and raw["attribute"].strip().casefold() == "fresh, washed, peeled and sliced"
    )
    return (
        "unsupported_material_form_identity" if explicit else "insufficient_material_specificity",
        _json(qualifiers),
    )


def _table_rows(stream, required):
    """Read complete rows with physical line locators and reject ambiguous evidence."""
    skipped = 0
    for first in stream:
        if not first.startswith("#"):
            break
        skipped += 1
    else:
        raise SourceFinalizationRequired("Missing material-scope mapping header")
    from itertools import chain

    reader = csv.DictReader(chain((first,), stream), delimiter="\t")
    fields = reader.fieldnames or ()
    if len(fields) != len(set(fields)) or not required.issubset(fields):
        raise SourceFinalizationRequired("Invalid material-scope mapping header")
    for ordinal, row in enumerate(reader, 1):
        if None in row or any(value is None for value in row.values()):
            raise SourceFinalizationRequired("Malformed material-scope mapping row")
        yield f"record={ordinal};line_end={skipped + reader.line_num}", row


class MaterialScopeAudit:
    """Collect only the reviewed grounding candidates; never create or choose an identity."""

    def __init__(self, transform, media_list):
        """Bind selected current input bytes before graph output, only scanning a relevant cohort."""
        self.transform = transform
        self.guard = SourceAdmission()
        self.claims = []
        self.rows = {}
        solutions = {
            str(solution[ID_COLUMN])
            for medium in media_list[DATA_KEY]
            for solution in transform.media_detailed[str(medium[ID_COLUMN])].get(SOLUTIONS_KEY, [])
        }
        relevant = False
        for identifier in solutions:
            recipe = transform.solutions_data[identifier].get(RECIPE_KEY)
            # Match the existing producer's absent/non-list recipe behavior.
            if isinstance(recipe, list):
                relevant |= any(
                    _potato(item.get(COMPOUND_KEY, item.get(SOLUTION_KEY))) for item in recipe if isinstance(item, dict)
                )
        self.active = relevant
        if not relevant:
            return
        # Bind the exact current policy even if the mapping reader has already
        # excluded the row. Such rows are candidates, not attempted lookups.
        with self._consume(POLICY_ROLE, IDENTITY_POLICY) as stream:
            policies = list(_table_rows(stream, {"target_id", "authority_label", "kind", "value", "reason"}))
        if not any(
            _policy_target_key(row["target_id"]) == TARGET
            and row["authority_label"] == AUTHORITY_LABEL
            and row["kind"] == "name_pattern"
            and row["value"] == "(?i)^potato$"
            for _, row in policies
        ) or ingredient_mapping_allowed("Potato", TARGET):
            raise SourceFinalizationRequired("Reviewed Potato material-scope identity hold is missing")
        unified = _repo_root() / transform.DATA_INPUTS[0]
        with self._consume(UNIFIED_ROLE, unified) as snapshot:
            with gzip.GzipFile(fileobj=snapshot.buffer) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                    for locator, row in _table_rows(stream, {"subject_id", "subject_label", "object_id"}):
                        if (
                            row["subject_id"].startswith("kgm.name:")
                            and _potato(row["subject_label"])
                            and _policy_target_key(row["object_id"]) == TARGET
                            and classify_mapping_row(row)[0] in {"canonical_name", "synonym"}
                        ):
                            self._claim(UNIFIED_ROLE, locator, row["object_id"], row)
        for role in ("micromediaparam_hydrate", "micromediaparam_strict"):
            # The already selected optional-input contract binds absence too.
            with transform.consume_optional_input(role) as stream:
                if stream is None:
                    continue
                for locator, row in _table_rows(stream, {"original", "mapped"}):
                    if _potato(row["original"]) and _policy_target_key(row["mapped"]) == TARGET:
                        self._claim(role, locator, row["mapped"], row)
        self.guard.verify()

    def _consume(self, role, path):
        """Guard the original lexical locator in addition to the immutable parser snapshot."""
        self.guard.bind_path(path)
        self.guard.capture(path)
        return self.transform.consume_input(role, path)

    def _claim(self, role, locator, target, record):
        """Retain distinct row ordinals even when the complete mapping payload is duplicated."""
        snapshot = self.transform.consumed_input_snapshots[role]
        self.claims.append((role, snapshot, locator, target, _json(record)))

    def observe(self, occurrence, raw):
        """Attach available candidates to an actual emitted occurrence and its selected target."""
        if not self.active or not _potato(raw.get(COMPOUND_KEY, raw.get(SOLUTION_KEY))):
            return
        if _policy_target_key(occurrence[ID_COLUMN]) == TARGET:
            raise SourceFinalizationRequired("Held Potato extract identity escaped source resolution")
        candidates = list(self.claims)
        identifier = raw.get(COMPOUND_ID_KEY)
        if identifier is not None:
            embedded = self.transform.compounds_data.get(str(identifier), {})
            value = embedded.get(CAS_RN_KEY)
            if value is not None and _policy_target_key(CAS_RN_PREFIX + str(value)) == TARGET:
                candidates.append(
                    (
                        "mediadive_compounds",
                        self.transform.consumed_input_snapshots["mediadive_compounds"],
                        f"key={_json(str(identifier))};field={CAS_RN_KEY}",
                        CAS_RN_PREFIX + str(value),
                        _json(embedded),
                    )
                )
        source = self.transform.consumed_input_snapshots["mediadive_solutions"]
        policy = self.transform.consumed_input_snapshots[POLICY_ROLE]
        reason, qualifiers = _reason(raw)
        payload = occurrence[SOURCE_RECORD_COLUMN]
        for route, snapshot, locator, target, candidate in candidates:
            row = (
                occurrence[SOURCE_ASSERTION_ID_COLUMN],
                payload,
                hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                source["path"],
                source["sha256"],
                occurrence[ID_COLUMN],
                "quarantined_grounding_candidate",
                reason,
                qualifiers,
                route,
                snapshot["path"],
                snapshot["sha256"],
                locator,
                target,
                candidate,
                policy["path"],
                policy["sha256"],
                AUTHORITY_LABEL,
                AUTHORITY_URI,
            )
            key = (occurrence[SOURCE_ASSERTION_ID_COLUMN], route, locator)
            if self.rows.setdefault(key, row) != row:
                raise SourceFinalizationRequired("Material-scope occurrence changed across repeated visits")

    def write(self):
        """Write complete producer-time evidence, including a valid empty-cohort header."""
        self.guard.verify()
        self.transform.verify_consumed_inputs()
        path = self.transform.output_dir / AUDIT_FILENAME
        if path.is_symlink():
            raise SourceFinalizationRequired("Material-scope audit output must not be a symlink")
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = tsv_writer(stream, quoting=csv.QUOTE_NONE, quotechar=None)
            writer.writerow(AUDIT_HEADER)
            for key in sorted(self.rows):
                writer.writerow(self.rows[key])
        self.guard.verify()
        self.transform.record_producer_audit(AUDIT_FILENAME)


def verify_recorded_material_inputs(report, report_path):
    """Require actual canonical evidence origins for the producer-bound candidate sidecar."""
    snapshots = report.get("consumed_inputs", {})
    path = Path(report_path).parent / AUDIT_FILENAME
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        if tuple(reader.fieldnames or ()) != AUDIT_HEADER:
            raise SourceFinalizationRequired("Invalid material-scope producer audit header")
        has_rows = next(reader, None) is not None
    if not has_rows and not any(role in snapshots for role in (UNIFIED_ROLE, POLICY_ROLE)):
        return
    expected = {
        UNIFIED_ROLE: _repo_root() / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
        POLICY_ROLE: IDENTITY_POLICY,
    }
    for role, origin in expected.items():
        if snapshots.get(role, {}).get("path") != str(origin.resolve()):
            raise SourceFinalizationRequired(f"Missing or wrong material-scope input origin: {role}")
