"""
Bind source-local BacDive taxonomy evidence for #1353, #1354, #1361 and #1364.

Native supplied-taxid and LPSN selection and inferred native-candidate eligibility
are independently replayable.
Name-derived parent claims remain predictions, never native supplied taxids.
"""

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.bacdive import (
    isolation_categories,
    ncit_category_claims,
    supplied_taxid_policy,
)
from kg_microbe.transform_utils.bacdive.ancestry_authority import FreshAncestryAuthority
from kg_microbe.transform_utils.bacdive.emission import (
    RESOLUTION_COLLAPSED,
    RESOLUTION_SUPPRESSED,
    RESOLUTION_SUPPRESSED_NO_ANCESTRY,
    resolve_deposit_parents,
)
from kg_microbe.transform_utils.bacdive.fallback_evidence import (
    FallbackEvidence,
    recorded_selected_opener,
)
from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    AUTOMATED_AGENT,
    INFERRED_SUBCLASS_RELATION,
    KNOWLEDGE_LEVEL_COLUMN,
    MANUAL_AGENT,
    OBJECT_COLUMN,
    OBSERVATION,
    ORIGINAL_OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PREDICTION,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PUBLICATIONS_COLUMN,
    RDFS_SUBCLASS_OF,
    RELATION_COLUMN,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
)
from kg_microbe.utils.lpsn_utils import (
    LPSN_CORRECT_NAME,
    LPSN_MAX_SYNONYM_HOPS,
    resolve_accepted_records,
)
from kg_microbe.utils.optional_consumed_inputs import verify_optional_inputs
from kg_microbe.utils.provenance import bacdive_record_url
from kg_microbe.utils.source_finalization import SourceFinalizationRequired, graph_rows

GSS_ROLE = "bacdive_taxonomy_lpsn_gss"
OPTIONAL_RAW_INPUTS = ((GSS_ROLE, "lpsn_gss.csv"),)
RAW_ROLE = isolation_categories.RAW_INPUT
AUDIT_FILE = "taxonomy_assertion_dispositions.tsv"
AUDIT_FIELDS = (
    "kind",
    "status",
    "subject",
    "object",
    "native_evidence_json",
    "lookup_evidence_json",
    "original_edge_json",
    "emitted_edge_json",
    "consumed_inputs_json",
)
_MEMBERS = {"nodes.tsv", "edges.tsv"}
_RAW_FILE = "bacdive_strains.json"
_PREFIX = "kgmicrobe.strain:bacdive_"


class _OptionalGss:
    """Use the existing optional-reader contract for this same source declaration."""

    OPTIONAL_RAW_CONSUMED_INPUTS = OPTIONAL_RAW_INPUTS


def _json(value):
    """Keep arbitrary source strings reversible in a single TSV cell."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _sha(value):
    """Seal structured parsed evidence without claiming it is original lexical JSON."""
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _fail(message):
    """Refuse incomplete or changed source-local taxonomy evidence."""
    raise SourceFinalizationRequired("BacDive taxonomy evidence: " + message)


def _records(payload):
    """Retain original list/dictionary coordinates before the producer normalizes containers."""
    if isinstance(payload, list):
        return enumerate(payload)
    if isinstance(payload, dict):
        return payload.items()
    _fail("native payload must be a list or record dictionary")


def _selected_taxid(general):
    """Match existing priority without turning competing native IDs into equivalence."""
    supplied = general.get("NCBI tax id")
    if supplied is None:
        return None
    if isinstance(supplied, dict):
        selected = supplied
    elif isinstance(supplied, list):
        preferred = [item for item in supplied if item.get("Matching level") == "strain"]
        preferred = preferred or [item for item in supplied if item.get("Matching level") == "species"]
        if not preferred:
            return None
        selected = preferred[0]
    else:
        _fail("unsupported supplied taxid container")
    value = selected.get("NCBI tax id")
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).isdigit():
        _fail("supplied taxid is not a native numeric identifier")
    return "NCBITaxon:" + str(value)


def _deposits(external):
    """Preserve source token positions and the current producer's exact identifier spelling."""
    value = external.get("culture collection no.") or ""
    if not isinstance(value, str):
        _fail("culture collection field is not a string")
    result = []
    for index, token in enumerate(value.split(",")):
        label = token.translate(str.maketrans("", "", '()"')).replace('""', "").strip()
        identifier = label.replace(" ", "-").replace(":", "-")
        if len(identifier) > 3:
            result.append({"token_index": index, "literal_token": token, "deposit": "kgmicrobe.strain:" + identifier})
    return result


def _native_record(coordinate, record):
    """Bind complete-record identity and preserve the complete taxonomy evidence blocks."""
    if not isinstance(record, dict):
        _fail("native record is not an object")
    general = record.get("General", {})
    identifier = str(general.get("BacDive-ID", ""))
    if not identifier:
        _fail("native record lacks its BacDive ID")
    classification = record.get("Name and taxonomic classification", {})
    external = record.get("External links", {})
    return {
        "record_id": identifier,
        "source_coordinate": coordinate,
        "record_sha256": _sha(record),
        "general": general,
        "classification": classification,
        "external_links": external,
        "references": record.get("Reference", {}),
        "direct_taxid": _selected_taxid(general),
        "deposits": _deposits(external),
    }


def _candidate(block):
    """Keep the actual species/blank-only two-token behavior, not the old misleading docstring."""
    if not block:
        return ""
    if not isinstance(block, dict):
        _fail("native LPSN block is not an object")
    name = (block.get("species") or "").strip()
    if name:
        return name
    text = re.sub(r"<[^>]+>", "", (block.get("full scientific name") or "").strip()).strip()
    return " ".join(text.split()[:2])


