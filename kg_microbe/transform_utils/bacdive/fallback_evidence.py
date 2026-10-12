"""
Bind source-derived fallback choices to the existing BacDive taxonomy lifecycle.

This is composed into taxonomy_evidence, not a second producer/finalizer or a
graph-repair pass. All native choices are prepared before
emission; no output/audit inventory serves as its independent input authority.
"""

import csv
import hashlib
import inspect
import json
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from kg_microbe.transform_utils.bacdive.fallback_native_authority import FreshFallbackAuthority
from kg_microbe.transform_utils.bacdive.fallback_selection import assess_candidates
from kg_microbe.transform_utils.constants import (
    CLASS,
    DOMAIN,
    FAMILY,
    FULL_SCIENTIFIC_NAME,
    GENUS,
    ID_COLUMN,
    NAME_COLUMN,
    ORDER,
    PHYLUM,
    PROVISIONAL_GENUS_PREFIX,
    PROVISIONAL_SPECIES_PREFIX,
    SPECIES,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired

SELECTED_ROLE = "bacdive_fallback_selected_ncbitaxon"
_FIELDS = (SPECIES, GENUS, FAMILY, ORDER, CLASS, PHYLUM, DOMAIN)
_PARSER_NAMES = (
    "_normalize_special_taxon_names",
    "_higher_rank_candidates",
    "_genus_for_unmatched_name",
    "_parse_genus_from_scientific_name",
    "_ncbitaxon_fallback_key",
)


def _json(value):
    """Preserve complete rows and source types in deterministic detached evidence."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(value):
    """Digest parsed evidence without claiming it is the native lexical byte stream."""
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _fail(message):
    """Keep ontology infrastructure failures outside per-record fallback handling."""
    raise SourceFinalizationRequired("BacDive fallback evidence: " + message)


class FallbackEvidence:
    """Retain one completed, source-derived inference plan and its owned native query guard."""

    def __init__(
        self,
        entries,
        snapshots,
        *,
        raw_role,
        selected_path,
        opener=None,
        adapter_selector=None,
        recorded=None,
        admission,
    ):
        """Read selected/native authorities only when actual raw records demand inference."""
        # Local import avoids a producer/helper import cycle and reuses the
        # existing stateless parser/mapping rules rather than copying them.
        from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform

        self.admission = admission
        self._failed = False
        self._owner = None
        self._contract = None
        self._plans = None
        self._selected_binding = None
        self.admission.capture_resolution(lambda: self._failed)
        original_entries = tuple(entries)
        entry_seal = _sha(original_entries)
        source_role = _json(snapshots.get(raw_role))
        if json.loads(source_role) is None:
            _fail("original raw read is required even for a genuine zero cohort")
        raw_binding = json.loads(source_role)
        if set(raw_binding) != {"path", "sha256"} or not Path(raw_binding["path"]).is_absolute():
            _fail("original raw role has an invalid locator or shape")
        raw_path = Path(raw_binding["path"])
        raw_identity = self.admission.capture(raw_path)
        if raw_identity["sha256"] != raw_binding["sha256"]:
            _fail("actual source differs from original immutable BacDive read")
        raw_resolved = raw_path.resolve()
        raw_stamp = self.admission.stamps[raw_resolved]
        # Detach the finite inference entries. TaxonomyEvidence separately owns
        # and verifies the full raw projection. Do not hash all99k native entries
        # on each individual query's admission callback.
        eligible = json.loads(
            _json({ordinal: entry for ordinal, entry in enumerate(original_entries) if entry["direct_taxid"] is None})
        )
        parser = BacDiveTransform.__new__(BacDiveTransform)
        parsers = tuple(getattr(BacDiveTransform, name) for name in _PARSER_NAMES)
        parser_path = Path(inspect.getfile(BacDiveTransform)).absolute()
        parser_identity = self.admission.capture(parser_path)
        parser_resolved = parser_path.resolve()
        parser_stamp = self.admission.stamps[parser_resolved]
        parser_map = _json(BacDiveTransform._UNIDENTIFIED_TAXON_MAP)
        selected_locator = Path(selected_path).absolute()

        def verify_original():
            """Do not let later erased roles or substituted cached plans redefine the initial scope."""
            if self._failed:
                _fail("a prior fallback checkpoint failed")
            if (
                self.admission.bindings.get(raw_path) != raw_resolved
                or self.admission.identities.get(raw_resolved) != raw_identity
                or self.admission.stamps.get(raw_resolved) != raw_stamp
            ):
                _fail("original native source admission was lost")
            if (
                self.admission.bindings.get(parser_path) != parser_resolved
                or self.admission.identities.get(parser_resolved) != parser_identity
                or self.admission.stamps.get(parser_resolved) != parser_stamp
            ):
                _fail("original parser implementation admission was lost")
            if tuple(getattr(BacDiveTransform, name) for name in _PARSER_NAMES) != parsers:
                _fail("actual source parser implementation changed")
            if _json(BacDiveTransform._UNIDENTIFIED_TAXON_MAP) != parser_map:
                _fail("actual source special-name mapping changed")
            return entry_seal, source_role, tuple(id(value) for value in parsers), parser_map

        self.admission.capture_resolution(verify_original)
        self._check_original = verify_original
        selected_rows, label_index, special_index = [], defaultdict(set), defaultdict(set)
        facts, demands = {}, []
        plans = {}
        try:
            # Derive a finite STRING universe without validating unused lower
            # fields. Native absence of any actual lookup demand is a truthful
            # zero authority contract, even for a record without a supplied ID.
            names = set()
            for entry in eligible.values():
                block = entry["classification"] or {}
                names.update(value for field in _FIELDS if isinstance(value := block.get(field), str) and value)
                full = block.get(FULL_SCIENTIFIC_NAME, "unknown")
                if isinstance(full, str):
                    normalized, special = parser._normalize_special_taxon_names(full)
                    if special:
                        names.update(parser._higher_rank_candidates(normalized))
                    else:
                        genus = parser._genus_for_unmatched_name(full, False)
                        if genus:
                            names.add(genus)
            if names:
                folded = {name.lower() for name in names}
                present = selected_locator.exists()
                # Capture lexical presence/absence before consuming. This is a
                # transformed authority path, not an optional raw-file role.
                identity = self.admission.capture(selected_locator, optional=True)
                if present:
                    if opener is None:
                        _fail("actual selected-label read opener is missing")
                    with opener(SELECTED_ROLE, selected_locator) as stream:
                        reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
                        header = reader.fieldnames
                        if (
                            header is None
                            or len(header) != len(set(header))
                            or not {ID_COLUMN, NAME_COLUMN} <= set(header)
                        ):
                            _fail("selected taxonomy header is missing required or unique fields")
                        for ordinal, row in enumerate(reader, 1):
                            if None in row or None in row.values() or any("\x00" in value for value in row.values()):
                                _fail("malformed selected taxonomy row")
                            name = row[NAME_COLUMN].lower()
                            synonyms = {
                                value.strip().lower() for value in row.get("synonym", "").split("|") if value.strip()
                            }
                            matches = ({name} | synonyms) & folded
                            if not matches:
                                continue
                            if not row[ID_COLUMN].startswith("NCBITaxon:"):
                                _fail("matching selected taxonomy row is not an NCBI declaration")
                            selected_rows.append(
                                {"record_ordinal": ordinal, "physical_line_end": reader.line_num, "full_row": row}
                            )
                            if name in folded:
                                label_index[name].add(row[ID_COLUMN])
                            for match in matches:
                                special_index[match].add(row[ID_COLUMN])
                    role = snapshots.get(SELECTED_ROLE)
                    if role != {"path": str(selected_locator.resolve()), "sha256": identity["sha256"]}:
                        _fail("selected taxonomy was not read under its exact original role")
                else:
                    if SELECTED_ROLE in snapshots:
                        _fail("an absent selected authority gained a consumed role")
                    role = None
                self._selected_binding = _json({"locator": str(selected_locator), "identity": identity, "role": role})
                original_resolved = selected_locator.resolve()
                original_stamp = self.admission.stamps.get(original_resolved)

                def selected_obligation():
                    """Preserve present AND absent selected-input obligations after query completion."""
                    if self.admission.bindings.get(selected_locator) != original_resolved:
                        _fail("original selected taxonomy locator guard was lost")
                    if present:
                        if (
                            self.admission.identities.get(original_resolved) != identity
                            or self.admission.stamps.get(original_resolved) != original_stamp
                        ):
                            _fail("original selected taxonomy read guard was lost")
                    elif original_resolved not in self.admission.absent:
                        _fail("original selected taxonomy absence guard was lost")
                    return self._selected_binding, original_resolved, original_stamp

                self.admission.capture_resolution(selected_obligation)
                if recorded is None:
                    if not callable(adapter_selector):
                        _fail("actual inference requires an original native adapter selector")
                    self._owner = FreshFallbackAuthority.from_resolved_adapter(
                        adapter_selector(), admission=self.admission
                    )
                else:
                    native = recorded.get("native_queries")
                    if not isinstance(native, dict) or not isinstance(native.get("connection"), dict):
                        _fail("recorded zero native authority conflicts with actual source inference")
                    self._owner = FreshFallbackAuthority.from_recorded_authority(
                        native["connection"].get("authority"), admission=self.admission
                    )
                owner = self._owner
                owner.prime_exact_labels(tuple(sorted(names)))

                def native_facts(identifier):
                    """Each actual indexed declaration is physically read once by the owned child."""
                    if identifier not in facts:
                        facts[identifier] = owner.candidate_facts(identifier)
                    return json.loads(_json(facts[identifier]))

                def lookup(entry, query, field, route="ordinary_rank", token=None):
                    """Preserve selected-tier priority without claiming an all-native homonym search."""
                    if not isinstance(query, str) or not query:
                        _fail("visited fallback selector is not nonempty text")
                    special = route == "special_higher_rank"
                    ids = sorted((special_index if special else label_index).get(query.lower(), ()))
                    mode = "special_selected_name_casefold" if special else "selected_label_casefold"
                    if not ids and not special:
                        ids = owner.exact_label_candidates(query)
                        mode = "native_exact_label"
                    candidates = [native_facts(identifier) for identifier in ids]
                    # The existing special route only considers higher ranks
                    # and requires lexical compatibility with the source token.
                    # Preserve that filter; native domain rejection remains terminal.
                    excluded = []
                    if special:
                        retained = []
                        word = token.strip().lower()
                        for candidate in candidates:
                            native_names = [value.lower() for value in candidate["labels"] + candidate["synonyms"]]
                            plausible = any(
                                word in name or name in word or min(len(word), len(name)) >= 8 and word[:8] == name[:8]
                                for name in native_names
                            )
                            if (
                                candidate["ranks"]
                                and candidate["ranks"][0] in {"family", "order", "class", "phylum"}
                                and plausible
                            ):
                                retained.append(candidate)
                            else:
                                excluded.append(candidate)
                        candidates = retained
                    decision = assess_candidates(
                        query, field, entry["classification"], candidates, route=route, match_mode=mode
                    )
                    evidence = {
                        "decision": json.loads(decision.evidence_json),
                        "status": decision.status,
                        "terminal": decision.terminal,
                        "target": decision.identifier,
                        "special_filter_exclusions": excluded,
                    }
                    demands.append({"record_id": entry["record_id"], **evidence})
                    return decision, evidence

                for ordinal, entry in eligible.items():
                    block = entry["classification"] or {}
                    early = None
                    terminal = False
                    start = len(demands)
                    for field in _FIELDS:
                        query = block.get(field)
                        if query:
                            decision, _ = lookup(entry, query, field)
                            early, terminal = decision.identifier, decision.terminal
                            if early or terminal:
                                break
                    subject = "kgmicrobe.strain:bacdive_" + entry["record_id"]
                    pairs, nodes = [], []
                    status = "accepted_ordinary" if early else "terminal_rejection" if terminal else "no_parent"
                    if early:
                        pairs.append((subject, early))
                    elif block and not terminal:
                        full = block.get(FULL_SCIENTIFIC_NAME, "unknown")
                        normalized, special = parser._normalize_special_taxon_names(full)
                        if special:
                            status = "unresolved_special"
                            for query in parser._higher_rank_candidates(normalized):
                                decision, _ = lookup(entry, query, GENUS, "special_higher_rank", normalized)
                                if decision.identifier:
                                    pairs.append((subject, decision.identifier))
                                    status = "accepted_special"
                                    break
                                if decision.terminal:
                                    status = "terminal_special_rejection"
                                    break
                        else:
                            genus = parser._genus_for_unmatched_name(full, False)
                            if genus:
                                decision, _ = lookup(entry, genus, GENUS, "parsed_genus")
                                if decision.terminal:
                                    status = "terminal_genus_rejection"
                                elif decision.identifier:
                                    words = full.strip().split()
                                    if len(words) >= 2:
                                        species = words[1]
                                        local = PROVISIONAL_SPECIES_PREFIX + genus + "_" + species
                                        nodes.append(
                                            {"kind": "species", "genus": genus, "species": species, "id": local}
                                        )
                                        pairs.extend(((subject, local), (local, decision.identifier)))
                                    else:
                                        pairs.append((subject, decision.identifier))
                                    status = "accepted_parsed_genus"
                                else:
                                    # Ordinary search has already examined all
                                    # higher fields against the SAME native tier.
                                    # Its complete no-match proof rules out a new
                                    # higher parent; retain the existing orphan
                                    # provisional genus, never invent its identity.
                                    local = PROVISIONAL_GENUS_PREFIX + genus
                                    nodes.append({"kind": "genus", "genus": genus, "id": local})
                                    pairs.append((subject, local))
                                    status = "unresolved_provisional_genus"
                            else:
                                status = "unresolved_unparseable_name"
                    label = None
                    if early:
                        labels = native_facts(early)["labels"]
                        if len(labels) != 1:
                            _fail("inferred parent has no unique native label")
                        label = labels[0]
                    plans[str(ordinal)] = {
                        "native_record": entry,
                        "early_target": early,
                        "inferred": bool(block),
                        "label": label,
                        "status": status,
                        "parent_pairs": pairs,
                        "provisional_nodes": nodes,
                        "lookups": demands[start:],
                    }
                native_contract = owner.finish_fallback()
            else:
                if SELECTED_ROLE in snapshots:
                    _fail("a genuine zero source gained a fallback input role")
                for ordinal, entry in eligible.items():
                    block = entry["classification"] or {}
                    if any(block.get(field) for field in _FIELDS):
                        _fail("visited fallback selector is not nonempty text")
                    if block:
                        # The source reaches this parser only after no ordinary
                        # match. Preserve its actual type handling, rather than
                        # eagerly rejecting an unused full name on a prior hit.
                        parser._normalize_special_taxon_names(block.get(FULL_SCIENTIFIC_NAME, "unknown"))
                    plans[str(ordinal)] = {
                        "native_record": entry,
                        "early_target": None,
                        "inferred": bool(block),
                        "label": None,
                        "status": "unresolved_unparseable_name" if block else "no_source_classification",
                        "parent_pairs": [],
                        "provisional_nodes": [],
                        "lookups": [],
                    }
                native_contract = None
            contract = {
                "version": 1,
                "source_projection_sha256": entry_seal,
                "raw_role": {"name": raw_role, "binding": json.loads(source_role)},
                "eligible_record_count": len(eligible),
                "selected_input": json.loads(self._selected_binding) if self._selected_binding else None,
                "selected_rows": selected_rows,
                "parser_implementation": {"path": str(parser_path), **parser_identity},
                "native_queries": native_contract,
                "plans": plans,
            }
            self._plans = _json(plans)
            self._contract = _json(contract)
            if recorded is not None and self._contract != _json(recorded):
                _fail("recorded fallback evidence differs from complete actual-source reconstruction")
            # A selected record decode is O(one record), not O(all818 plans).
            per_record = {key: _json(value) for key, value in plans.items()}

            def read_plan(ordinal):
                """Keep the record-sized sealed plan cache private to this completed child."""
                value = per_record.get(str(ordinal))
                return json.loads(value) if value is not None else None

            self._read_plan = read_plan
            frozen = (self._plans, self._contract, id(self._owner), id(self._check_original), id(self._read_plan))
            self.admission.capture_resolution(
                lambda: (self._plans, self._contract, id(self._owner), id(self._check_original), id(self._read_plan))
            )
            self._frozen = frozen
            self.admission.capture_resolution(lambda: self._frozen)
            self.verify(snapshots)
        except BaseException:
            self._failed = True
            if self._owner is not None:
                self._owner._poison()
            raise
        finally:
            if self._owner is not None:
                self._owner.close()

    @property
    def selected_roles(self):
        """Return only this child's immutable selected-input role for the shared row audit."""
        selected = json.loads(self._selected_binding) if self._selected_binding else None
        return {SELECTED_ROLE: selected["role"]} if selected and selected["role"] else {}

    def _poison(self):
        """Keep a caught failure incompatible with the original healthy admission state."""
        self._failed = True
        self.admission.capture_resolution(lambda: self._failed)

    @property
    def contract(self):
        """Return detached evidence only after every actual inference record has a plan."""
        if self._failed or self._contract is None:
            _fail("fallback native planning did not complete")
        return json.loads(self._contract)

    def plan(self, ordinal):
        """Expose a detached selected record plan without permitting cached evidence mutation."""
        try:
            self._check_original()
            if (
                self._plans,
                self._contract,
                id(self._owner),
                id(self._check_original),
                id(self._read_plan),
            ) != self._frozen:
                _fail("completed fallback evidence or reader linkage changed")
            return self._read_plan(ordinal)
        except BaseException:
            self._poison()
            raise

    def select_ordinary(self, ordinal, producer_cache):
        """Validate a run-local cache against the independently fixed native decision."""
        try:
            from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform

            plan = self.plan(ordinal)
            if plan is None:
                _fail("supplied-ID source record entered the inference selector")
            if not plan["inferred"]:
                return None, None, False
            block = plan["native_record"]["classification"]
            key = BacDiveTransform._ncbitaxon_fallback_key(block)
            target = plan["early_target"]
            if key in producer_cache and producer_cache[key] != target:
                _fail("producer fallback cache disagrees with native selector evidence")
            producer_cache[key] = target
            return target, plan["label"], plan["inferred"]
        except BaseException:
            self._poison()
            raise

    def verify(self, snapshots):
        """Retain exact source roles, parsed witnesses and owned native authority after completion."""
        try:
            self._check_original()
            if self._frozen != (
                self._plans,
                self._contract,
                id(self._owner),
                id(self._check_original),
                id(self._read_plan),
            ):
                _fail("original completed fallback guard was replaced")
            contract = self.contract
            raw = contract["raw_role"]
            if snapshots.get(raw["name"]) != raw["binding"]:
                _fail("original native source read role changed")
            selected = contract["selected_input"]
            if snapshots.get(SELECTED_ROLE) != (selected["role"] if selected else None):
                _fail("original present/absent selected taxonomy role changed")
            if self._owner is not None:
                self._owner.verify()
            self.admission.verify(metadata_only=True)
        except BaseException:
            self._failed = True
            raise


@contextmanager
def recorded_selected_opener(snapshots, admission, role, path):
    """Re-read only the originally bound transformed authority; never fabricate a consumed role."""
    path = Path(path).absolute()
    identity = admission.capture(path)
    if snapshots.get(role) != {"path": str(path.resolve()), "sha256": identity["sha256"]}:
        _fail("recorded selected taxonomy role is missing or has different bytes")
    with path.open(encoding="utf-8", newline="") as stream:
        yield stream
    admission.verify(metadata_only=True)
