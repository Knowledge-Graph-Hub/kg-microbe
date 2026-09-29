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
REVIEWED_ROLE = "material_scope_reviewed_claims"
REVIEWED_PATH = "mappings/mediadive_material_grounding_review.json"
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


def _reviewed_catalogue(stream):
    """Read finite historical claims as evidence only, never as a lookup or replacement policy."""

    def unique_keys(pairs):
        """Reject duplicate JSON keys rather than silently replacing curated evidence."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise SourceFinalizationRequired("Duplicate reviewed material catalogue key")
            result[key] = value
        return result

    def require(condition):
        """Reject malformed or internally inconsistent catalogue evidence."""
        if not condition:
            raise SourceFinalizationRequired("Invalid reviewed material grounding catalogue")

    try:
        text = stream.read(4 * 1024 * 1024 + 1)
        require(len(text) <= 4 * 1024 * 1024)
        catalogue = json.loads(text, object_pairs_hook=unique_keys)
    except SourceFinalizationRequired:
        raise
    except (ValueError, TypeError) as exc:
        raise SourceFinalizationRequired("Invalid reviewed material grounding catalogue JSON") from exc
    require(
        isinstance(catalogue, dict) and set(catalogue) == {"version", "baseline", "dispositions", "historical_claims"}
    )
    require(type(catalogue["version"]) is int and catalogue["version"] == 1)
    baseline = catalogue["baseline"]
    require(isinstance(baseline, dict) and set(baseline) == {"path", "sha256", "fields"})
    require(baseline["path"] == "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz")
    require(isinstance(baseline["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", baseline["sha256"]))
    fields = baseline["fields"]
    require(isinstance(fields, list) and all(isinstance(field, str) and field for field in fields))
    require(
        len(fields) == len(set(fields))
        and {
            "subject_id",
            "subject_label",
            "object_id",
            "object_label",
            "predicate_id",
            "mapping_justification",
            "comment",
        }.issubset(fields)
    )
    require(isinstance(catalogue["dispositions"], list) and isinstance(catalogue["historical_claims"], list))
    dispositions, names = {}, {}
    for decision in catalogue["dispositions"]:
        require(
            isinstance(decision, dict)
            and set(decision) == {"id", "target_id", "authority_label", "reason", "evidence_uri", "source_names"}
        )
        require(
            all(isinstance(value, str) and value.strip() for key, value in decision.items() if key != "source_names")
        )
        require(
            re.fullmatch(r"CHEBI:[0-9]+", decision["target_id"]) and decision["evidence_uri"].startswith("https://")
        )
        require(decision["id"] not in dispositions)
        require(isinstance(decision["source_names"], list) and decision["source_names"])
        require(all(isinstance(name, str) and normalize_name(name) for name in decision["source_names"]))
        require(len(decision["source_names"]) == len(set(decision["source_names"])))
        dispositions[decision["id"]] = decision
        for name in decision["source_names"]:
            key = normalize_name(name)
            require(key not in names or names[key] == decision)
            names[key] = decision
    ordinals, represented = set(), set()
    for claim in catalogue["historical_claims"]:
        require(isinstance(claim, dict) and set(claim) == {"disposition_id", "data_row_ordinal", "row"})
        require(isinstance(claim["disposition_id"], str) and claim["disposition_id"] in dispositions)
        ordinal = claim["data_row_ordinal"]
        require(type(ordinal) is int and ordinal > 0 and ordinal not in ordinals)
        ordinals.add(ordinal)
        row, decision = claim["row"], dispositions[claim["disposition_id"]]
        require(
            isinstance(row, dict) and set(row) == set(fields) and all(isinstance(value, str) for value in row.values())
        )
        require(row["object_id"] == decision["target_id"] and row["subject_id"].startswith("kgm.name:"))
        require(classify_mapping_row(row)[0] in {"canonical_name", "synonym"})
        require(names.get(normalize_name(row["subject_label"])) == decision)
        represented.add(claim["disposition_id"])
    require(represented == set(dispositions))
    return catalogue, names


def _policy_name_forms(name):
    """Mirror existing identity-policy spelling forms without adding lexical heuristics."""
    original = name.strip()
    normalized = re.sub(r"[^\w\s-]", "", original)
    return (original, normalized, re.sub(r"[\s_-]+", " ", original), re.sub(r"[\s_-]+", " ", normalized))


class MaterialScopeAudit:
    """Collect only the reviewed grounding candidates; never create or choose an identity."""

    def __init__(self, transform, media_list):
        """Bind selected current input bytes before graph output, only scanning a relevant cohort."""
        self.transform = transform
        self.guard = SourceAdmission()
        self.claims = []
        self.rows = {}
        with self._consume(REVIEWED_ROLE, _repo_root() / REVIEWED_PATH) as stream:
            self.reviewed_catalogue, self.reviewed_names = _reviewed_catalogue(stream)
        with self._consume(POLICY_ROLE, IDENTITY_POLICY) as stream:
            policies = list(_table_rows(stream, {"target_id", "authority_label", "kind", "value", "reason"}))
        self.reviewed_selected = {}
        self._validate_reviewed_policy(policies)
        solutions = {
            str(solution[ID_COLUMN])
            for medium in media_list[DATA_KEY]
            for solution in transform.media_detailed[str(medium[ID_COLUMN])].get(SOLUTIONS_KEY, [])
        }
        self.names = {"potato": set(), "p3556": set(), "sugar": set(), "peptone": set(), "reviewed": set()}
        for identifier in solutions:
            recipe = transform.solutions_data[identifier].get(RECIPE_KEY)
            # Match the existing producer's absent/non-list recipe behavior.
            if isinstance(recipe, list):
                for item in recipe:
                    if isinstance(item, dict) and (profile := self._profile(item)):
                        name = item.get(COMPOUND_KEY, item.get(SOLUTION_KEY))
                        self.names[profile].add(name if isinstance(name, str) else "")
        self.active = any(self.names.values())
        if not self.active:
            self.guard.verify()
            return
        # Bind the exact current policy even if the mapping reader has already
        # excluded the row. Such rows are candidates, not attempted lookups.
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
        if self.names["reviewed"]:
            for name in self.names["reviewed"]:
                decision = self.reviewed_selected[name]
                for claim in self.reviewed_catalogue["historical_claims"]:
                    if claim["disposition_id"] == decision["id"]:
                        baseline = self.reviewed_catalogue["baseline"]
                        locator = (
                            f"historical-baseline-sha256={baseline['sha256']};data-record={claim['data_row_ordinal']}"
                        )
                        self._claim("reviewed", name, REVIEWED_ROLE, locator, claim["row"]["object_id"], claim["row"])
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
                    for name in self.names["reviewed"]:
                        decision = self.reviewed_selected[name]
                        if name.lower().strip() == row["original"].lower().strip() and _policy_target_key(
                            row["mapped"]
                        ) == _policy_target_key(decision["target_id"]):
                            self._claim("reviewed", name, role, locator, row["mapped"], row)
        self.guard.verify()

    def _profile(self, raw):
        """Select finite audited pairs without changing source identity resolution."""
        existing = _profile(raw)
        name = raw.get(COMPOUND_KEY, raw.get(SOLUTION_KEY))
        if existing or not isinstance(name, str):
            return existing
        if name not in self.reviewed_selected:
            matches = [
                decision
                for decision, patterns in self.reviewed_patterns
                if any(pattern.search(form) for pattern in patterns for form in _policy_name_forms(name))
            ]
            if len(matches) > 1:
                raise SourceFinalizationRequired("Ambiguous reviewed material name/target dispositions")
            if matches and ingredient_mapping_allowed(name, matches[0]["target_id"]):
                raise SourceFinalizationRequired("Reviewed material policy disagrees with runtime mapping admission")
            self.reviewed_selected[name] = matches[0] if matches else None
        return "reviewed" if self.reviewed_selected[name] is not None else None

    def _validate_reviewed_policy(self, policies):
        """Require actual selected policy bytes, not only a previously cached rejection."""
        self.reviewed_patterns = []
        for decision in self.reviewed_catalogue["dispositions"]:
            patterns = [
                re.compile(row["value"])
                for _, row in policies
                if row["target_id"] == decision["target_id"]
                and row["authority_label"] == decision["authority_label"]
                and row["kind"] == "name_pattern"
            ]
            patterns = [
                pattern
                for pattern in patterns
                if any(pattern.search(form) for name in decision["source_names"] for form in _policy_name_forms(name))
            ]
            for name in decision["source_names"]:
                if not any(
                    pattern.search(form) for pattern in patterns for form in _policy_name_forms(name)
                ) or ingredient_mapping_allowed(name, decision["target_id"]):
                    raise SourceFinalizationRequired("Reviewed material name/target policy changed or is missing")
            self.reviewed_patterns.append((decision, patterns))

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
        for name in self.names["reviewed"]:
            decision = self.reviewed_selected[name]
            if row["object_id"].strip() == decision["target_id"] and (
                normalize_name(name) == normalize_name(row.get("object_label", ""))
                or (route == "synonym" and normalize_name(name) == normalize_name(row["subject_label"]))
            ):
                self._claim("reviewed", name, role, locator, row["object_id"], row)
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
        profile = self._profile(raw)
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
        reviewed = self.reviewed_selected[name] if profile == "reviewed" else None
        if reviewed and _policy_target_key(occurrence[ID_COLUMN]) == _policy_target_key(reviewed["target_id"]):
            raise SourceFinalizationRequired("Held reviewed material name/target pair escaped source resolution")
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
                if reviewed and _policy_target_key(target) != _policy_target_key(reviewed["target_id"]):
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
        elif reviewed:
            reason = reviewed["reason"]
            authority_label, authority_uri = reviewed["authority_label"], reviewed["evidence_uri"]
        payload = occurrence[SOURCE_RECORD_COLUMN]
        for route, snapshot, locator, target, candidate in candidates:
            row = (
                occurrence[SOURCE_ASSERTION_ID_COLUMN],
                payload,
                hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                source["path"],
                source["sha256"],
                occurrence[ID_COLUMN],
                "historical_quarantined_grounding_claim"
                if route == REVIEWED_ROLE
                else "quarantined_grounding_candidate",
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
    if snapshots.get(REVIEWED_ROLE, {}).get("path") != str((_repo_root() / REVIEWED_PATH).resolve()):
        raise SourceFinalizationRequired(f"Missing or wrong material-scope input origin: {REVIEWED_ROLE}")
    if snapshots.get(POLICY_ROLE, {}).get("path") != str(IDENTITY_POLICY.resolve()):
        raise SourceFinalizationRequired(f"Missing or wrong material-scope input origin: {POLICY_ROLE}")
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
    expected = {}
    if has_rows or UNIFIED_ROLE in snapshots:
        expected[UNIFIED_ROLE] = _repo_root() / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
    if needs_identity or POLICY_ROLE in snapshots:
        expected[POLICY_ROLE] = IDENTITY_POLICY
    if needs_context or context_recorded or CONTEXT_ROLE in snapshots:
        expected[CONTEXT_ROLE] = _repo_root() / CONTEXT_POLICY
    if needs_supported or needs_context or context_recorded or CONTEXT_ROLE in snapshots or SUPPORTED_ROLE in snapshots:
        expected[SUPPORTED_ROLE] = _repo_root() / "mappings/ingredient_mappings.sssom.tsv"
    for role, origin in expected.items():
        if snapshots.get(role, {}).get("path") != str(origin.resolve()):
            raise SourceFinalizationRequired(f"Missing or wrong material-scope input origin: {role}")