class LpsnIndex:
    """A run-local index built only from the actual optional immutable GSS read."""

    def __init__(self, stream):
        """Keep all original rows; ambiguity is evaluated only after explicit record-link resolution."""
        rows, coordinates, names = {}, {}, defaultdict(list)
        if stream is not None:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            required = {"record_no", "record_lnk", "status", "genus_name", "sp_epithet", "subsp_epithet"}
            if fields is None or len(fields) != len(set(fields)) or not required <= set(fields):
                _fail("GSS header is missing required fields or has duplicate columns")
            for ordinal, row in enumerate(reader, 1):
                if None in row or None in row.values() or any("\x00" in value for value in row.values()):
                    _fail("malformed native GSS row")
                identifier = row["record_no"].strip()
                if not identifier:
                    continue
                if identifier in rows:
                    _fail("duplicate native GSS record number")
                rows[identifier] = row
                coordinates[identifier] = {"record_ordinal": ordinal, "physical_line_end": reader.line_num}
                name = " ".join(
                    row[field].strip() for field in ("genus_name", "sp_epithet", "subsp_epithet") if row[field].strip()
                )
                if name:
                    names[name].append(identifier)
        accepted = resolve_accepted_records(rows)
        self._rows = rows
        self._coordinates = coordinates
        self._names = dict(names)
        self._accepted = accepted
        self._seal = _sha(self.state())
        self._row_seals = {identifier: _sha(row) for identifier, row in rows.items()}

    def state(self):
        """Expose only the parsed scientific state for retained checkpoint verification."""
        return self._rows, self._coordinates, self._names, self._accepted

    def verify(self):
        """Reject mutable parsed-cache drift once per checkpoint, not once per record."""
        if _sha(self.state()) != self._seal:
            _fail("parsed native GSS evidence changed")

    def _chain(self, identifier):
        """Retain every traversed original row without treating dead ends or cycles as replacements."""
        chain, seen, current = [], set(), identifier
        for _ in range(LPSN_MAX_SYNONYM_HOPS + 1):
            if current in seen or current not in self._rows:
                break
            seen.add(current)
            row = self._rows[current]
            if _sha(row) != self._row_seals[current]:
                _fail("a selected cached GSS row changed before use")
            chain.append({"record_no": current, "coordinate": self._coordinates[current], "full_row": row})
            if LPSN_CORRECT_NAME in (row.get("status") or ""):
                break
            link = (row.get("record_lnk") or "").strip()
            if not link:
                break
            current = link
        return chain

    def lookup(self, block):
        """Keep original multiplicity but decide uniqueness on resolved target IDs."""
        candidate = _candidate(block)
        originals = list(self._names.get(candidate, ()))
        remapped = [self._accepted.get(identifier, identifier) for identifier in originals]
        distinct = sorted(set(remapped))
        return {
            "candidate": candidate,
            "original_ids": originals,
            "resolved_ids_with_multiplicity": remapped,
            "distinct_resolved_ids": distinct,
            "chains": [self._chain(identifier) for identifier in originals],
            "target": distinct[0] if len(distinct) == 1 else None,
            "previous_target": remapped[0] if len(remapped) == 1 else None,
        }

    def preview_index(self):
        """Return independent copies for legacy narrow preview callers, not production read receipts."""
        return {
            name: sorted({self._accepted.get(identifier, identifier) for identifier in values})
            for name, values in self._names.items()
        }


def _edge(subject, target, *, inferred=False):
    """Construct only unchanged taxonomy shape and the reviewed derivation metadata."""
    return {
        SUBJECT_COLUMN: subject,
        PREDICATE_COLUMN: SUBCLASS_PREDICATE,
        OBJECT_COLUMN: target,
        RELATION_COLUMN: INFERRED_SUBCLASS_RELATION if inferred else RDFS_SUBCLASS_OF,
        PRIMARY_KNOWLEDGE_SOURCE_COLUMN: "infores:bacdive",
        KNOWLEDGE_LEVEL_COLUMN: PREDICTION if inferred else OBSERVATION,
        AGENT_TYPE_COLUMN: AUTOMATED_AGENT if inferred else MANUAL_AGENT,
        "value": "",
        "unit": "",
        PUBLICATIONS_COLUMN: bacdive_record_url(subject[len(_PREFIX) :]) if subject.startswith(_PREFIX) else "",
        ORIGINAL_OBJECT_COLUMN: "",
    }


def _equal_row(actual, expected):
    """Permit only schema-added empty fields, never unreviewed nonempty qualifiers or evidence."""
    return all((actual.get(key) or "") == (expected.get(key) or "") for key in set(actual) | set(expected))


def _row_key(row):
    """Retain complete nonempty row identity while allowing schema-added empty fields."""
    return tuple(sorted((key, value) for key, value in row.items() if value))


