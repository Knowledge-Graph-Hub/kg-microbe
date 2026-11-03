"""Reconstruct source-local NCBI declaration guarantees from actual selected-input membership."""

import csv
import hashlib
import json
import re
from pathlib import Path

import yaml

from kg_microbe.transform_utils.constants import (
    BACDIVE_MEDIUM_DICT,
    CULTURE_AND_GROWTH_CONDITIONS,
    CULTURE_LINK,
    CULTURE_MEDIUM,
    CULTURE_NAME,
    GENERAL,
    ID_COLUMN,
    KEYWORDS,
    NAME_COLUMN,
)
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.string_coding import remove_nextlines

SELECTED_ROLE = "bacdive_source_declaration_selected_ncbitaxon"
CUSTOM_ROLE = "bacdive_source_declaration_custom_curies"
METPO_ROLE = "bacdive_source_declaration_metpo_classes"
ALIASES_ROLE = "bacdive_source_declaration_metpo_aliases"


def _json(value):
    """Detach finite source evidence without using mutable generated graph rows as authority."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fail(message):
    """Reject an unproved local declaration rather than relax anonymous-reference safeguards."""
    raise SourceFinalizationRequired("BacDive source declaration evidence: " + message)


def _medium_parent_declared(record):
    """Replay only the native URL/label conditions that make the medium block emit its early parent."""
    conditions = record.get(CULTURE_AND_GROWTH_CONDITIONS) or {}
    media = conditions.get(CULTURE_MEDIUM) or []
    for medium in media if isinstance(media, list) else [media]:
        if not medium.get(CULTURE_LINK):
            continue
        url = str(medium[CULTURE_LINK])
        if url == "None":
            continue
        recognized = any(url.startswith(prefix) for prefix in BACDIVE_MEDIUM_DICT.values())
        if not recognized and "www.dsmz.de/microorganisms/medium/pdf/DSMZ_Medium" in url:
            recognized = re.search(r"DSMZ_Medium(\d+)\.pdf", url) is not None
        if recognized:
            # The producer cannot append a medium if label conversion fails.
            remove_nextlines(medium.get(CULTURE_NAME)).translate({})
            return True
    return False


def _keyword_projection(class_rows, alias_rows):
    """Reconstruct only mapping keys and tree selectors, without predicate/category or chemical work."""
    from kg_microbe.transform_utils.bacdive.bacdive import BacDiveTransform
    from kg_microbe.utils.mapping_file_utils import MetpoTreeNode

    nodes = {}
    for row in class_rows:
        identifier, label = row.get("ID", "").strip(), row.get("label", "").strip()
        if not identifier or not label:
            continue
        synonyms = [item.strip() for item in row.get("madin synonym or field", "").split("|") if item.strip()]
        paths = []
        for item in (item.strip() for item in row.get("bacdive keyword synonym", "").split("|")):
            if item:
                (paths if "." in item else synonyms).append(item)
        nodes[identifier] = MetpoTreeNode(identifier, label, synonyms, "", paths)
    for row in class_rows:
        identifier = row.get("ID", "").strip()
        parent = row.get("parent classes (one strongly preferred)", "").split("|")[0].strip()
        if identifier in nodes and parent:
            match = next((node for node in nodes.values() if node.label == parent), None)
            if match is not None:
                match.add_child(nodes[identifier])
    entries, parents = [], {}
    for row in class_rows:
        identifier = row.get("ID", "").strip()
        synonyms = row.get("bacdive keyword synonym", "").strip()
        if not identifier or not synonyms:
            continue
        parent = nodes[identifier].parent.label if identifier in nodes and nodes[identifier].parent else None
        for synonym in (item.strip() for item in synonyms.split("|")):
            if synonym:
                parents.setdefault(synonym, [])
                if parent:
                    parents[synonym].append(parent)
                entries.append((synonym, parent, {"curie": identifier, "label": row.get("label", "").strip()}))
    mappings = {}
    for synonym, parent, value in entries:
        if len(parents[synonym]) > 1 and parent:
            mappings[f"{parent}.{synonym}"] = value
        mappings[synonym] = value
    for row in alias_rows:
        if (
            (row.get("mapping_justification") or "").strip() != "semapv:ManualMappingCuration"
            or (row.get("confidence") or "").strip().lower() not in {"high", "medium"}
            or (identifier := (row.get("object_id") or "").strip()) not in nodes
        ):
            continue
        for field in ("subject_label_normalized", "subject_label"):
            if key := (row.get(field) or "").strip():
                mappings[key] = {"curie": identifier, "label": (row.get("object_label") or "").strip()}
    parser = BacDiveTransform.__new__(BacDiveTransform)
    parser.bacdive_metpo_mappings = mappings
    parser.bacdive_metpo_tree = nodes
    parser.metpo_iri_to_mapping = parser._build_metpo_iri_index()
    return parser


class SourceDeclarationEvidence:
    """Bind the selected membership used by the producer's mandatory missing-parent stub route."""

    def __init__(
        self,
        targets,
        snapshots,
        *,
        selected_path,
        opener,
        admission,
        entries,
        early_parents,
        raw_role,
        keyword_paths,
        cache_reader=None,
        producer_keyword_matcher=None,
        keyword_cache_reader=None,
        recorded=None,
    ):
        """Read only on native parent demand and preserve both selected presence and absence."""
        self.admission = admission
        self._failed = False
        self.admission.capture_resolution(lambda: self._failed)
        targets = frozenset(targets)
        selected_rows, selected_labels = [], {}
        selected_input = None
        if targets:
            locator = Path(selected_path).absolute()
            resolved = self.admission.bind_path(locator)
            identity = self.admission.capture(locator, optional=True)
            if identity is not None:
                with opener(SELECTED_ROLE, locator) as stream:
                    reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
                    fields = reader.fieldnames
                    if fields is None or len(fields) != len(set(fields)) or not {ID_COLUMN, NAME_COLUMN} <= set(fields):
                        _fail("selected taxonomy header is missing required or unique fields")
                    for ordinal, row in enumerate(reader, 1):
                        if None in row or None in row.values() or any("\x00" in value for value in row.values()):
                            _fail("malformed selected taxonomy row")
                        identifier, name = row[ID_COLUMN], row[NAME_COLUMN]
                        if identifier not in targets or not name:
                            continue
                        selected_rows.append(
                            {"record_ordinal": ordinal, "physical_line_end": reader.line_num, "full_row": row}
                        )
                        selected_labels[identifier] = name
                role = {"path": str(resolved), "sha256": identity["sha256"]}
            else:
                role = None
            if snapshots.get(SELECTED_ROLE) != role:
                _fail("selected membership was not read under its original consumed role")
            selected_input = {"locator": str(locator), "identity": identity, "role": role}
            stamp = self.admission.stamps.get(resolved)

            def original_input():
                """Keep the original read/absence obligation even if a later cache entry is removed."""
                if self.admission.bindings.get(locator) != resolved:
                    _fail("original selected membership locator guard was lost")
                if identity is None:
                    if resolved not in self.admission.absent:
                        _fail("original selected membership absence guard was lost")
                elif (
                    self.admission.identities.get(resolved) != identity or self.admission.stamps.get(resolved) != stamp
                ):
                    _fail("original selected membership read guard was lost")
                return str(locator), str(resolved), _json(identity), stamp

            self.admission.capture_resolution(original_input)
        elif SELECTED_ROLE in snapshots:
            _fail("a genuine zero source gained a source declaration input role")
        if cache_reader is not None:

            def original_cache():
                """Check actual producer membership against native bytes before and after stub emission."""
                cache = cache_reader()
                if not isinstance(cache, dict):
                    _fail("producer selected-label cache is missing")
                selected = {identifier: cache[identifier] for identifier in targets if identifier in cache}
                if selected != selected_labels:
                    _fail("producer selected-label cache differs from actual selected membership")
                return _json(selected)

            # Zero-demand producers may never initialize the preview cache.
            if targets:
                self.admission.capture_resolution(original_cache)
        self._targets = targets
        self._selected_labels = _json(selected_labels)
        self._input_bindings = {}
        keyword_inputs, native_emissions = {}, []
        parser, custom = None, None
        # Only selected early parents need positive medium/keyword proof: an
        # absent-selected demanded target already has the mandatory stub path.
        selected_parents = {ordinal: target for ordinal, target in early_parents.items() if target in selected_labels}
        if selected_parents:
            from kg_microbe.transform_utils.bacdive.ncit_category_claims import _native_records

            raw = snapshots[raw_role]
            with opener(raw_role, Path(raw["path"])) as stream:
                count = 0
                for ordinal, (coordinate, record) in enumerate(_native_records(stream)):
                    count += 1
                    if ordinal >= len(entries) or coordinate != entries[ordinal]["source_coordinate"]:
                        _fail("native source coordinates changed during declaration reconstruction")
                    if hashlib.sha256(_json(record).encode()).hexdigest() != entries[ordinal]["record_sha256"]:
                        _fail("native source record changed during declaration reconstruction")
                    target = selected_parents.get(ordinal)
                    if target is None:
                        continue
                    medium = _medium_parent_declared(record)
                    keywords = record.get(GENERAL, {}).get(KEYWORDS, "")
                    matches = []
                    if keywords:
                        if parser is None:
                            parser, custom, keyword_inputs = self._read_keyword_inputs(keyword_paths, snapshots, opener)
                            if keyword_cache_reader is not None:
                                self.admission.capture_resolution(lambda: _json(keyword_cache_reader()))
                        keys = parser._build_keyword_map_from_record(record, custom)
                        matches = [key for key in keywords if key.lower().replace(" ", "_").replace("-", "_") in keys]
                        if producer_keyword_matcher is not None and matches != producer_keyword_matcher(record):
                            _fail("producer keyword selection differs from actual mapping inputs")
                    if medium or matches:
                        native_emissions.append(
                            {"ordinal": ordinal, "target": target, "medium": medium, "keywords": matches}
                        )
                if count != len(entries):
                    _fail("native source omitted records during declaration reconstruction")
        self._native_emissions = _json(native_emissions)
        self._input_bindings = _json(self._input_bindings)
        self._contract = _json(
            {
                "version": 1,
                "targets": sorted(targets),
                "selected_input": selected_input,
                "selected_rows": selected_rows,
                "keyword_inputs": keyword_inputs,
                "native_emissions": native_emissions,
            }
        )
        original_state = (
            self._targets,
            self._selected_labels,
            self._native_emissions,
            self._input_bindings,
            self._contract,
        )
        self.admission.capture_resolution(
            lambda: (self._targets, self._selected_labels, self._native_emissions, self._input_bindings, self._contract)
        )
        self._original_state = original_state
        if recorded is not None and self._contract != _json(recorded):
            _fail("recorded declaration proof differs from actual native membership reconstruction")
        self.verify(snapshots)

    def _read_keyword_inputs(self, paths, snapshots, opener):
        """Bind only local key authorities used by the existing keyword-trigger parser."""
        inputs, tables = {}, {}
        for role in (CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE):
            locator = Path(paths[role]).absolute()
            identity = self.admission.capture(locator, optional=role == ALIASES_ROLE)
            binding = {"path": str(locator.resolve()), "sha256": identity["sha256"]} if identity else None
            if identity:
                with opener(role, locator) as stream:
                    if role == CUSTOM_ROLE:
                        tables[role] = yaml.safe_load(stream)
                    else:
                        reader = csv.DictReader(stream, delimiter="\t")
                        if role == METPO_ROLE:
                            next(reader)  # ROBOT template directives are not native term rows.
                        tables[role] = list(reader)
            else:
                tables[role] = []
            if snapshots.get(role) != binding:
                _fail("keyword authority was not consumed under its original role")
            self._input_bindings[role] = binding
            inputs[role] = {"locator": str(locator), "identity": identity, "role": binding}
            resolved = locator.resolve()
            stamp = self.admission.stamps.get(resolved)

            def original_keyword_input(locator=locator, resolved=resolved, identity=identity, stamp=stamp):
                """Retain each original mapping obligation even if admission cache membership is erased."""
                if self.admission.bindings.get(locator) != resolved:
                    _fail("original keyword authority locator guard was lost")
                if identity is None:
                    if resolved not in self.admission.absent:
                        _fail("original keyword authority absence guard was lost")
                elif (
                    self.admission.identities.get(resolved) != identity or self.admission.stamps.get(resolved) != stamp
                ):
                    _fail("original keyword authority read guard was lost")
                return str(locator), str(resolved), _json(identity), stamp

            self.admission.capture_resolution(original_keyword_input)
        return _keyword_projection(tables[METPO_ROLE], tables[ALIASES_ROLE]), tables[CUSTOM_ROLE], inputs

    @property
    def guaranteed_stubs(self):
        """Predict typed local rows from native endpoints absent from the selected named declarations."""
        return self._targets - json.loads(self._selected_labels).keys()

    @property
    def proved_declarations(self):
        """Union mandatory stubs with positive native medium/keyword emitters across the source cohort."""
        return self.guaranteed_stubs | {entry["target"] for entry in json.loads(self._native_emissions)}

    @property
    def contract(self):
        """Expose a detached input contract that admission independently reconstructs."""
        return json.loads(self._contract)

    def verify(self, snapshots):
        """Keep source roles, selected bytes and original producer-cache semantics fixed."""
        try:
            if self._failed or self._original_state != (
                self._targets,
                self._selected_labels,
                self._native_emissions,
                self._input_bindings,
                self._contract,
            ):
                _fail("original source declaration state was changed")
            selected = self.contract["selected_input"]
            if snapshots.get(SELECTED_ROLE) != (selected["role"] if selected else None):
                _fail("original selected membership consumed role changed")
            for role in (CUSTOM_ROLE, METPO_ROLE, ALIASES_ROLE):
                if snapshots.get(role) != json.loads(self._input_bindings).get(role):
                    _fail("original keyword authority consumed role changed")
            self.admission.verify(metadata_only=True)
        except BaseException:
            self._failed = True
            raise
