"""Bind named ontology dependency declarations to the finalizer's actual selected files."""

import csv
import json
from pathlib import Path

from kg_microbe.merge_utils.source_admission import SourceAdmission
from kg_microbe.transform_utils.constants import ID_COLUMN, NAME_COLUMN
from kg_microbe.utils.source_finalization import (
    FINALIZATION_FILE,
    SourceFinalizationRequired,
    _ontology_node_files,
    graph_rows,
)


def _json(value):
    """Freeze compact input identities without copying graph-scale node rows."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _fail(message):
    """Reject a changed or unsupported dependency declaration proof."""
    raise SourceFinalizationRequired("Ontology dependency declarations: " + message)


class OntologyDependencyDeclarations:
    """Read the same selected dependency inventory used for finalizer declaration precedence."""

    def __init__(self, directory, *, admission=None, recorded=None, recorded_inputs=None):
        """Bind inventory, lexical selection and actual named membership before it licenses forwarding."""
        self.admission = admission or SourceAdmission()
        self._failed = False
        self.admission.capture_resolution(lambda: self._failed)
        selected_directory = Path(directory).absolute()
        resolved_directory = self.admission.bind_path(selected_directory)
        directory = selected_directory
        if recorded is not None:
            if not isinstance(recorded, dict) or any(
                not isinstance(recorded.get(key), str) or not Path(recorded[key]).is_absolute()
                for key in ("directory_locator", "directory")
            ):
                _fail("recorded dependency directory binding is missing or malformed")
            directory = Path(recorded["directory_locator"])
            recorded_directory = Path(recorded["directory"])
            # Public merge paths may already be canonicalized. Replay the
            # original lexical inventory only if both spellings still select
            # its original target; equal file bytes in another root do not count.
            if resolved_directory != recorded_directory or self.admission.bind_path(directory) != recorded_directory:
                _fail("selected or original dependency directory locator changed")
        receipt = directory / FINALIZATION_FILE
        receipt_identity = self.admission.capture(receipt, optional=True)
        quoting = csv.QUOTE_NONE if receipt_identity is not None else csv.QUOTE_MINIMAL

        def inventory():
            """Retain receipt membership or the supported older-output fallback selection."""
            return tuple(_ontology_node_files(directory))

        members = self.admission.capture_resolution(inventory)
        if any(path.parent != directory for path in members):
            _fail("selected node member is outside the canonical dependency directory")
        paths = (*members, receipt) if receipt_identity is not None else members
        identities = {receipt: receipt_identity}
        declarations, member_contract = set(), {}
        for path in members:
            identity = self.admission.capture(path)
            identities[path] = identity
            for row in graph_rows(path, quoting=quoting):
                if row.get(NAME_COLUMN):
                    declarations.add(row[ID_COLUMN])
            member_contract[path.name] = {
                "locator": str(path),
                "path": str(self.admission.bind_path(path)),
                **identity,
            }
        self._declarations = frozenset(declarations)
        self._input_paths = tuple(paths)
        self._contract = _json(
            {
                "version": 1,
                "directory_locator": str(directory),
                "directory": str(resolved_directory),
                "receipt": {
                    "locator": str(receipt),
                    "path": str(self.admission.bind_path(receipt)),
                    "identity": receipt_identity,
                },
                "members": member_contract,
            }
        )
        # Retain original cache obligations too: removing a verified identity
        # or an absence assertion must not turn a later checkpoint into a no-op.
        obligations = tuple(
            (
                locator,
                self.admission.bind_path(locator),
                _json(identity),
                self.admission.stamps.get(self.admission.bind_path(locator)),
            )
            for locator, identity in identities.items()
        )
        admission = self.admission

        def original_inputs():
            """Keep the original directory, member reads and receipt absence bound after return."""
            if (
                admission.bindings.get(directory) != resolved_directory
                or admission.bindings.get(selected_directory) != resolved_directory
            ):
                _fail("original dependency directory binding was lost")
            for locator, resolved, identity, stamp in obligations:
                if admission.bindings.get(locator) != resolved:
                    _fail("original dependency member locator binding was lost")
                if identity == "null":
                    if resolved not in admission.absent:
                        _fail("original dependency receipt absence guard was lost")
                elif _json(admission.identities.get(resolved)) != identity or admission.stamps.get(resolved) != stamp:
                    _fail("original dependency member read guard was lost")
            return str(directory), str(selected_directory), str(resolved_directory), obligations

        self.admission.capture_resolution(original_inputs)
        self._original_state = self._declarations, self._input_paths, self._contract, id(self.admission)
        self.admission.capture_resolution(
            lambda: (self._declarations, self._input_paths, self._contract, id(self.admission))
        )
        if recorded is not None and self._contract != _json(recorded):
            _fail("recorded inventory differs from the actual selected dependency")
        if recorded is not None and recorded_inputs is None:
            _fail("recorded dependency input identities are missing")
        if recorded_inputs is not None:
            if not isinstance(recorded_inputs, list) or any(
                not isinstance(item, dict) or not {"path", "sha256"} <= item.keys() for item in recorded_inputs
            ):
                _fail("recorded dependency input identities are missing or malformed")
            recorded_hashes = {item["path"]: item["sha256"] for item in recorded_inputs}
            for path in paths:
                if recorded_hashes.get(str(self.admission.bind_path(path))) != identities[path]["sha256"]:
                    _fail("selected dependency member was not recorded as an actual finalizer input")
        # Check the exact native bytes again after the streaming semantic read.
        self.verify(metadata_only=False)

    @property
    def declarations(self):
        """Return the immutable native named-ID set used by generic finalizer precedence."""
        self.verify()
        return self._declarations

    def declarations_for(self, identifiers):
        """Query only selected original retirement IDs without trusting projected graph labels."""
        return self.declarations.intersection(identifiers)

    @property
    def input_paths(self):
        """Return selected dependency members and the receipt that selected them, when present."""
        return self._input_paths

    @property
    def contract(self):
        """Expose detached inventory identities; public verification re-reads actual native rows."""
        self.verify()
        return json.loads(self._contract)

    def verify(self, *, metadata_only=True):
        """Retain the initial selection and read identities through final publication or admission."""
        try:
            if self._failed or self._original_state != (
                self._declarations,
                self._input_paths,
                self._contract,
                id(self.admission),
            ):
                _fail("original dependency declaration state changed")
            self.admission.verify(metadata_only=metadata_only)
        except BaseException:
            self._failed = True
            raise