class TaxonomyEvidence:
    """Retain source-local support classifications without changing parent-resolution policy."""

    def __init__(self, raw_dir, gss, bindings, optional_state, *, supplied_policy, admission=None):
        """Start before the existing immutable BacDive native read observer is invoked."""
        self.raw_dir = Path(raw_dir).absolute()
        self.gss = gss
        self._bindings = _json(bindings)
        self._optional_state = _json(optional_state)
        self._supplied_policy = _json(supplied_policy)
        self.records = ()
        self._entry_seals = ()
        self._native_seal = None
        self._deposit_occurrences = {}
        self._deposit_occurrence_seals = {}
        self._deposit_occurrence_binding = None
        self.parent_choices = {}
        self._choice_seals = {}
        self.lookup_seen = set()
        self.deposit_rows = {}
        self._contract = None
        self._ancestry = None
        self._ancestry_owner = None
        self._fallback = None
        self._resolver_result = None
        self._completed = False
        self._outputs_ready = False
        self._failed = False
        self.admission = admission or SourceAdmission()
        self.admission.capture_resolution(lambda: self._failed)
        self.admission.bind_path(self.raw_dir / _RAW_FILE)
        self.admission.bind_path(self.raw_dir / "lpsn_gss.csv")
        policy_binding = bindings.get(supplied_taxid_policy.ROLE)
        if policy_binding != {
            "path": str(supplied_taxid_policy.POLICY_PATH.resolve()),
            "sha256": supplied_taxid_policy.POLICY_SHA256,
        }:
            _fail("original supplied-taxid policy binding missing or changed")
        if self.admission.capture(supplied_taxid_policy.POLICY_PATH)["sha256"] != policy_binding["sha256"]:
            _fail("original supplied-taxid policy bytes changed")
        verify_optional_inputs(
            _OptionalGss,
            {"version": 1, "inputs": {GSS_ROLE: optional_state}},
            bindings,
            admission=self.admission,
            input_dir=self.raw_dir,
        )
        optional_locator = self.raw_dir / "lpsn_gss.csv"
        optional_resolved = optional_locator.resolve()
        optional_identity = _json(self.admission.identities.get(optional_resolved))
        optional_stamp = self.admission.stamps.get(optional_resolved)
        optional_absent = optional_state["sha256"] is None

        def original_optional_obligation():
            """Do not let a lost admission-cache entry turn an original absence/read into no obligation."""
            if self.admission.bindings.get(optional_locator) != optional_resolved:
                _fail("original GSS locator guard was lost")
            if optional_absent:
                if optional_resolved not in self.admission.absent:
                    _fail("original GSS absence guard was lost")
            elif (
                _json(self.admission.identities.get(optional_resolved)) != optional_identity
                or self.admission.stamps.get(optional_resolved) != optional_stamp
            ):
                _fail("original GSS byte/read guard was lost")
            return optional_locator, optional_resolved, optional_identity, optional_stamp, optional_absent

        self.admission.capture_resolution(original_optional_obligation)

    def _poison(self):
        """Keep a failed checkpoint incompatible with the initial healthy admission state."""
        self._failed = True
        self.admission.capture_resolution(lambda: self._failed)

    def capture_native(self, payload, snapshots):
        """Observe the exact parsed payload while its original immutable reader is still open."""
        self.capture_records(_records(payload), snapshots)

    def capture_records(self, records, snapshots):
        """Use the same complete stream projection during recorded-source rejoining."""
        if self._native_seal is not None:
            _fail("native observer was called more than once")
        policy = json.loads(self._supplied_policy)
        native = []
        for coordinate, record in records:
            entry = _native_record(coordinate, record)
            disposition = supplied_taxid_policy.disposition(record, policy)
            if disposition is not None:
                entry["supplied_taxid_disposition"] = disposition
            native.append(entry)
        native = tuple(native)
        raw = snapshots.get(RAW_ROLE)
        if not isinstance(raw, dict) or raw.get("path") != str((self.raw_dir / _RAW_FILE).resolve()):
            _fail("actual immutable BacDive read role is missing")
        bindings = json.loads(self._bindings)
        bindings[RAW_ROLE] = raw
        self._bindings = _json(bindings)
        self.records = native
        occurrences = defaultdict(list)
        for ordinal, entry in enumerate(native):
            for token_index, token in enumerate(entry["deposits"]):
                occurrences[token["deposit"]].append((ordinal, token_index))
        original_occurrences = MappingProxyType({key: tuple(items) for key, items in occurrences.items()})
        original_seals = MappingProxyType({key: _sha(items) for key, items in original_occurrences.items()})
        self._deposit_occurrences = original_occurrences
        self._deposit_occurrence_seals = original_seals

        def original_occurrence_binding():
            """Retain immutable original indexes with constant-time checks on every query admission."""
            return (
                getattr(self, "_deposit_occurrences", None) is original_occurrences,
                getattr(self, "_deposit_occurrence_seals", None) is original_seals,
            )

        self._deposit_occurrence_binding = original_occurrence_binding
        self.admission.capture_resolution(original_occurrence_binding)
        self._entry_seals = tuple(_sha(entry) for entry in native)
        self._native_seal = _sha(native)
        self.admission.capture_resolution(self._scientific_state)

    def _scientific_state(self):
        """Keep the complete source witness and authority state fixed through all later phases."""
        return (
            self._native_seal,
            self._entry_seals,
            id(self._deposit_occurrence_binding),
            self._bindings,
            self._optional_state,
            self._supplied_policy,
            str(self.raw_dir),
            self.gss._seal,
        )

    def _entry(self, ordinal, record=None):
        """Check only the touched record before use; full cache checking belongs at checkpoints."""
        if type(ordinal) is not int or ordinal < 0 or ordinal >= len(self.records):
            _fail("native record ordinal changed")
        entry = self.records[ordinal]
        if _sha(entry) != self._entry_seals[ordinal]:
            _fail("captured native record witness changed before use")
        if record is not None and _sha(record) != entry["record_sha256"]:
            _fail("parsed native record changed before taxonomy use")
        return entry

    def observe_parent_choice(self, ordinal, record, target, inferred):
        """Retain the existing selected target and prove whether a supplied native taxid supports it."""
        try:
            self.require_fallback()
            entry = self._entry(ordinal, record)
            self.observe_selected_parent(ordinal, entry, target, inferred)
        except BaseException:
            self._poison()
            raise

    def observe_selected_parent(self, ordinal, entry, target, inferred):
        """Retain native supplied choices or an explicitly identified producer derivation."""
        if entry != self._entry(ordinal) or type(inferred) is not bool:
            _fail("invalid native record choice evidence")
        if target is not None and (not isinstance(target, str) or not re.fullmatch(r"NCBITaxon:[0-9]+", target)):
            _fail("invalid observed parent identifier")
        key = ordinal
        if key in self.parent_choices:
            _fail("native record parent choice was observed twice")
        direct = entry["direct_taxid"]
        self.require_fallback()
        if direct is None:
            plan = self._fallback.plan(ordinal)
            if plan is None or target != plan["early_target"] or inferred != plan["inferred"]:
                _fail("observed fallback choice differs from actual native reconstruction")
        expected_direct = None if entry.get("supplied_taxid_disposition") else direct
        if direct is not None and (target != expected_direct or inferred):
            _fail("direct parent choice differs from native supplied taxid priority")
        if direct is None and target is not None and not inferred:
            _fail("computed parent choice lost its derivation")
        self.parent_choices[key] = {"target": target, "inferred": bool(inferred), "ordinal": ordinal}
        self._choice_seals[key] = _sha(self.parent_choices[key])

    def _choice(self, key):
        """Do not let a changed previously observed choice silently seed deposit output."""
        self.require_fallback()
        self._entry(key)
        choice = self.parent_choices.get(key)
        if choice is None or _sha(choice) != self._choice_seals.get(key):
            _fail("observed record parent choice is missing or changed")
        return choice

    def lookup(self, ordinal, block):
        """Use the captured native block and consumed GSS rather than a constructor-time index."""
        entry = self._entry(ordinal)
        if block != entry["classification"].get("LPSN"):
            _fail("native LPSN block changed")
        key = ordinal
        if key in self.lookup_seen:
            _fail("native LPSN lookup was repeated")
        self.lookup_seen.add(key)
        return self.gss.lookup(block)["target"]

    def native_deposit_claims(self):
        """Recreate exact native token multiplicity and the already observed early parent choices."""
        claims = defaultdict(lambda: defaultdict(list))
        for ordinal, entry in enumerate(self.records):
            choice = self._choice(ordinal)
            if choice["target"] is None:
                continue
            for token in entry["deposits"]:
                claims[token["deposit"]][choice["target"]].append(entry["record_id"])
        return {deposit: dict(parents) for deposit, parents in claims.items()}

    def _claim_occurrences(self, subject, claims):
        """Join exact legacy claim lists to every sealed source-record/token occurrence."""
        if not callable(self._deposit_occurrence_binding) or self._deposit_occurrence_binding() != (True, True):
            _fail("original native deposit occurrence binding was lost")
        occurrences = self._deposit_occurrences.get(subject)
        if occurrences is None or _sha(occurrences) != self._deposit_occurrence_seals.get(subject):
            _fail("native deposit occurrence inventory missing or changed")
        witnesses = defaultdict(list)
        projected = defaultdict(list)
        for ordinal, token_index in occurrences:
            entry = self._entry(ordinal)
            token = entry["deposits"][token_index]
            if token["deposit"] != subject:
                _fail("deposit occurrence moved from its original source token")
            choice = self._choice(ordinal)
            parent = choice["target"]
            if parent is None:
                continue
            projected[parent].append(entry["record_id"])
            witnesses[parent].append({"native_record": entry, "selected_parent_choice": choice, "claim_parent": parent})
        if dict(projected) != claims:
            _fail("deposit claims differ from complete native occurrence evidence")
        return dict(witnesses)

    def resolve_deposits(self, claims, adapter_selector=None, *, recorded_ancestry=None):
        """
        Delegate scientific selection to the unchanged resolver with a fresh actual-read callback.

        Demand comes from actual resolver callbacks, including repeated calls
        across deposits. It is not guessed as the union of every candidate ID.
        The private per-batch cache preserves the old callback's query reuse.
        """
        if self._failed or self._ancestry is not None:
            _fail("invalid or repeated deposit-resolution phase")
        if claims != self.native_deposit_claims():
            _fail("resolver did not receive the complete original native deposit claims")
        demands = []
        cached = {}
        owner = None

        def ancestors(identifier):
            """Bind the authority lazily on the first query the unchanged resolver actually requests."""
            nonlocal owner
            demands.append(identifier)
            if identifier not in cached:
                if owner is None:
                    if recorded_ancestry is not None:
                        witness = recorded_ancestry.get("actual_queries")
                        if not isinstance(witness, dict) or not isinstance(witness.get("authority"), dict):
                            _fail("recorded zero/missing ancestry authority conflicts with actual query demand")
                        owner = FreshAncestryAuthority.from_recorded_authority(
                            witness["authority"], admission=self.admission
                        )
                    else:
                        if not callable(adapter_selector):
                            _fail("actual query demand requires the original adapter selector")
                        owner = FreshAncestryAuthority.from_resolved_adapter(
                            adapter_selector(), admission=self.admission
                        )
                    self._ancestry_owner = owner
                cached[identifier] = owner.ancestors(identifier)
            return cached[identifier]

        try:
            result = resolve_deposit_parents(claims, ancestors_of=ancestors, ancestry_failed=lambda _id: False)
            witness = owner.finish() if owner is not None else None
            # Rejoin demand to completed queries, retaining both callback and
            # physical-query multiplicities without relying on Python set order.
            counts = Counter(demands)
            queried = Counter(row["subject"] for row in witness["computed_queries"]) if witness else Counter()
            if queried != Counter({identifier: 1 for identifier in cached}) or set(counts) != set(cached):
                _fail("actual ancestry query evidence is incomplete or unexpectedly duplicated")
            ancestry = {
                "version": 1,
                "callback_demand_counts": sorted(counts.items()),
                "actual_queries": witness,
                "resolver_result_sha256": _sha(result),
            }
            # Compare JSON-normalized tuples/lists; actual query call order is
            # intentionally not presented as reproducible scientific evidence.
            if recorded_ancestry is not None and _json(ancestry) != _json(recorded_ancestry):
                _fail("recorded ancestry demand, query evidence or resolver result changed")
            self._ancestry = _json(ancestry)
            self._resolver_result = _json(result)
            self.admission.capture_resolution(lambda: (self._ancestry, self._resolver_result, id(self._ancestry_owner)))
            return result
        except BaseException:
            # An outer broad catch cannot later turn a failed native query into
            # successful completion or an apparently genuine zero-query source.
            self._poison()
            raise
        finally:
            if owner is not None:
                owner.close()

    def classify_deposit(self, subject, target, claims):
        """Direct support must name the selected parent; mixed ancestor derivations stay derived."""
        if not claims or target not in claims:
            _fail("selected deposit parent was not one of the original buffered claims")
        direct = []
        for parent, witnesses in self._claim_occurrences(subject, claims).items():
            for witness in witnesses:
                choice = witness["selected_parent_choice"]
                if not choice["inferred"]:
                    direct.append((choice["ordinal"], parent))
        direct_at_parent = any(parent == target for _, parent in direct)
        status = (
            "direct_at_selected_parent"
            if direct_at_parent
            else "mixed_direct_descendant_and_inferred_ancestor"
            if direct
            else "exclusively_name_inferred"
        )
        row = _edge(subject, target, inferred=not direct_at_parent)
        if subject in self.deposit_rows:
            _fail("resolved deposit was emitted more than once")
        self.deposit_rows[subject] = {"target": target, "claims": claims, "status": status, "row": row}
        return dict(row)

    def _audit_rows(self):
        """Reconstruct changed/native-ambiguity evidence without suppressing original source claims."""
        rows = []
        for ordinal, entry in enumerate(self.records):
            disposition = entry.get("supplied_taxid_disposition")
            if disposition is None:
                continue
            subject = _PREFIX + entry["record_id"]
            rows.append(
                {
                    "kind": "supplied_taxid_ambiguity",
                    "status": disposition["status"],
                    "subject": subject,
                    "object": "",
                    "native_evidence_json": _json(
                        {
                            "native_record": entry,
                            "selected_parent_choice": self._choice(ordinal),
                            "withheld_deposit_contributions": [
                                {"native_token": token, "edge": _edge(token["deposit"], entry["direct_taxid"])}
                                for token in entry["deposits"]
                            ],
                        }
                    ),
                    "lookup_evidence_json": _json(disposition),
                    "original_edge_json": _json(_edge(subject, entry["direct_taxid"])),
                    "emitted_edge_json": "null",
                    "consumed_inputs_json": self._bindings,
                }
            )
        for subject, item in sorted(self.deposit_rows.items()):
            claims = item["claims"]
            occurrences = self._claim_occurrences(subject, claims)
            if not any(
                witness["selected_parent_choice"]["inferred"]
                for witnesses in occurrences.values()
                for witness in witnesses
            ):
                continue
            evidence = [witness for parent in sorted(occurrences) for witness in occurrences[parent]]
            rows.append(
                {
                    "kind": "deposit",
                    "status": item["status"],
                    "subject": subject,
                    "object": item["target"],
                    "native_evidence_json": _json(
                        {
                            "claims": evidence,
                            "selected_parent": item["target"],
                            "candidate_parents": sorted(claims),
                            "computed_ancestry": self._deposit_ancestry(claims),
                        }
                    ),
                    "lookup_evidence_json": "",
                    "original_edge_json": _json(_edge(subject, item["target"])),
                    "emitted_edge_json": _json(item["row"]),
                    "consumed_inputs_json": self._bindings,
                }
            )
        for entry in self.records:
            block = entry["classification"].get("LPSN")
            lookup = self.gss.lookup(block)
            if len(lookup["original_ids"]) <= 1:
                continue
            target = lookup["target"]
            subject = _PREFIX + entry["record_id"]
            rows.append(
                {
                    "kind": "lpsn_lookup",
                    "status": "convergent_explicit_accepted_record" if target else "distinct_targets_unresolved",
                    "subject": subject,
                    "object": "lpsn:" + target if target else "",
                    "native_evidence_json": _json(entry),
                    "lookup_evidence_json": _json(lookup),
                    "original_edge_json": "null",
                    "emitted_edge_json": _json(_edge(subject, "lpsn:" + target)) if target else "null",
                    "consumed_inputs_json": self._bindings,
                }
            )
        self.require_fallback()
        for ordinal, entry in enumerate(self.records):
            if entry["direct_taxid"] is not None:
                continue
            plan = self._fallback.plan(ordinal)
            subject = _PREFIX + entry["record_id"]
            rejected = []
            for lookup in plan["lookups"]:
                if not lookup["terminal"]:
                    continue
                for candidate in lookup["decision"]["candidates"]:
                    target = candidate["candidate"]["id"]
                    rejected.append(
                        {
                            "kind": "attempted_record_parent_not_native_supplied_id",
                            "edge": _edge(subject, target, inferred=True),
                        }
                    )
                    # Deposit parents use ONLY the early ordinary choice.
                    if lookup["decision"]["route"] == "ordinary_rank":
                        for token in entry["deposits"]:
                            rejected.append(
                                {
                                    "kind": "attempted_derived_deposit_parent",
                                    "native_token": token,
                                    "edge": _edge(token["deposit"], target, inferred=True),
                                }
                            )
            rows.append(
                {
                    "kind": "fallback",
                    "status": plan["status"],
                    "subject": subject,
                    "object": plan["early_target"] or "",
                    "native_evidence_json": _json({"native_record": entry, "rejected_parent_proposals": rejected}),
                    "lookup_evidence_json": _json(plan["lookups"]),
                    "original_edge_json": "null",
                    "emitted_edge_json": _json(
                        [_edge(left, right, inferred=True) for left, right in plan["parent_pairs"]]
                    ),
                    "consumed_inputs_json": _json({**json.loads(self._bindings), **self._fallback.selected_roles}),
                }
            )
        return rows

    def _deposit_ancestry(self, claims):
        """Keep the actual computed support distinct from the external native-row acceptance proof."""
        if self._ancestry is None:
            _fail("deposit evidence requires completed query demand accounting")
        witness = json.loads(self._ancestry)["actual_queries"]
        if len(claims) < 2:
            return None
        if witness is None:
            _fail("multiple-parent deposit lost actual query authority")
        return {
            "authority": witness["authority"],
            "native_version_statements": witness["native_version_statements"],
            "computed_queries": [row for row in witness["computed_queries"] if row["subject"] in claims],
            "asserted_native_parent_rows": False,
        }

    def _completion(self):
        """Bind completion separately from the later output-readiness transition."""
        return (
            self._completed,
            self._contract,
            _sha(self.parent_choices),
            _sha(self._choice_seals),
            tuple(sorted(self.lookup_seen)),
        )

    @property
    def outputs_ready(self):
        """Return a read-only output phase; callers may not erase completion to skip checks."""
        return self._outputs_ready

    @property
    def contract(self):
        """Return a copy only after complete producer taxonomy observation."""
        if self._contract is None:
            _fail("taxonomy producer completion is missing")
        return json.loads(self._contract)

    def complete(self, buffered_claims, resolved, contested, audit_writer=None):
        """Reconcile every original claim and write the mandatory audit before publication."""
        if self._failed or self._completed or self._ancestry is None:
            _fail("taxonomy completion repeated")
        if _json((resolved, contested)) != self._resolver_result:
            _fail("emitter result differs from the unchanged resolver's actual decision")
        expected_keys = set(range(len(self.records)))
        expected_lookups = {
            ordinal for ordinal, entry in enumerate(self.records) if entry["classification"].get("LPSN")
        }
        if set(self.parent_choices) != expected_keys or self.lookup_seen != expected_lookups:
            _fail("producer omitted a native parent choice or LPSN lookup")
        if self.native_deposit_claims() != buffered_claims:
            _fail("buffered deposit claims lost native witness multiplicity")
        resolved_rows = list(resolved)
        resolved = dict(resolved_rows)
        if (
            len(resolved) != len(resolved_rows)
            or len(resolved) != len(self.deposit_rows)
            or resolved != {key: item["target"] for key, item in self.deposit_rows.items()}
        ):
            _fail("emitted deposits differ from the unchanged resolver result")
        contested_rows = list(contested)
        contested = {entry[0]: entry for entry in contested_rows}
        if len(contested) != len(contested_rows):
            _fail("duplicate contested deposit disposition")
        expected_contested = {key for key, parents in buffered_claims.items() if len(parents) > 1}
        if set(contested) != expected_contested:
            _fail("contested deposit inventory differs from native multiple-parent claims")
        for key, entry in contested.items():
            if len(entry) != 4 or entry[1] != buffered_claims[key]:
                _fail("contested deposit lost its complete native claims")
            resolution, target = entry[2:]
            if resolution == RESOLUTION_COLLAPSED:
                if not target or resolved.get(key) != target or target not in entry[1]:
                    _fail("collapsed deposit differs from the unchanged resolution result")
            elif resolution in (RESOLUTION_SUPPRESSED, RESOLUTION_SUPPRESSED_NO_ANCESTRY):
                if target or key in resolved:
                    _fail("suppressed deposit gained a parent")
            else:
                _fail("unknown deposit resolution status")
        if set(resolved) | set(contested) != set(buffered_claims):
            _fail("resolved/suppressed deposit accounting is incomplete")
        audits = self._audit_rows()
        if audit_writer is not None:
            for row in audits:
                audit_writer.writerow([row[field] for field in AUDIT_FIELDS])
        self.require_fallback()
        contract = {
            "version": 2,
            "raw_locator": str(self.raw_dir),
            "consumed_inputs": json.loads(self._bindings),
            "optional_gss": json.loads(self._optional_state),
            "native_records": len(self.records),
            "native_projection_sha256": self._native_seal,
            "gss_projection_sha256": self.gss._seal,
            "ancestry": json.loads(self._ancestry),
            "audit_rows": len(audits),
            "audit_projection_sha256": _sha(audits),
            "fallback_choices": [
                {"record_id": entry["record_id"], **self.parent_choices[ordinal]}
                for ordinal, entry in enumerate(self.records)
                if entry["direct_taxid"] is None
            ],
            "contested": list(contested.values()),
            "resolved_deposit_count": len(resolved),
            "resolved_deposit_sha256": _sha(sorted(resolved.items())),
            "members": sorted(_MEMBERS),
            "fallback_native_evidence": self._fallback.contract,
            "fallback_target_identity_independently_validated": True,
        }
        self._contract = _json(contract)
        self._completed = True
        self.admission.capture_resolution(self._completion)

    def mark_output_ready(self, snapshots):
        """Permit graph checks only after writers close, and make that transition irreversible."""
        self.verify_native(snapshots)
        if not self._completed or self._outputs_ready:
            _fail("invalid taxonomy output readiness transition")
        self._outputs_ready = True
        self.admission.capture_resolution(lambda: self._outputs_ready)

    def verify_native(self, snapshots):
        """Check original roles and complete parsed state; failure remains sticky until a real rerun."""
        if self._failed:
            _fail("a prior taxonomy checkpoint failed")
        try:
            self.admission.verify(metadata_only=True)
            expected = json.loads(self._bindings)
            for role in (RAW_ROLE, GSS_ROLE, supplied_taxid_policy.ROLE):
                if snapshots.get(role) != expected.get(role):
                    _fail("original consumed input role changed: " + role)
            verify_optional_inputs(
                _OptionalGss,
                {"version": 1, "inputs": {GSS_ROLE: json.loads(self._optional_state)}},
                snapshots,
                admission=self.admission,
                input_dir=self.raw_dir,
            )
            if _sha(self.records) != self._native_seal:
                _fail("captured native record witnesses changed")
            self.gss.verify()
            self.require_fallback()
            self._fallback.verify(snapshots)
            if self._ancestry_owner is not None:
                self._ancestry_owner.verify()
            for key in self.parent_choices:
                self._choice(key)
            if self._completed and _sha(self._audit_rows()) != self.contract["audit_projection_sha256"]:
                _fail("completed taxonomy witness or emission state changed")
        except BaseException:
            self._poison()
            raise

    def verify(self, snapshots, *, output_dir=None, quoting=csv.QUOTE_NONE, finalized=False):
        """Retain a failed output checkpoint as well as every mandatory native-role checkpoint."""
        if self._failed:
            _fail("a prior taxonomy checkpoint failed")
        try:
            self.verify_native(snapshots)
            if output_dir is not None:
                if not self.outputs_ready:
                    _fail("output verification requested before producer writers closed")
                self.verify_output(output_dir, quoting=quoting, finalized=finalized)
        except BaseException:
            self._poison()
            raise

    def _finalized_expectations(self, expected, directory):
        """
        Admit only exact native-backed object retirement at the existing upstream finalization boundary.

        The producer contract/audit still contains its raw chosen parent. The
        source finalizer's separate report must preserve that entire row, and
        the same local taxdump must independently prove the explicit replacement.
        No original_object wildcard, endpoint exclusion, or model-based rewrite
        is allowed here. This reads evidence and never edits the graph.
        """
        import tarfile

        from kg_microbe.merge_utils.external_node_closure import _taxdump_records
        from kg_microbe.utils.external_identifiers import load_taxid_merges

        report_path = Path(directory) / "source_reference_resolution.tsv"
        report_admission = SourceAdmission()
        report_admission.capture(report_path)
        projections = {}
        expected_pairs = {(row[SUBJECT_COLUMN], row[OBJECT_COLUMN]) for row in expected.values()}
        for item in graph_rows(report_path, quoting=csv.QUOTE_MINIMAL):
            if not item.get("original_edge_json"):
                continue
            original = json.loads(item["original_edge_json"])
            pair = original.get(SUBJECT_COLUMN), original.get(OBJECT_COLUMN)
            if pair not in expected_pairs or item.get("disposition") == "authority_declaration":
                continue
            key = _row_key(original)
            if key not in expected:
                _fail("unsupported or incomplete finalized taxonomy reference disposition")
            prior = expected[key]
            if (
                not _equal_row(original, prior)
                or not str(prior[OBJECT_COLUMN]).startswith("NCBITaxon:")
                or item.get("original_id") != prior[OBJECT_COLUMN]
                or item.get("disposition") != "retired_id_replaced"
                or item.get("authority") != "taxdump.tar.gz"
                or not re.fullmatch(r"NCBITaxon:[0-9]+", item.get("canonical_id", ""))
                or item["canonical_id"] == prior[OBJECT_COLUMN]
            ):
                _fail("unsupported or incomplete finalized taxonomy reference disposition")
            decision = item["canonical_id"], item.get("authority_sha256")
            if projections.setdefault(key, decision) != decision:
                _fail("conflicting finalized taxonomy reference dispositions")
        if not projections:
            report_admission.verify()
            return expected
        taxdump = self.raw_dir / "taxdump.tar.gz"
        identity = self.admission.capture(taxdump)
        resolved = taxdump.resolve()
        sealed_identity = _json(identity)
        original_stamp = self.admission.stamps[resolved]

        def original_native_binding():
            """Keep the actual source-finalization authority alive after parsed decisions are used."""
            if (
                self.admission.bindings.get(taxdump) != resolved
                or _json(self.admission.identities.get(resolved)) != sealed_identity
                or self.admission.stamps.get(resolved) != original_stamp
            ):
                _fail("native retirement authority admission was lost")
            return taxdump, resolved, sealed_identity, original_stamp

        self.admission.capture_resolution(original_native_binding)
        with tarfile.open(taxdump) as archive:
            members = archive.getmembers()
            for name in ("merged.dmp", "nodes.dmp", "names.dmp"):
                selected = [member for member in members if member.name == name]
                if len(selected) != 1 or not selected[0].isfile():
                    _fail("native retirement archive has missing or ambiguous authority members")
        replacements = load_taxid_merges(self.raw_dir)
        targets = {canonical.removeprefix("NCBITaxon:") for canonical, _sha256 in projections.values()}
        originals = {expected[key][OBJECT_COLUMN].removeprefix("NCBITaxon:") for key in projections}
        records = _taxdump_records(taxdump, targets | originals)
        projected = dict(expected)
        for key, (canonical, sha256) in projections.items():
            old = expected[key][OBJECT_COLUMN].removeprefix("NCBITaxon:")
            target = canonical.removeprefix("NCBITaxon:")
            declaration = records.get(target, {})
            if (
                sha256 != identity["sha256"]
                or replacements.get(old) != target
                or old in records
                or not declaration.get("name")
                or not declaration.get("prokaryote")
            ):
                _fail("native authority does not prove the finalized taxonomy replacement")
            row = dict(projected.pop(key))
            row[OBJECT_COLUMN] = canonical
            row[ORIGINAL_OBJECT_COLUMN] = expected[key][OBJECT_COLUMN]
            projected_key = _row_key(row)
            if projected_key in projected:
                _fail("unreviewed finalization collapse of scoped taxonomy observations")
            projected[projected_key] = row
        self.admission.verify()
        report_admission.verify()
        return projected

    def verify_output(self, directory, *, quoting=csv.QUOTE_NONE, finalized=False):
        """Require every exact lookup/deposit row while leaving other graph assertions outside this scope."""
        if not self._completed:
            _fail("output verification requires completed native accounting")
        directory = Path(directory)
        with (directory / AUDIT_FILE).open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
            if reader.fieldnames != list(AUDIT_FIELDS) or list(reader) != self._audit_rows():
                _fail("mandatory taxonomy audit missing, reordered, forged or incomplete")
        expected = {}
        fallback_subjects = set()
        withheld_subjects = {
            _PREFIX + entry["record_id"] for entry in self.records if entry.get("supplied_taxid_disposition")
        }
        self.require_fallback()
        for ordinal, entry in enumerate(self.records):
            if entry["direct_taxid"] is not None:
                continue
            fallback_subjects.add(_PREFIX + entry["record_id"])
            plan = self._fallback.plan(ordinal)
            # Orphan provisional genera have no outgoing pair but remain scoped nodes.
            fallback_subjects.update(node["id"] for node in plan["provisional_nodes"])
            for subject, target in plan["parent_pairs"]:
                fallback_subjects.add(subject)
                row = _edge(subject, target, inferred=True)
                expected[_row_key(row)] = row
        for entry in self.records:
            subject = _PREFIX + entry["record_id"]
            if entry["direct_taxid"] is not None and subject in fallback_subjects and subject not in withheld_subjects:
                row = _edge(subject, entry["direct_taxid"])
                expected[_row_key(row)] = row
            target = self.gss.lookup(entry["classification"].get("LPSN"))["target"]
            if target:
                row = _edge(_PREFIX + entry["record_id"], "lpsn:" + target)
                expected[_row_key(row)] = row
        for item in self.deposit_rows.values():
            expected[_row_key(item["row"])] = item["row"]
        if finalized:
            expected = self._finalized_expectations(expected, directory)
        found = Counter()
        for row in graph_rows(directory / "edges.tsv", quoting=quoting):
            if row[PREDICATE_COLUMN] != SUBCLASS_PREDICATE:
                continue
            subject, target = row[SUBJECT_COLUMN], row[OBJECT_COLUMN]
            in_scope = (
                (
                    subject in withheld_subjects
                    and target.startswith(("NCBITaxon:", "kgmicrobe.genus:", "kgmicrobe.species:"))
                )
                or (subject.startswith(_PREFIX) and target.startswith("lpsn:"))
                or (
                    subject.startswith("kgmicrobe.strain:")
                    and not subject.startswith(_PREFIX)
                    and target.startswith("NCBITaxon:")
                )
                or (
                    subject in fallback_subjects
                    and target.startswith(("NCBITaxon:", "kgmicrobe.genus:", "kgmicrobe.species:"))
                )
                or (
                    target in fallback_subjects
                    and subject.startswith(
                        ("NCBITaxon:", "kgmicrobe.genus:", "kgmicrobe.species:", "kgmicrobe.strain:")
                    )
                )
            )
            if not in_scope:
                continue
            key = _row_key(row)
            if key not in expected or not _equal_row(row, expected[key]):
                _fail("unexpected or changed scoped taxonomy row")
            found[key] += 1
        if found != Counter({key: 1 for key in expected}):
            _fail("missing or duplicate scoped taxonomy row")

    def require_fallback(self):
        """Refuse a lost child instead of downgrading inference to old unaudited choices."""
        if self._fallback is None:
            _fail("mandatory native fallback child missing; rerun BacDive")

    def prepare_fallback(self, snapshots, *, selected_path, opener, adapter_selector=None, recorded=None):
        """Compose one source-derived child after the existing native observer, before output."""
        try:
            if self._native_seal is None or self._fallback is not None:
                _fail("native fallback preparation is missing its source or was repeated")
            self._fallback = FallbackEvidence(
                self.records,
                snapshots,
                raw_role=RAW_ROLE,
                selected_path=selected_path,
                opener=opener,
                adapter_selector=adapter_selector,
                recorded=recorded,
                admission=self.admission,
            )
            self.admission.capture_resolution(lambda: id(self._fallback))
        except BaseException:
            self._poison()
            raise

    def fallback_choice(self, ordinal, producer_cache):
        """Use actual source/native planning before any inferred parent node or deposit is emitted."""
        try:
            self.require_fallback()
            return self._fallback.select_ordinary(ordinal, producer_cache)
        except BaseException:
            self._poison()
            raise

    def supplied_parent_withheld(self, ordinal, record):
        """Keep unresolved supplied IDs distinct from the missing-ID fallback cohort."""
        return self._entry(ordinal, record).get("supplied_taxid_disposition") is not None

    def emit_fallback_hierarchy(self, ordinal, transform, node_writer, edge_writer):
        """Emit the already reconstructed late hierarchy using the existing node writers."""
        try:
            self.require_fallback()
            plan = self._fallback.plan(ordinal)
            if plan is None or plan["early_target"]:
                _fail("late fallback emitter has the wrong source scope")
            for node in plan["provisional_nodes"]:
                actual = (
                    transform._create_provisional_genus_node(node["genus"], node_writer)
                    if node["kind"] == "genus"
                    else transform._create_provisional_species_node(node["genus"], node["species"], node_writer)
                )
                if actual != node["id"]:
                    _fail("provisional node emitter changed its original identifier formula")
            for subject, target in plan["parent_pairs"]:
                row = _edge(subject, target, inferred=True)
                edge_writer.writerow([row.get(column, "") for column in transform.edge_header])
        except BaseException:
            self._poison()
            raise


