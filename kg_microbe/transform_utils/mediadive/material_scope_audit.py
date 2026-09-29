"""Preserve reviewed material grounding candidates separately from identity."""

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
    CHEBI_KEY,
    CHEBI_PREFIX,
    COMPOUND_ID_KEY,
    COMPOUND_KEY,
    DATA_KEY,
    ID_COLUMN,
    KEGG_KEY,
    KEGG_PREFIX,
    MEDIADIVE_INGREDIENT_PREFIX,
    MEDIADIVE_SOLUTION_PREFIX,
    PUBCHEM_KEY,
    PUBCHEM_PREFIX,
    RECIPE_KEY,
    SOLUTION_ID_KEY,
    SOLUTION_KEY,
    SOLUTIONS_KEY,
    SOURCE_ASSERTION_ID_COLUMN,
    SOURCE_RECORD_COLUMN,
)
from kg_microbe.utils.chemical_mapping_utils import normalize_name
from kg_microbe.utils.ingredient_identity import (
    IDENTITY_POLICY,
    _policy_target_key,
    _scope_key,
    ingredient_mapping_allowed,
    ingredient_xref_allowed,
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
SUPPORTED_ROLE = "material_scope_supported"
CONTEXT_ROLE = "material_scope_context_policy"
CONTEXT_POLICY = "mappings/canonical/mediadive_material_context_dispositions.tsv"
SUGAR_ATTRIBUTE = "250 mM each of xylose, maltose and cellobiose"
SUGAR_REASON = "qualified_sugar_solution_not_demonstrated_food_identity"
SUGAR_URI = "https://www.jcm.riken.jp/cgi-bin/jcm/jcm_grmd?GRMD=537"
CONTEXT_FIELDS = {
    "source_name",
    "source_attribute",
    "disposition",
    "reason",
    "evidence_uri",
    "authority_label",
    "withheld_target_example",
}
P3556_MIM = "MIM:L-alpha-Phosphatidylcholine"
P3556_TARGET = "CHEBI:86658"
P3556_AUTHORITY_LABEL = "Sigma P3556 egg-yolk phosphatidylcholine material (variable fatty-acid composition)"
P3556_AUTHORITY_URI = "https://www.sigmaaldrich.com/deepweb/assets/sigmaaldrich/product/documents/152/475/p3556pis.pdf"
PEPTONE_TARGET = "pubchem.compound:167312541"
PEPTONE_AUTHORITY_LABEL = "Glycerides, C8-10 mono-and di-"
PEPTONE_AUTHORITY_URI = "https://pubchem.ncbi.nlm.nih.gov/compound/167312541"
PEPTONE_REASON = "digest_material_not_demonstrated_structural_identity"
PEPTONE_PATTERNS = {
    "Soy peptone": "(?i)^soy[ _-]+peptone$",
    "Vitamin-free casamino acids": "(?i)^vitamin[ _-]+free[ _-]+casamino[ _-]+acids$",
}
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


def p3556_material(raw):
    """Recognize only an explicit supplier/product qualifier, never a name or source ID."""
    value = raw.get("attribute") if isinstance(raw, dict) else None
    return isinstance(value, str) and " ".join(value.split()).casefold() == "sigma p3556"


def _peptone(value):
    """Match only the two reviewed digest names, including shared policy normalization."""
    return isinstance(value, str) and _scope_key(re.sub(r"[^\w\s-]", "", value)) in {
        "soy peptone",
        "vitamin free casamino acids",
    }


def sugar_material(raw, name=None):
    """Match only the reviewed source name and stock qualifier, with case/whitespace normalization."""
    if not isinstance(raw, dict):
        return False
    name = raw.get(COMPOUND_KEY, raw.get(SOLUTION_KEY, name))
    attribute = raw.get("attribute")
    return (
        isinstance(name, str)
        and " ".join(name.split()).casefold() == "sugar"
        and isinstance(attribute, str)
        and " ".join(attribute.split()).casefold() == SUGAR_ATTRIBUTE.casefold()
    )


def _profile(raw):
    """Give explicit product evidence priority over a possibly contradictory display name."""
    if p3556_material(raw):
        return "p3556"
    if sugar_material(raw):
        return "sugar"
    if _peptone(raw.get(COMPOUND_KEY, raw.get(SOLUTION_KEY))):
        return "peptone"
    return "potato" if _potato(raw.get(COMPOUND_KEY, raw.get(SOLUTION_KEY))) else None


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
        self.names = {"potato": set(), "p3556": set(), "sugar": set(), "peptone": set()}
        for identifier in solutions:
            recipe = transform.solutions_data[identifier].get(RECIPE_KEY)
            # Match the existing producer's absent/non-list recipe behavior.
            if isinstance(recipe, list):
                for item in recipe:
                    if isinstance(item, dict) and (profile := _profile(item)):
                        name = item.get(COMPOUND_KEY, item.get(SOLUTION_KEY))
                        self.names[profile].add(name if isinstance(name, str) else "")
        self.active = any(self.names.values())
        if not self.active:
            return
        # Bind the exact current policy even if the mapping reader has already
        # excluded the row. Such rows are candidates, not attempted lookups.
        policies = []
        if self.names["potato"] or self.names["p3556"] or self.names["peptone"]:
            with self._consume(POLICY_ROLE, IDENTITY_POLICY) as stream:
                policies = list(_table_rows(stream, {"target_id", "authority_label", "kind", "value", "reason"}))
        if self.names["sugar"]:
            with self._consume(CONTEXT_ROLE, _repo_root() / CONTEXT_POLICY) as stream:
                decisions = list(_table_rows(stream, CONTEXT_FIELDS))
            if len(decisions) != 1:
                raise SourceFinalizationRequired("Reviewed Sugar context requires one exact decision")
            self.sugar_decision = decisions[0][1]
            if set(self.sugar_decision) != CONTEXT_FIELDS or self.sugar_decision != {
                "source_name": "Sugar",
                "source_attribute": SUGAR_ATTRIBUTE,
                "disposition": "retain_existing_local",
                "reason": SUGAR_REASON,
                "evidence_uri": SUGAR_URI,
                "authority_label": "JCM 537 mixed xylose, maltose and cellobiose stock solution",
                "withheld_target_example": "NCIT:C71939",
            }:
                raise SourceFinalizationRequired("Reviewed Sugar context decision changed or is missing")
        if self.names["potato"] and (
            not any(
                _policy_target_key(row["target_id"]) == TARGET
                and row["authority_label"] == AUTHORITY_LABEL
                and row["kind"] == "name_pattern"
                and row["value"] == "(?i)^potato$"
                for _, row in policies
            )
            or ingredient_mapping_allowed("Potato", TARGET)
        ):
            raise SourceFinalizationRequired("Reviewed Potato material-scope identity hold is missing")
        if self.names["p3556"] and (
            ingredient_mapping_allowed("L-alpha-Phosphatidylcholine", P3556_TARGET)
            or ingredient_xref_allowed(P3556_MIM, P3556_TARGET)
            or not all(
                any(
                    row["target_id"] == P3556_TARGET and row["kind"] == kind and row["value"] == value
                    for _, row in policies
                )
                for kind, value in (
                    ("name_pattern", "(?i)^l[ _-]*(?:alpha|α)[ _-]*phosphatidylcholine$"),
                    ("xref", P3556_MIM),
                )
            )
        ):
            raise SourceFinalizationRequired("Reviewed P3556 material-scope identity hold is missing")
        if self.names["peptone"] and not all(
            not ingredient_mapping_allowed(name, PEPTONE_TARGET)
            and any(
                _policy_target_key(row["target_id"]) == PEPTONE_TARGET
                and row["authority_label"] == PEPTONE_AUTHORITY_LABEL
                and row["kind"] == "name_pattern"
                and row["value"] == pattern
                for _, row in policies
            )
            for name, pattern in PEPTONE_PATTERNS.items()
        ):
            raise SourceFinalizationRequired("Reviewed peptone material-scope identity holds are missing")
        unified = _repo_root() / transform.DATA_INPUTS[0]
        with self._consume(UNIFIED_ROLE, unified) as snapshot:
            with gzip.GzipFile(fileobj=snapshot.buffer) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                    for locator, row in _table_rows(stream, {"subject_id", "subject_label", "object_id"}):
                        self._mapping_claims(UNIFIED_ROLE, locator, row)
        if self.names["p3556"] or self.names["sugar"]:
            # Original imported evidence remains available after the derived
            # unified row is removed. This never feeds an identity lookup.
            with self._consume(SUPPORTED_ROLE, _repo_root() / "mappings/ingredient_mappings.sssom.tsv") as stream:
                for locator, row in _table_rows(stream, {"subject_id", "subject_label", "object_id"}):
                    self._mapping_claims(SUPPORTED_ROLE, locator, row)
        for role in ("micromediaparam_hydrate", "micromediaparam_strict"):
            # The already selected optional-input contract binds absence too.
            with transform.consume_optional_input(role) as stream:
                if stream is None:
                    continue
                for locator, row in _table_rows(stream, {"original", "mapped"}):
                    if (
                        self.names["potato"]
                        and _potato(row["original"])
                        and _policy_target_key(row["mapped"]) == TARGET
                    ):
                        self._claim("potato", None, role, locator, row["mapped"], row)
                    for profile in ("p3556", "sugar"):
                        for name in self.names[profile]:
                            if name and name.lower().strip() == row["original"].lower().strip():
                                self._claim(profile, name, role, locator, row["mapped"], row)
                    if _policy_target_key(row["mapped"]) == PEPTONE_TARGET:
                        for name in self.names["peptone"]:
                            if name.lower().strip() == row["original"].lower().strip():
                                self._claim("peptone", name, role, locator, row["mapped"], row)
        self.guard.verify()

    def _mapping_claims(self, role, locator, row):
        """Select only reader-eligible lexical or exact imported claims for the actual spelling."""
        route = classify_mapping_row(row)[0]
        if route in {"canonical_name", "synonym"}:
            if (
                self.names["potato"]
                and _potato(row["subject_label"])
                and _policy_target_key(row["object_id"]) == TARGET
            ):
                self._claim("potato", None, role, locator, row["object_id"], row)
        # All four recognized primary routes can supply canonical object
        # metadata; only synonym rows additionally index subject_label (#1243).
        # Preserve eligible original claims even when the identity policy now
        # rejects that label. These are available candidates, not lookup calls.
        if route not in {"identity", "attribute", "canonical_name", "synonym"}:
            return
        if _policy_target_key(row["object_id"]) == PEPTONE_TARGET:
            for name in self.names["peptone"]:
                if normalize_name(name) == normalize_name(row.get("object_label", "")) or (
                    route == "synonym" and normalize_name(name) == normalize_name(row["subject_label"])
                ):
                    self._claim("peptone", name, role, locator, row["object_id"], row)
        for profile, subject, target in (
            ("p3556", P3556_MIM, P3556_TARGET),
            ("sugar", "MIM:Sugar", "NCIT:C71939"),
        ):
            if (
                self.names[profile]
                and route == "identity"
                and row["subject_id"] == subject
                and row["object_id"] == target
            ):
                self._claim(profile, None, role, locator, row["object_id"], row)
                continue
            for name in self.names[profile]:
                if name and (
                    normalize_name(name) == normalize_name(row.get("object_label", ""))
                    or (route == "synonym" and normalize_name(name) == normalize_name(row["subject_label"]))
                ):
                    self._claim(profile, name, role, locator, row["object_id"], row)

    def _consume(self, role, path):
        """Guard the original lexical locator in addition to the immutable parser snapshot."""
        self.guard.bind_path(path)
        self.guard.capture(path)
        return self.transform.consume_input(role, path)

    def _claim(self, profile, name, role, locator, target, record):
        """Retain distinct row ordinals even when the complete mapping payload is duplicated."""
        snapshot = self.transform.consumed_input_snapshots[role]
        self.claims.append((profile, name, (role, snapshot, locator, target, _json(record))))

    def observe(self, occurrence, raw):
        """Attach available candidates to an actual emitted occurrence and its selected target."""
        profile = _profile(raw)
        if not self.active or not profile:
            return
        if profile == "potato" and _policy_target_key(occurrence[ID_COLUMN]) == TARGET:
            raise SourceFinalizationRequired("Held Potato extract identity escaped source resolution")
        if profile == "peptone" and _policy_target_key(occurrence[ID_COLUMN]) == PEPTONE_TARGET:
            raise SourceFinalizationRequired("Held peptone structural identity escaped source resolution")
        if profile in {"p3556", "sugar"}:
            local = (
                MEDIADIVE_INGREDIENT_PREFIX + str(raw[COMPOUND_ID_KEY])
                if raw.get(COMPOUND_ID_KEY) is not None
                else MEDIADIVE_SOLUTION_PREFIX + str(raw[SOLUTION_ID_KEY])
            )
            if occurrence[ID_COLUMN] != local:
                raise SourceFinalizationRequired("Held source material identity escaped source resolution")
        name = raw.get(COMPOUND_KEY, raw.get(SOLUTION_KEY))
        candidates = [claim for group, spelling, claim in self.claims if group == profile and spelling in (None, name)]
        identifier = raw.get(COMPOUND_ID_KEY)
        if identifier is not None:
            embedded = self.transform.compounds_data.get(str(identifier), {})
            for field, prefix in (
                (CHEBI_KEY, CHEBI_PREFIX),
                (KEGG_KEY, KEGG_PREFIX),
                (PUBCHEM_KEY, PUBCHEM_PREFIX),
                (CAS_RN_KEY, CAS_RN_PREFIX),
            ):
                value = embedded.get(field)
                target = prefix + str(value)
                if value is None or (profile == "potato" and _policy_target_key(target) != TARGET):
                    continue
                if profile == "peptone" and _policy_target_key(target) != PEPTONE_TARGET:
                    continue
                candidates.append(
                    (
                        "mediadive_compounds",
                        self.transform.consumed_input_snapshots["mediadive_compounds"],
                        f"key={_json(str(identifier))};field={field}",
                        target,
                        _json(embedded),
                    )
                )
        source = self.transform.consumed_input_snapshots["mediadive_solutions"]
        policy_role = CONTEXT_ROLE if profile == "sugar" else POLICY_ROLE
        policy = self.transform.consumed_input_snapshots[policy_role]
        reason, qualifiers = (
            ("whole_product_not_molecular_identity", _json({"attribute": raw["attribute"]}))
            if profile == "p3556"
            else _reason(raw)
        )
        if profile == "sugar":
            reason, qualifiers = self.sugar_decision["reason"], _json({"attribute": raw["attribute"]})
        if profile == "peptone":
            reason = PEPTONE_REASON
        authority_label, authority_uri = AUTHORITY_LABEL, AUTHORITY_URI
        if profile == "p3556":
            authority_label, authority_uri = P3556_AUTHORITY_LABEL, P3556_AUTHORITY_URI
        elif profile == "peptone":
            authority_label, authority_uri = PEPTONE_AUTHORITY_LABEL, PEPTONE_AUTHORITY_URI
        elif profile == "sugar":
            authority_label, authority_uri = self.sugar_decision["authority_label"], self.sugar_decision["evidence_uri"]
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
                authority_label,
                authority_uri,
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
    context_path = str((_repo_root() / CONTEXT_POLICY).resolve())
    context_recorded = any(item.get("path") == context_path for item in report.get("inputs", ()))
    path = Path(report_path).parent / AUDIT_FILENAME
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        if tuple(reader.fieldnames or ()) != AUDIT_HEADER:
            raise SourceFinalizationRequired("Invalid material-scope producer audit header")
        has_rows = False
        needs_supported = False
        needs_context = False
        needs_identity = False
        for row in reader:
            has_rows = True
            sugar = row.get("reason") == SUGAR_REASON
            needs_context |= sugar
            needs_identity |= not sugar
            needs_supported |= sugar or row.get("reason") == "whole_product_not_molecular_identity"
    if (
        not has_rows
        and not context_recorded
        and not any(role in snapshots for role in (UNIFIED_ROLE, POLICY_ROLE, SUPPORTED_ROLE, CONTEXT_ROLE))
    ):
        return
    expected = {
        UNIFIED_ROLE: _repo_root() / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz",
    }
    if needs_identity or POLICY_ROLE in snapshots:
        expected[POLICY_ROLE] = IDENTITY_POLICY
    if needs_context or context_recorded or CONTEXT_ROLE in snapshots:
        expected[CONTEXT_ROLE] = _repo_root() / CONTEXT_POLICY
    if needs_supported or needs_context or context_recorded or CONTEXT_ROLE in snapshots or SUPPORTED_ROLE in snapshots:
        expected[SUPPORTED_ROLE] = _repo_root() / "mappings/ingredient_mappings.sssom.tsv"
    for role, origin in expected.items():
        if snapshots.get(role, {}).get("path") != str(origin.resolve()):
            raise SourceFinalizationRequired(f"Missing or wrong material-scope input origin: {role}")