def prepare_fallback(transform, selected_path, adapter_selector):
    """Track an actual immutable selected-label read without retaining constructor lookup caches."""
    snapshots = transform.consumed_input_snapshots

    @contextmanager
    def opener(role, path):
        """Consume the selected native lookup through the producer's immutable input stream."""
        with transform.consume_input(role, path) as stream:
            snapshots[role] = transform.consumed_input_snapshots[role]
            yield stream

    transform._taxonomy_evidence_guard.prepare_fallback(
        snapshots,
        selected_path=selected_path,
        opener=opener,
        adapter_selector=adapter_selector,
    )


def prepare(transform):
    """Consume GSS before output creation and wait for the existing actual raw-read observer."""
    with transform.consume_optional_input(GSS_ROLE) as stream:
        index = LpsnIndex(stream)
    optional = transform.optional_consumed_inputs["inputs"][GSS_ROLE]
    bindings = {GSS_ROLE: transform.consumed_input_snapshots[GSS_ROLE]} if optional["sha256"] is not None else {}
    with transform.consume_input(supplied_taxid_policy.ROLE, supplied_taxid_policy.POLICY_PATH) as stream:
        policy = supplied_taxid_policy.load_policy(stream)
    bindings[supplied_taxid_policy.ROLE] = transform.consumed_input_snapshots[supplied_taxid_policy.ROLE]
    guard = TaxonomyEvidence(transform.input_base_dir, index, bindings, optional, supplied_policy=policy)
    transform._taxonomy_evidence_guard = guard
    return guard


def split_native_contract(recorded):
    """Require the new child while preserving the exact independently reviewed NCIT contract."""
    if not isinstance(recorded, dict) or not isinstance(recorded.get("taxonomy"), dict):
        _fail("mandatory taxonomy producer contract missing; rerun BacDive")
    ncit = dict(recorded)
    taxonomy = ncit.pop("taxonomy")
    return ncit, taxonomy


def verify_recorded(contract, snapshots, raw_dir, output_dir, *, optional_state, members=None, admission=None):
    """
    Rejoin the mandatory complete native cohort and exact lookup decisions during admission.

    The mandatory fallback child re-reads the original selected/native inputs,
    rederives all eligible records and predicts exact current parent rows. This
    does not upgrade name-derived inference into native supplied-ID observations.
    """
    admission = admission or SourceAdmission()
    raw_dir = Path(raw_dir).absolute()
    if not isinstance(contract, dict) or contract.get("version") != 2 or contract.get("raw_locator") != str(raw_dir):
        _fail("mandatory taxonomy contract or original raw locator missing")
    if members is not None and set(members) != _MEMBERS:
        _fail("recorded taxonomy graph member scope changed")
    optional = {"version": 1, "inputs": {GSS_ROLE: optional_state}}
    verify_optional_inputs(_OptionalGss, optional, snapshots, admission=admission, input_dir=raw_dir)
    raw = snapshots.get(RAW_ROLE)
    if (
        not isinstance(raw, dict)
        or set(raw) != {"path", "sha256"}
        or raw["path"] != str((raw_dir / _RAW_FILE).resolve())
    ):
        _fail("original actual native read role missing or rebound")
    if admission.capture(raw_dir / _RAW_FILE)["sha256"] != raw["sha256"]:
        _fail("native BacDive source differs from original immutable read")
    if optional_state["sha256"] is None:
        index = LpsnIndex(None)
        bindings = {}
    else:
        with (raw_dir / "lpsn_gss.csv").open(newline="", encoding="utf-8") as stream:
            index = LpsnIndex(stream)
        bindings = {GSS_ROLE: snapshots[GSS_ROLE]}
    policy_binding = snapshots.get(supplied_taxid_policy.ROLE)
    if policy_binding != {
        "path": str(supplied_taxid_policy.POLICY_PATH.resolve()),
        "sha256": supplied_taxid_policy.POLICY_SHA256,
    }:
        _fail("original supplied-taxid policy binding missing or changed")
    if admission.capture(supplied_taxid_policy.POLICY_PATH)["sha256"] != policy_binding["sha256"]:
        _fail("original supplied-taxid policy bytes changed")
    with supplied_taxid_policy.POLICY_PATH.open(encoding="utf-8") as stream:
        policy = supplied_taxid_policy.load_policy(stream)
    bindings[supplied_taxid_policy.ROLE] = policy_binding
    guard = TaxonomyEvidence(raw_dir, index, bindings, optional_state, supplied_policy=policy, admission=admission)
    with (raw_dir / _RAW_FILE).open("rb") as stream:
        guard.capture_records(ncit_category_claims._native_records(stream), snapshots)
    native_fallback = contract.get("fallback_native_evidence")
    if not isinstance(native_fallback, dict):
        _fail("mandatory original fallback native contract missing")
    selected_input = native_fallback.get("selected_input")
    # Zero sources never consume the placeholder; active sources must carry
    # their original lexical selected-authority locator and presence/absence.
    selected_path = (
        selected_input.get("locator") if isinstance(selected_input, dict) else raw_dir / "unused-zero-fallback-locator"
    )
    guard.prepare_fallback(
        snapshots,
        selected_path=selected_path,
        opener=lambda role, path: recorded_selected_opener(snapshots, admission, role, path),
        recorded=native_fallback,
    )
    fallback = contract.get("fallback_choices")
    if not isinstance(fallback, list) or any(
        not isinstance(row, dict) or set(row) != {"record_id", "target", "inferred", "ordinal"} for row in fallback
    ):
        _fail("derived parent-choice inventory missing or malformed")
    if any(type(row["ordinal"]) is not int for row in fallback):
        _fail("recorded parent choice moved from its original coordinate")
    fallback_by_ordinal = {row["ordinal"]: row for row in fallback}
    expected_fallback = {ordinal for ordinal, entry in enumerate(guard.records) if entry["direct_taxid"] is None}
    if len(fallback_by_ordinal) != len(fallback) or set(fallback_by_ordinal) != expected_fallback:
        _fail("derived parent-choice inventory omitted or duplicated native records")
    for ordinal, entry in enumerate(guard.records):
        if entry["direct_taxid"] is not None:
            target = None if entry.get("supplied_taxid_disposition") else entry["direct_taxid"]
            guard.observe_selected_parent(ordinal, entry, target, False)
        else:
            choice = fallback_by_ordinal[ordinal]
            if choice["record_id"] != entry["record_id"]:
                _fail("recorded parent choice moved from its original coordinate")
            guard.observe_selected_parent(ordinal, entry, choice["target"], choice["inferred"])
        block = entry["classification"].get("LPSN")
        if block:
            guard.lookup(ordinal, block)
    claims = guard.native_deposit_claims()
    ancestry = contract.get("ancestry")
    if not isinstance(ancestry, dict):
        _fail("mandatory active or genuine-zero ancestry contract missing")
    resolved, contested = guard.resolve_deposits(claims, recorded_ancestry=ancestry)
    for subject, target in resolved:
        guard.classify_deposit(subject, target, claims[subject])
    guard.complete(claims, resolved, contested)
    if _json(guard.contract) != _json(contract):
        _fail("recorded taxonomy contract does not equal complete actual-native reconstruction")
    for name in (*sorted(_MEMBERS), AUDIT_FILE, "source_reference_resolution.tsv"):
        admission.capture(Path(output_dir) / name)
    guard.mark_output_ready(snapshots)
    guard.verify(snapshots, output_dir=output_dir, finalized=True)
    # Retain the original role membership as well as bytes after this method
    # returns its admission. In particular, absent GSS cannot gain a forged role.
    admission.capture_resolution(
        lambda: {role: snapshots.get(role) for role in (RAW_ROLE, GSS_ROLE, supplied_taxid_policy.ROLE)}
    )
    admission.capture_resolution(lambda: _json(optional_state))
    admission.verify(metadata_only=True)
    return guard
