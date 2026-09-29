"""
MediaDive KG.

Example script to transform downloaded data into a graph format that KGX can ingest directly,
in either TSV or JSON format:
https://github.com/NCATS-Tangerine/kgx/blob/master/data-preparation.md

Input: any file in data/raw/ (that was downloaded by placing a URL in incoming.txt/yaml
and running `run.py download`.

Output: transformed data in data/raw/MediaDive:

Output these two files:
- nodes.tsv
- edges.tsv
"""

import csv
import json
import math
import os
import time
from pathlib import Path
from typing import Dict, Optional, Union

import pandas as pd
import requests
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    AGENT_TYPE_COLUMN,
    AMOUNT_COLUMN,
    BACDIVE,
    BACDIVE_ID_COLUMN,
    BACDIVE_PREFIX,
    BACDIVE_TMP_DIR,
    BROAD_MATCH_PREDICATE,
    BROAD_MATCH_RELATION,
    CAS_RN_KEY,
    CAS_RN_PREFIX,
    CATEGORY_COLUMN,
    CHEBI_EDGES_FILE,
    CHEBI_KEY,
    CHEBI_NODES_FILE,
    CHEBI_PREFIX,
    CHEBI_TO_ROLE_EDGE,
    COMPOUND_ID_KEY,
    COMPOUND_KEY,
    DATA_KEY,
    DESCRIPTION_COLUMN,
    DOES_NOT_GROW_IN,
    GRAMS_PER_LITER_COLUMN,
    HAS_PART,
    HAS_ROLE,
    ID_COLUMN,
    INGREDIENT_CATEGORY,
    INGREDIENTS_COLUMN,
    IS_GROWN_IN,
    KEGG_KEY,
    KEGG_PREFIX,
    KNOWLEDGE_LEVEL_COLUMN,
    MANUAL_AGENT,
    MEDIADIVE,
    MEDIADIVE_COMPLEX_MEDIUM_COLUMN,
    MEDIADIVE_DESC_COLUMN,
    MEDIADIVE_ID_COLUMN,
    MEDIADIVE_INGREDIENT_PREFIX,
    MEDIADIVE_LINK_COLUMN,
    MEDIADIVE_MAX_PH_COLUMN,
    MEDIADIVE_MEDIUM_PREFIX,
    MEDIADIVE_MEDIUM_STRAIN_YAML_DIR,
    MEDIADIVE_MEDIUM_TYPE_COMPLEX_ID,
    MEDIADIVE_MEDIUM_TYPE_COMPLEX_LABEL,
    MEDIADIVE_MEDIUM_TYPE_DEFINED_ID,
    MEDIADIVE_MEDIUM_TYPE_DEFINED_LABEL,
    MEDIADIVE_MEDIUM_YAML_DIR,
    MEDIADIVE_MIN_PH_COLUMN,
    MEDIADIVE_REF_COLUMN,
    MEDIADIVE_REST_API_BASE_URL,
    MEDIADIVE_SOLUTION_PREFIX,
    MEDIADIVE_SOURCE_COLUMN,
    MEDIADIVE_TMP_DIR,
    MEDIUM,
    MEDIUM_COMPLEX_CATEGORY,
    MEDIUM_DEFINED_CATEGORY,
    MEDIUM_STRAINS,
    MEDIUM_TO_INGREDIENT_EDGE,
    MEDIUM_TO_SOLUTION_EDGE,
    MEDIUM_TYPE_COMPLEX_CATEGORY,
    MEDIUM_TYPE_DEFINED_CATEGORY,
    MICROMEDIAPARAM_COMPOUND_MAPPINGS_FILE,
    MICROMEDIAPARAM_HYDRATE_MAPPINGS_FILE,
    MMOL_PER_LITER_COLUMN,
    NAME_COLUMN,
    NCBI_CATEGORY,
    NCBI_TO_MEDIUM_EDGE,
    NCBI_TO_MEDIUM_NEGATIVE_EDGE,
    NCBITAXON_ID_COLUMN,
    OBJECT_COLUMN,
    OBSERVATION,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    PUBCHEM_KEY,
    PUBCHEM_PREFIX,
    PUBLICATIONS_COLUMN,
    RAW_DATA_DIR,
    RDFS_SUBCLASS_OF,
    RECIPE_KEY,
    RELATION_COLUMN,
    ROLE_CATEGORY,
    SAME_AS_COLUMN,
    SOLUTION,
    SOLUTION_CATEGORY,
    SOLUTION_ID_KEY,
    SOLUTION_KEY,
    SOLUTIONS_COLUMN,
    SOLUTIONS_KEY,
    SOURCE_ASSERTION_ID_COLUMN,
    SOURCE_RECORD_COLUMN,
    SPECIES,
    STRAIN_PREFIX,
    SUBCLASS_PREDICATE,
    SUBJECT_COLUMN,
    SYNONYM_COLUMN,
    TRANSLATION_TABLE_FOR_LABELS,
    UNIT_COLUMN,
    XREF_COLUMN,
)
from kg_microbe.transform_utils.mediadive.bulk_inputs import (
    BULK_INPUTS,
    MEDIA_LIST_INPUT,
    REQUIRED_BULK_INPUTS,
    snapshot_bulk_input,
    verify_bulk_inputs,
    verify_recorded_bulk_inputs,
)
from kg_microbe.transform_utils.mediadive.material_scope_audit import (
    AUDIT_FILENAME,
    MaterialScopeAudit,
    p3556_material,
    sugar_material,
    verify_recorded_material_inputs,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.chemical_mapping_utils import ChemicalMappingLoader
from kg_microbe.utils.dummy_tqdm import DummyTqdm
from kg_microbe.utils.ingredient_identity import (
    ingredient_authority_label,
    ingredient_hydration_compatible,
    ingredient_mapping_allowed,
)
from kg_microbe.utils.pandas_utils import (
    drop_duplicates,
)
from kg_microbe.utils.provenance import bacdive_record_url
from kg_microbe.utils.source_finalization import SourceFinalizationRequired
from kg_microbe.utils.tsv_io import tsv_writer


class MediaDiveTransform(Transform):
    """Template for how the transform class would be designed."""

    #: Reads ``ontologies/chebi_nodes.tsv`` and ``chebi_edges.tsv`` (roles/categories)
    #: via constants.py (#1035), plus BacDive's intermediate strain-taxid TSV (#1091).
    TRANSFORM_INPUTS = ("ontologies", BACDIVE)
    DEFAULT_INPUT_DIR = RAW_DATA_DIR
    REQUIRED_AUDIT_FILES = (AUDIT_FILENAME,)
    REQUIRED_CONSUMED_INPUTS = ("bacdive_taxon_lookup", *REQUIRED_BULK_INPUTS)

    DATA_INPUTS = ("mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz",)
    OPTIONAL_RAW_CONSUMED_INPUTS = (
        ("micromediaparam_strict", MICROMEDIAPARAM_COMPOUND_MAPPINGS_FILE),
        ("micromediaparam_hydrate", MICROMEDIAPARAM_HYDRATE_MAPPINGS_FILE),
    )

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        """Instantiate part."""
        source_name = MEDIADIVE
        super().__init__(source_name, input_dir, output_dir)
        # Extend edge schema with `value`/`unit` so solution→ingredient edges
        # can carry the recipe's amount + unit (g/l, mmol/l, ml/l, ...).
        # Other edge sites in this transform leave both columns empty.
        self.edge_header = self.edge_header + [
            "value",
            "unit",
            PUBLICATIONS_COLUMN,
            SOURCE_ASSERTION_ID_COLUMN,
            SOURCE_RECORD_COLUMN,
            GRAMS_PER_LITER_COLUMN,
            MMOL_PER_LITER_COLUMN,
        ]
        # No `requests_cache.install_cache()` here: that monkeypatched
        # `requests.Session` for the whole process from a constructor, so every
        # HTTP client in the run became a CachedSession and a test that merely
        # built this transform changed the outcome of unrelated tests (#624).
        # Explicit API helpers own a plain, uncached session. Production reads
        # admitted bulk JSONs only; old HTTP/YAML files are never adopted.
        self._http: Optional[requests.Session] = None
        self.translation_table = str.maketrans(TRANSLATION_TABLE_FOR_LABELS)

        # Load ChEBI role relationships from ontologies transform output (fast TSV lookup).
        # NOTE: This depends on TSV files produced by the ontologies transform being present.
        # Missing or incompatible required tables fail before any graph output is opened.
        self.chebi_roles: Dict[str, list] = {}  # {chebi_id: [role_ids]}
        self.chebi_role_edges: Dict[str, list] = {}  # Original ontology assertion metadata.
        self.chebi_labels: Dict[str, str] = {}  # {chebi_id: label}
        self.chebi_categories: Dict[str, str] = {}  # {chebi_id: category} for category alignment
        self._load_chebi_roles()
        self._load_chebi_categories()

        self.bulk_data_dir = self._resolve_bulk_data_dir(self.input_base_dir)
        self._bulk_input_admission = None
        self._bulk_input_states = {}
        self.media_detailed = {}
        self.media_strains = {}
        self.solutions_data = {}
        self.compounds_data = {}
        self.using_bulk_data = False
        self.api_calls_avoided = 0
        self.api_calls_made = 0

        # Load unified chemical mappings (replaces compound_mappings_strict*.tsv)
        self.chemical_loader = ChemicalMappingLoader()

        # Load MicroMediaParam chemical mappings (kept as legacy fallback during testing)
        self.compound_mappings = {}
        self._load_micromediaparam_mappings()

        # Set knowledge source for MediaDive edges
        self.knowledge_source = "infores:mediadive"  # InforES standard knowledge source

        self._load_bulk_data()

    def consume_bulk_input(self, name, path):
        """Consume a required JSON from the original lexical path and immutable bytes."""
        return snapshot_bulk_input(self, name, path)

    @property
    def producer_native_inputs(self):
        """Serialize original reads, never substitute current files at finalization."""
        return {"version": 1, "inputs": {name: dict(state) for name, state in self._bulk_input_states.items()}}

    @producer_native_inputs.setter
    def producer_native_inputs(self, recorded):
        """Permit exact repeated finalization without replacing the retained read epoch."""
        if recorded != self.producer_native_inputs:
            raise SourceFinalizationRequired("MediaDive bulk reads differ from finalized run; rerun the producer")

    def verify_native_inputs(self, *, byte_verified=False, output_dir=None):
        """Keep the constructor and selected list bound through finalization."""
        verify_bulk_inputs(self, byte_verified=byte_verified, output_dir=output_dir)
        material_audit = getattr(self, "_material_scope_audit", None)
        if material_audit is not None:
            material_audit.guard.verify(metadata_only=byte_verified)

    @classmethod
    def verify_recorded_native_inputs(cls, report, report_path, *, admission=None):
        """Admit the original raw JSON identities with the public source validator."""
        guard = verify_recorded_bulk_inputs(report, report_path, admission=admission)
        verify_recorded_material_inputs(report, report_path)
        return guard

    def _create_node_row(
        self,
        node_id: str,
        category: str,
        name: str,
        description: str = None,
        xref: str = None,
        synonym: str = None,
        same_as: str = None,
    ) -> list:
        """
        Create a properly formatted node row with all columns.

        Automatically populates the provided_by field with self.knowledge_source.

        :param node_id: Node ID (CURIE format)
        :param category: Biolink category
        :param name: Node name/label
        :param description: Optional description
        :param xref: Optional cross-references (pipe-separated string)
        :param synonym: Optional synonyms (pipe-separated string)
        :param same_as: Optional equivalent identifiers (pipe-separated string)
        :return: List representing a complete node row matching node_header
        """
        # Positions follow base Transform.node_header:
        # [id, category, name, description, xref, provided_by, synonym, deprecated, same_as]
        node_row = [None] * len(self.node_header)
        node_row[self.node_header.index(ID_COLUMN)] = node_id
        node_row[self.node_header.index(CATEGORY_COLUMN)] = category
        node_row[self.node_header.index(NAME_COLUMN)] = name
        node_row[self.node_header.index(DESCRIPTION_COLUMN)] = description
        node_row[self.node_header.index(XREF_COLUMN)] = xref
        node_row[self.node_header.index(PROVIDED_BY_COLUMN)] = self.knowledge_source
        node_row[self.node_header.index(SYNONYM_COLUMN)] = synonym
        node_row[self.node_header.index(SAME_AS_COLUMN)] = same_as
        return node_row

    def _load_bulk_data(self):
        """Read all four required bulk dictionaries; never fill gaps from an undated cache."""
        try:
            print(f"Loading bulk MediaDive data from {self.bulk_data_dir}/")
            loaded = {}
            for name, filename in BULK_INPUTS.items():
                with self.consume_bulk_input(name, self.bulk_data_dir / filename) as reader:
                    loaded[name] = json.load(reader)
                    if not isinstance(loaded[name], dict):
                        raise ValueError(f"MediaDive {filename} must contain an object keyed by record ID")
            # Publish only one complete set of dictionaries, all read in this
            # instance's original epoch. A partial/retried read cannot mix epochs.
            self.media_detailed = loaded["mediadive_media_detailed"]
            self.media_strains = loaded["mediadive_media_strains"]
            self.solutions_data = loaded["mediadive_solutions"]
            self.compounds_data = loaded["mediadive_compounds"]
            self.using_bulk_data = True
            print(f"  Loaded {len(self.media_detailed)} detailed media recipes")
            print(f"  Loaded strain associations for {len(self.media_strains)} media")
            print(f"  Loaded {len(self.solutions_data)} solutions")
            print(f"  Loaded {len(self.compounds_data)} compounds")
            print("  Bulk data loaded successfully - YAML/HTTP fallback is disabled")
        except BaseException as error:
            self._consumed_input_error = str(error)
            raise

    def _load_chebi_roles(self):
        """
        Load ChEBI role relationships from ontologies transform output.

        This is much faster than querying the ChEBI SQLite database via OakLib.
        Loads roles and labels from chebi_edges.tsv and chebi_nodes.tsv.
        """
        required_edges = {
            SUBJECT_COLUMN,
            PREDICATE_COLUMN,
            OBJECT_COLUMN,
            RELATION_COLUMN,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
            KNOWLEDGE_LEVEL_COLUMN,
            AGENT_TYPE_COLUMN,
        }
        roles, role_edges, labels, hydrate_names = {}, {}, {}, {}
        seen = set()
        print("Loading ChEBI roles from ontologies transform output...")
        for path, required in (
            (CHEBI_EDGES_FILE, required_edges),
            (CHEBI_NODES_FILE, {ID_COLUMN, NAME_COLUMN}),
        ):
            if not path.is_file():
                raise FileNotFoundError(
                    f"Missing required MediaDive ontology input {path}; run 'poetry run kg transform -s ontologies'"
                )
            with path.open(encoding="utf-8", newline="") as stream:
                # Ontology finalization writes unquoted KGX TSV: quotes inside
                # labels or scalar metadata are data, not CSV escape syntax.
                reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
                if len(reader.fieldnames or ()) != len(set(reader.fieldnames or ())):
                    raise ValueError(f"Invalid MediaDive ontology input {path}: duplicate column names")
                missing = required - set(reader.fieldnames or ())
                if missing:
                    raise ValueError(f"Invalid MediaDive ontology input {path}: missing columns {sorted(missing)}")
                for line, row in enumerate(reader, 2):
                    if None in row or any(row.get(column) is None for column in required):
                        raise ValueError(f"Malformed MediaDive ontology input {path}, row {line}")
                    if path == CHEBI_NODES_FILE:
                        if row[ID_COLUMN].startswith(CHEBI_PREFIX) and row[NAME_COLUMN]:
                            labels[row[ID_COLUMN]] = row[NAME_COLUMN]
                            if "hydrate" in row[NAME_COLUMN].casefold():
                                hydrate_names[row[ID_COLUMN]] = tuple(row.get(SYNONYM_COLUMN, "").split("|"))
                        continue
                    subject, obj = row[SUBJECT_COLUMN], row[OBJECT_COLUMN]
                    if row[RELATION_COLUMN] != HAS_ROLE or not subject.startswith(CHEBI_PREFIX):
                        continue
                    if not obj.startswith(CHEBI_PREFIX) or not all(
                        row[column]
                        for column in (PRIMARY_KNOWLEDGE_SOURCE_COLUMN, KNOWLEDGE_LEVEL_COLUMN, AGENT_TYPE_COLUMN)
                    ):
                        raise ValueError(f"Incomplete ChEBI role assertion in {path}, row {line}")
                    key = tuple(sorted(row.items()))
                    if key not in seen:
                        seen.add(key)
                        role_edges.setdefault(subject, []).append(row)
                    if obj not in roles.setdefault(subject, []):
                        roles[subject].append(obj)
        # Publish the in-memory index only after both tables validate successfully.
        self.chebi_roles, self.chebi_role_edges, self.chebi_labels = roles, role_edges, labels
        self.chebi_hydrate_names = hydrate_names
        print(f"  Loaded {len(roles)} ChEBI compounds with roles")
        print(f"  Loaded {len(labels)} ChEBI labels")

    def _generate_chebi_role_edges(self, chebi_ids):
        """Project source ontology assertions to the actual output header without inventing observations."""
        edges = []
        for chebi_id in dict.fromkeys(chebi_ids):
            for assertion in self.chebi_role_edges.get(chebi_id, ()):
                fields = {**assertion, PREDICATE_COLUMN: CHEBI_TO_ROLE_EDGE, RELATION_COLUMN: HAS_ROLE}
                edges.append([fields.get(column, "") for column in self.edge_header])
        return edges

    def _load_chebi_categories(self):
        """
        Load CHEBI categories from ontologies transform output.

        This ensures MediaDive uses the same categories assigned by the ontologies transform,
        preventing multi-category conflicts during merge (e.g., ChemicalEntity|SmallMolecule).
        Falls back to INGREDIENT_CATEGORY if CHEBI ID not found in ontologies.
        """
        chebi_nodes_file = CHEBI_NODES_FILE

        if chebi_nodes_file.exists():
            try:
                print("Loading CHEBI categories from ontologies transform output...")
                with open(chebi_nodes_file) as f:
                    f.readline()  # skip header
                    for line in f:
                        parts = line.strip().split("\t")
                        if len(parts) >= 2:
                            # KGX nodes.tsv columns: [0]=id, [1]=category, [2]=name, ...
                            node_id = parts[0]
                            category = parts[1]
                            if node_id.startswith("CHEBI:") and category:
                                self.chebi_categories[node_id] = category
                print(f"  Loaded {len(self.chebi_categories)} CHEBI categories")
            except Exception as e:
                print(f"Warning: Could not load CHEBI categories: {e}")
        else:
            print(f"Warning: CHEBI nodes file not found at {chebi_nodes_file}")
            print("  Will fall back to INGREDIENT_CATEGORY (biolink:ChemicalEntity)")

    def _get_chebi_category(self, chebi_id: str) -> str:
        """
        Get the category for a CHEBI ID from preloaded categories.

        Args:
            chebi_id: CHEBI CURIE (e.g., "CHEBI:16828")

        Returns:
            The Biolink category for the CHEBI ID (e.g., "biolink:SmallMolecule"),
            or INGREDIENT_CATEGORY (biolink:ChemicalEntity) if not found

        """
        return self.chebi_categories.get(chebi_id, INGREDIENT_CATEGORY)

    def _load_mapping_file(
        self, mapping_file: Path, description: str, *, consumed_role=None, reader=None
    ) -> Dict[str, str]:
        """
        Load a single MicroMediaParam mapping file and return filtered mappings.

        Args:
        ----
            mapping_file: Path to the TSV mapping file.
            description: Human-readable description for logging.
            consumed_role: Optional declared role used by production callers to capture an immutable read.
            reader: Already captured parser handle, used internally without reopening the source path.

        Returns:
        -------
            Dictionary mapping normalized compound names to ontology IDs.

        """
        if consumed_role is not None:
            with self.consume_optional_input(consumed_role) as snapshot:
                if snapshot is None:
                    print(f"  {description} not found at {mapping_file}")
                    return {}
                return self._load_mapping_file(mapping_file, description, reader=snapshot)

        from kg_microbe.transform_utils.constants import HAS_PART_PREDICATE
        from kg_microbe.utils.ingredient_identity import _hydration_scope

        try:
            if reader is None and not mapping_file.exists():
                print(f"  {description} not found at {mapping_file}")
                return {}

            print(f"  Loading {description} from {mapping_file}")
            # Preserve identifiers and blank optional fields without NaN coercion.
            df = pd.read_csv(reader if reader is not None else mapping_file, sep="\t", dtype=str, keep_default_na=False)
            if not {"original", "mapped"}.issubset(df.columns):
                print(f"  Warning: Could not load {description}: missing original/mapped columns")
                return {}
        except pd.errors.ParserError as e:
            print(f"  Warning: Could not parse {description}: {e}")
            return {}
        except pd.errors.EmptyDataError:
            print(f"  Warning: {description} file is empty")
            return {}

        # The hydrate file supplies a *different* identity, not permission to
        # strip water. Confirm its relationship to that row's supplied base
        # independently in native ChEBI before considering the supplied ID.
        # Infrastructure failures must abort, outside the optional TSV parser.
        has_hydrates = "hydrated_chebi_id" in df and df["hydrated_chebi_id"].str.strip().ne("").any()
        if has_hydrates and not hasattr(self, "_native_hydrate_parts"):
            parts = set()
            required = {
                SUBJECT_COLUMN,
                PREDICATE_COLUMN,
                OBJECT_COLUMN,
                RELATION_COLUMN,
                PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
            }
            with CHEBI_EDGES_FILE.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
                if len(reader.fieldnames or ()) != len(set(reader.fieldnames or ())) or not required.issubset(
                    reader.fieldnames or ()
                ):
                    raise ValueError(f"Invalid MediaDive native hydrate evidence header: {CHEBI_EDGES_FILE}")
                for line, row in enumerate(reader, 2):
                    if None in row or any(row.get(column) is None for column in required):
                        raise ValueError(f"Malformed MediaDive native hydrate evidence: {CHEBI_EDGES_FILE}, row {line}")
                    if (
                        row[PREDICATE_COLUMN] == HAS_PART_PREDICATE
                        and row[RELATION_COLUMN] == HAS_PART
                        and row[PRIMARY_KNOWLEDGE_SOURCE_COLUMN] == "infores:chebi"
                    ):
                        parts.add((row[SUBJECT_COLUMN], row[OBJECT_COLUMN]))
            self._native_hydrate_parts = frozenset(parts)

        unwanted_prefixes = (
            "ingredient:",
            "solution:",
            "medium:",
            MEDIADIVE_INGREDIENT_PREFIX,
            MEDIADIVE_SOLUTION_PREFIX,
            MEDIADIVE_MEDIUM_PREFIX,
        )
        mappings = {}
        declared = getattr(self, "_supplied_hydrate_names", set())
        held = getattr(self, "_held_hydrate_names", set())
        claims = getattr(self, "_legacy_identity_claims", {})
        for row in df.to_dict("records"):
            name, base = row["original"].strip(), row["mapped"].strip()
            if not name or not base or base.startswith(unwanted_prefixes):
                continue
            key = name.lower()
            candidates = set()
            if self._ingredient_identity_allowed(name, base):
                candidates.add(base)
            hydrated = row.get("hydrated_chebi_id", "").strip()
            if hydrated:
                declared.add(key)
                label = getattr(self, "chebi_labels", {}).get(hydrated, "")
                native_names = (label, *getattr(self, "chebi_hydrate_names", {}).get(hydrated, ()))
                supplied_label = row.get("hydrated_chebi_label", "").strip()
                scope = _hydration_scope(name)
                supplied_count = row.get("hydration_number", "").strip()
                try:
                    count_agrees = not supplied_count or float(supplied_count) == scope
                except ValueError:
                    count_agrees = False
                valid_id = (
                    hydrated.startswith(CHEBI_PREFIX)
                    and hydrated[len(CHEBI_PREFIX) :].isascii()
                    and hydrated[len(CHEBI_PREFIX) :].isdigit()
                )
                valid_label = bool(label and supplied_label) and supplied_label.casefold() in {
                    value.strip().casefold() for value in native_names if value
                }
                same_declared_target = hydrated == base and base in candidates
                independently_linked = (
                    (hydrated, base) in self._native_hydrate_parts and isinstance(scope, (int, float)) and scope > 0
                )
                if (
                    valid_id
                    and valid_label
                    and count_agrees
                    and (same_declared_target or independently_linked)
                    and self._ingredient_identity_allowed(name, hydrated)
                ):
                    candidates.add(hydrated)
                else:
                    held.add(key)
            claims.setdefault(key, set()).update(candidates)
            if candidates:
                # Non-hydrate legacy rows retain first-admitted-row priority.
                mappings.setdefault(key, base if base in candidates else next(iter(candidates)))

        # Reject contradictory supplied identities, also across the priority
        # files. A later strict row cannot restore a held hydrate alias or leave
        # an already-installed conflicting legacy result behind.
        held.update(key for key in declared if len(claims.get(key, ())) > 1)
        for key in held:
            mappings.pop(key, None)
            getattr(self, "compound_mappings", {}).pop(key, None)
        self._supplied_hydrate_names = declared
        self._held_hydrate_names = held
        self._legacy_identity_claims = claims
        print(f"    Loaded {len(mappings)} mappings from {description}")

        return mappings

    def _load_micromediaparam_mappings(self):
        """
        Load MicroMediaParam compound mappings for chemical name to ontology ID mapping.

        Loads mappings in priority order:
        1. Hydrate mappings (highest priority) - admits supplied hydrate IDs with native evidence
        2. Strict mappings (fallback) - standard compound name to ontology ID mappings

        Maps compound names to standardized IDs (ChEBI, CAS-RN, PubChem, etc.)
        to reduce use of custom ingredient: and solution: prefixes.
        See download.yaml for file format details.
        """
        print("Loading MicroMediaParam compound mappings...")

        # Step 1: Load hydrate mappings first (these take precedence)
        # Supplied hydrate IDs require native scope and hydrate-to-base part evidence.
        hydrate_file = Path(self.input_base_dir) / MICROMEDIAPARAM_HYDRATE_MAPPINGS_FILE
        hydrate_mappings = self._load_mapping_file(
            hydrate_file, "hydrate mappings", consumed_role="micromediaparam_hydrate"
        )
        self.compound_mappings.update(hydrate_mappings)

        # Step 2: Load strict mappings for compounds not in hydrate mappings
        strict_file = Path(self.input_base_dir) / MICROMEDIAPARAM_COMPOUND_MAPPINGS_FILE
        strict_mappings = self._load_mapping_file(
            strict_file, "strict mappings", consumed_role="micromediaparam_strict"
        )

        # Only add strict mappings for compounds NOT already in hydrate mappings
        new_from_strict = 0
        for key, value in strict_mappings.items():
            if key not in self.compound_mappings:
                self.compound_mappings[key] = value
                new_from_strict += 1

        print(f"  Total compound mappings: {len(self.compound_mappings)}")
        print(f"    From hydrate mappings: {len(hydrate_mappings)} (precedence)")
        print(f"    From strict mappings: {new_from_strict} (fallback)")

        if not self.compound_mappings:
            print("  Warning: No MicroMediaParam mappings loaded, will use MediaDive API mappings only")

    def _get_mediadive_json(self, url: str, retry_count: int = 3, retry_delay: float = 2.0) -> Dict:
        """
        Fetch live API data through an owned uncached session, never old cache files.

        :param url: Path provided by MediaDive API.
        :param retry_count: Number of retry attempts on failure.
        :param retry_delay: Delay in seconds between retries.
        :return: JSON response as a Dict.
        """
        for attempt in range(retry_count):
            try:
                r = self._http_session().get(url, timeout=30)
                r.raise_for_status()
                data_json = r.json()
                return data_json.get(DATA_KEY, {})
            except requests.exceptions.RequestException as e:
                self._close_http()
                if attempt < retry_count - 1:
                    print(f"  Retry {attempt + 1}/{retry_count} after error: {e} (URL: {url})")
                    time.sleep(retry_delay)
                else:
                    print(f"  Failed after {retry_count} attempts: {e} (URL: {url})")
                    return {}
            except BaseException:
                self._close_http()
                raise

    def _http_session(self) -> requests.Session:
        """Return this transform's uncached HTTP session, opening it on first explicit use."""
        if self._http is None:
            self._http = requests.Session()
        return self._http

    def _close_http(self) -> None:
        """Close this transform's owned session without touching any persistent cache."""
        # getattr: tests build the transform with __new__ and no __init__.
        session = getattr(self, "_http", None)
        if session is not None:
            try:
                session.close()
            finally:
                self._http = None

    def _get_chebi_label(self, curie: str) -> str:
        """
        Look up the label for a CURIE from preloaded ChEBI labels.

        Only supports CURIEs with the CHEBI prefix. For other prefixes,
        returns an empty string.

        Args:
        ----
            curie: CURIE identifier (e.g., "CHEBI:12345").

        Returns:
        -------
            The label for the CHEBI CURIE if found, otherwise an empty string.

        """
        if ":" not in curie:
            return ""
        prefix = curie.split(":", 1)[0]
        if prefix.startswith(CHEBI_KEY):
            return self.chebi_labels.get(curie, "")
        return ""

    def get_compounds_of_solution(self, id: str):
        """
        Return the historical unique-display-name view, refusing lossy collisions.

        Production emission uses ``get_solution_recipe_occurrences`` instead.
        This compatibility view is safe only when every display name is unique.

        :param id: ID of solution.
        :return: Dictionary of display names to resolved identities and quantities.
        :raises ValueError: Two recipe occurrences have the same display name.
        """
        ingredients = {}
        for occurrence in self.get_solution_recipe_occurrences(id):
            name = occurrence[NAME_COLUMN]
            if name in ingredients:
                raise ValueError(
                    f"Solution {id} has duplicate recipe display name {name!r}; "
                    "use get_solution_recipe_occurrences() to preserve every occurrence"
                )
            ingredients[name] = {
                column: occurrence[column]
                for column in (ID_COLUMN, AMOUNT_COLUMN, UNIT_COLUMN, GRAMS_PER_LITER_COLUMN, MMOL_PER_LITER_COLUMN)
            }
        return ingredients

    def get_solution_recipe_occurrences(self, id: str):
        """
        Resolve every recipe occurrence in source-list order without name deduplication.

        Assertion IDs use the owning solution and one-based raw list position,
        not the optional/nonunique source recipe_order. The exact source item is
        retained as canonical JSON evidence, including original name, source ID,
        source order, optional flag and all supplied quantity fields.

        :param id: ID of solution.
        :return: Ordered occurrence dictionaries with resolved IDs and source evidence.
        """
        # Check bulk downloaded data first
        if self.using_bulk_data:
            if id not in self.solutions_data:
                raise FileNotFoundError(
                    f"Missing MediaDive bulk solution {id!r} in {self.bulk_data_dir / 'solutions.json'}. "
                    "Refresh the bulk download; refusing YAML/HTTP fallback in bulk mode."
                )
            self.api_calls_avoided += 1
            data = self.solutions_data[id]
        else:
            self.api_calls_made += 1
            url = MEDIADIVE_REST_API_BASE_URL + SOLUTION + id
            data = self._get_mediadive_json(url)

        occurrences = []
        if RECIPE_KEY not in data or not isinstance(data[RECIPE_KEY], list):
            return occurrences
        for position, item in enumerate(data[RECIPE_KEY], 1):
            if COMPOUND_ID_KEY in item and item[COMPOUND_ID_KEY] is not None:
                # Display cleanup must not erase chemical formula/scope before
                # lookup, or mutate the cached source for later calls (#1167).
                source_name = item[COMPOUND_KEY]
                display_name = (
                    item[COMPOUND_KEY].translate(self.translation_table).replace('""', "").strip()
                    if isinstance(item[COMPOUND_KEY], str)
                    else item[COMPOUND_KEY]
                )
                ingredient_id = self.standardize_compound_id(
                    str(item[COMPOUND_ID_KEY]), source_name, source_record=item
                )
            elif SOLUTION_ID_KEY in item and item[SOLUTION_ID_KEY] is not None:
                # Resolve the original scope; normalize only the display key.
                if isinstance(item[SOLUTION_KEY], str):
                    source_name = item[SOLUTION_KEY]
                    solution_name = source_name.translate(self.translation_table).replace('""', "").strip()
                elif item[SOLUTION_KEY] is not None:
                    source_name = solution_name = str(item[SOLUTION_KEY])
                else:
                    source_name = solution_name = ""

                solution_name_normalized = source_name.lower().strip()

                # Check if solution name can be mapped to ontology via unified or legacy mappings
                candidates = (
                    []
                    if p3556_material(item) or sugar_material(item)
                    else [
                        self.chemical_loader.find_chebi_by_name(source_name),
                        self.compound_mappings.get(solution_name_normalized),
                    ]
                )
                solution_id = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate and self._ingredient_identity_allowed(source_name, candidate)
                    ),
                    MEDIADIVE_SOLUTION_PREFIX + str(item[SOLUTION_ID_KEY]),
                )

                display_name = solution_name
                ingredient_id = solution_id
            else:
                continue
            occurrences.append(
                {
                    NAME_COLUMN: display_name,
                    ID_COLUMN: ingredient_id,
                    AMOUNT_COLUMN: item.get(AMOUNT_COLUMN),
                    UNIT_COLUMN: item.get(UNIT_COLUMN),
                    GRAMS_PER_LITER_COLUMN: item.get(GRAMS_PER_LITER_COLUMN),
                    MMOL_PER_LITER_COLUMN: item.get(MMOL_PER_LITER_COLUMN),
                    SOURCE_ASSERTION_ID_COLUMN: f"{MEDIADIVE_SOLUTION_PREFIX}{id}#recipe/{position}",
                    SOURCE_RECORD_COLUMN: json.dumps(
                        item, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
                    ),
                }
            )
            material_audit = getattr(self, "_material_scope_audit", None)
            if material_audit is not None:
                material_audit.observe(occurrences[-1], item)
        return occurrences

    def _ingredient_identity_allowed(self, name: str, target: str) -> bool:
        """Check every fallback against explicit hydration scope and curated identity policy."""
        if not ingredient_mapping_allowed(name, target):
            return False
        # Prefer native ChEBI names over possibly stale source-derived labels.
        label = getattr(self, "chebi_labels", {}).get(target, "") or ingredient_authority_label(target)
        if not label:
            getter = getattr(getattr(self, "chemical_loader", None), "get_canonical_name", None)
            label = getter(target) if getter else ""
        return ingredient_hydration_compatible(name, label, getattr(self, "chebi_hydrate_names", {}).get(target, ()))

    def standardize_compound_id(self, id: str, compound_name: str = None, *, source_record: dict = None):
        """
        Get standardized IDs via unified chemical mappings, bulk data, or legacy mappings.

        Lookup order:
        1. Unified chemical mappings by compound name (ChemicalMappingLoader)
        2. Legacy MicroMediaParam mappings by compound name (fallback during transition)
        3. Bulk downloaded data (embedded ChEBI/KEGG/PubChem/CAS-RN)
        4. Custom ingredient prefix (last resort)

        :param id: MediaDive compound ID.
        :param compound_name: Compound name for mapping lookup.
        :param source_record: Actual occurrence evidence; even an empty dictionary overrides embedded qualifiers.
        :return: Standardized ID.
        """
        # A whole supplier product is not a pure molecular species. The actual
        # occurrence wins over another recipe's cached embedded record (#1241).
        evidence = source_record if source_record is not None else getattr(self, "compounds_data", {}).get(id, {})
        if p3556_material(evidence) or sugar_material(evidence, compound_name):
            return MEDIADIVE_INGREDIENT_PREFIX + id
        if compound_name:
            # Check unified chemical mappings by compound name. The unified
            # mapping is not restricted to CHEBI — it also holds FOODON
            # foods, UBERON anatomy, and ENVO environments for ingredients
            # like "Yeast extract", "Defibrinated sheep blood", "Natural
            # seawater". A missing hydrate identity stays local; recipe-level
            # interchangeability cannot substitute the anhydrous chemical.
            mapped_id = self.chemical_loader.find_chebi_by_name(compound_name)
            if mapped_id and self._ingredient_identity_allowed(compound_name, mapped_id):
                return mapped_id

            # Fallback: check legacy MicroMediaParam mappings by compound name
            normalized_name = compound_name.lower().strip()
            mapped_id = self.compound_mappings.get(normalized_name)
            if mapped_id and self._ingredient_identity_allowed(compound_name, mapped_id):
                return mapped_id

        # Check bulk downloaded data for embedded compound mappings
        # Note: MediaDive compound API endpoint does not exist (returns 400 "not supported")
        # Compound mappings are extracted from embedded recipe data in media_detailed.json
        # No API call path - endpoint doesn't exist, so we always use embedded data or fallback

        if id in self.compounds_data:
            # Only count as avoided API call when data is actually found in bulk data
            if self.using_bulk_data:
                self.api_calls_avoided += 1
            data = self.compounds_data[id]
            # Every embedded namespace must pass the same identity contract;
            # a rejected ChEBI entry cannot escape through PubChem/CAS (#1155).
            name = compound_name or data.get(COMPOUND_KEY) or data.get("name", "")
            for key, prefix in (
                (CHEBI_KEY, CHEBI_PREFIX),
                (KEGG_KEY, KEGG_PREFIX),
                (PUBCHEM_KEY, PUBCHEM_PREFIX),
                (CAS_RN_KEY, CAS_RN_PREFIX),
            ):
                if data.get(key) is not None:
                    mapped_id = prefix + str(data[key])
                    if self._ingredient_identity_allowed(name, mapped_id):
                        return mapped_id

        # Fall back to custom ingredient prefix
        return MEDIADIVE_INGREDIENT_PREFIX + id

    def _classify_ingredient_category(self, ingredient_id: str, ingredient_name: str) -> str:
        """
        Classify ingredient category based on ID mapping and name patterns.

        Ingredients mapped to ontologies (ChEBI, KEGG, PubChem, CAS-RN) are categorized
        as simple ChemicalEntity. Unmapped ingredients are checked against a pattern list
        to identify complex ingredients (peptone, yeast extract, etc.) which are categorized
        as ComplexMolecularMixture.

        Args:
        ----
            ingredient_id: Standardized ingredient ID (ChEBI:, KEGG:, mediadive.ingredient:, etc.)
            ingredient_name: Human-readable ingredient name

        Returns:
        -------
            Biolink category (ChemicalEntity or ComplexMolecularMixture)

        """
        from kg_microbe.transform_utils.constants import COMPLEX_INGREDIENT_CATEGORY

        # If mapped to ontology, derive the category from the unified
        # mapping's `category` data column — no prefix routing in code.
        if not ingredient_id.startswith(MEDIADIVE_INGREDIENT_PREFIX):
            # CHEBI keeps a dedicated path to stay in sync with the
            # ontologies transform (multi-category reconciliation).
            if ingredient_id.startswith("CHEBI:"):
                return self._get_chebi_category(ingredient_id)
            # Any other ontology CURIE: read category from the unified file.
            category = self.chemical_loader.get_category(ingredient_id)
            if category:
                return category
            # Non-ontology IDs (KEGG, PubChem, CAS-RN): generic chemical.
            return INGREDIENT_CATEGORY

        # Check name patterns for complex ingredients
        ingredient_name_lower = ingredient_name.lower()

        # Patterns indicating complex biological mixtures
        complex_patterns = [
            "peptone",
            "yeast extract",
            "meat extract",
            "beef extract",
            "casein",
            "casitone",
            "tryptone",
            "soytone",
            "proteose peptone",
            "trypticase",
            "nutrient broth",
            "agar",
            "gelatin",
            "blood",
            "serum",
            "brain heart infusion",
            "malt extract",
            "soy",
            "corn steep",
            "peptide",
            "hydrolysate",
            "infusion",
        ]

        for pattern in complex_patterns:
            if pattern in ingredient_name_lower:
                return COMPLEX_INGREDIENT_CATEGORY

        # Default to simple ChemicalEntity
        return INGREDIENT_CATEGORY

    def download_yaml_and_get_json(
        self,
        url: str,
        target_dir: Path,
    ) -> Dict[str, str]:
        """
        Fetch live MediaDive data; retain the legacy signature without YAML persistence.

        :param url: Path provided by MediaDive API.
        :param target_dir: Ignored legacy cache destination; never read, created or written.
        """
        return self._get_mediadive_json(url)

    def get_json_object(self, fn: Union[Path, str], url_extension: str, target_dir: Path) -> Dict[str, str]:
        """
        Read admitted bulk data, or fetch live data for an explicit nonbulk lookup.

        Bulk mode never falls back to YAML or HTTP for a missing record.
        Nonbulk helper calls are uncached diagnostics, not a production transform mode.

        :param fn: Ignored legacy YAML file path.
        :param url_extension: API endpoint extension (e.g., "medium/123").
        :param target_dir: Ignored legacy YAML directory.
        :return: Dictionary.
        """
        # Extract ID from url_extension (e.g., "medium/123" -> "123")
        medium_id = url_extension.split("/")[-1]

        # Check bulk downloaded data first
        if self.using_bulk_data:
            if url_extension.startswith(MEDIUM_STRAINS):
                if medium_id in self.media_strains:
                    self.api_calls_avoided += 1
                    return self.media_strains[medium_id]
                else:
                    # Medium has no strain associations in bulk data (empty response during download)
                    # Return empty list instead of falling back to API
                    self.api_calls_avoided += 1
                    return []
            elif url_extension.startswith(MEDIUM):
                if medium_id in self.media_detailed:
                    self.api_calls_avoided += 1
                    # Return bulk-downloaded detailed data directly
                    # Structure from media_detailed.json:
                    #   {
                    #     "medium": {...},
                    #     "solutions": [
                    #       {"id": 1, "name": "...", "recipe": [...], "steps": [...]},
                    #       ...
                    #     ]
                    #   }
                    # Note: SOLUTIONS_KEY ("solutions") is at the top level, not RECIPE_KEY.
                    # The "recipe" key is nested within each solution object.
                    return self.media_detailed[medium_id]
                raise FileNotFoundError(
                    f"Missing MediaDive bulk medium {medium_id!r} in {self.bulk_data_dir / 'media_detailed.json'}. "
                    "Refresh the bulk download; refusing YAML/HTTP fallback in bulk mode."
                )
            raise ValueError(f"Unsupported MediaDive bulk lookup: {url_extension!r}")

        self.api_calls_made += 1
        url = MEDIADIVE_REST_API_BASE_URL + url_extension
        return self.download_yaml_and_get_json(url, target_dir)

    @classmethod
    def _resolve_bulk_data_dir(cls, input_base_dir) -> Path:
        """Resolve bulk JSONs beneath the same selected raw root as the list and mappings."""
        return Path(input_base_dir) / "mediadive"

    def _assert_bulk_data_available(self) -> None:
        """
        Refuse to transform when the bulk MediaDive download is missing.

        Historical cache-only runs could silently reuse superseded recipes.
        Production now requires the admitted bulk JSON evidence; neither old
        caches nor explicit uncached diagnostic helpers can replace it.
        The former stale-cache override is no longer admitted.
        """
        if self.using_bulk_data:
            return
        raise FileNotFoundError(
            f"MediaDive bulk data not found in {self.bulk_data_dir}/. Refusing to transform: "
            "YAML caches and live diagnostic helpers cannot replace required bulk evidence. "
            "Run `poetry run kg download -t mediadive` and let it finish "
            "first. KG_MEDIADIVE_ALLOW_STALE_CACHE cannot bypass required source evidence."
        )

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run the transformation, closing the API session afterwards."""
        try:
            self._run(data_file, show_status)
        except BaseException as error:
            self._consumed_input_error = str(error)
            raise
        finally:
            self._close_http()

    def _preflight_bulk_records(self, input_json):
        """Check every requested medium and expanded solution before opening graph outputs."""
        if not isinstance(input_json, dict) or not isinstance(input_json.get(DATA_KEY), list):
            raise ValueError("MediaDive media list must contain a 'data' list")
        for record in input_json[DATA_KEY]:
            if not isinstance(record, dict) or ID_COLUMN not in record:
                raise ValueError("MediaDive media list contains a record without an ID")
            medium_id = str(record[ID_COLUMN])
            if medium_id not in self.media_detailed:
                raise FileNotFoundError(
                    f"Missing MediaDive bulk medium {medium_id!r} in {self.bulk_data_dir / 'media_detailed.json'}. "
                    "Refresh the bulk download; refusing YAML/HTTP fallback in bulk mode."
                )
            detail = self.media_detailed[medium_id]
            if not isinstance(detail, dict):
                raise ValueError(f"MediaDive bulk medium {medium_id!r} must be an object")
            # Present metadata-only entries are valid, unlike absent records.
            solutions = detail.get(SOLUTIONS_KEY, [])
            if not isinstance(solutions, list):
                raise ValueError(f"MediaDive bulk medium {medium_id!r} solutions must be a list")
            for solution in solutions:
                if not isinstance(solution, dict) or ID_COLUMN not in solution:
                    raise ValueError(f"MediaDive bulk medium {medium_id!r} has a solution without an ID")
                solution_id = str(solution[ID_COLUMN])
                if solution_id not in self.solutions_data:
                    raise FileNotFoundError(
                        f"Missing MediaDive bulk solution {solution_id!r} requested by medium {medium_id!r} "
                        f"in {self.bulk_data_dir / 'solutions.json'}. Refresh the bulk download."
                    )
                if not isinstance(self.solutions_data[solution_id], dict):
                    raise ValueError(f"MediaDive bulk solution {solution_id!r} must be an object")

    def _run(self, data_file: Union[Optional[Path], Optional[str]] = None, show_status: bool = True):
        """Run the transformation."""
        # Constructor-loaded mappings belong to this instance's original input
        # epoch. Repeated runs may reuse it only unchanged; a new epoch requires
        # a new instance, never resetting evidence underneath cached mappings.
        self._assert_bulk_data_available()
        input_file = Path(data_file) if data_file is not None else Path("mediadive.json")
        if not input_file.is_absolute():
            input_file = self.input_base_dir / input_file
        with self.consume_bulk_input(MEDIA_LIST_INPUT, input_file) as reader:
            input_json = json.load(reader)
        bacdive_input_file = BACDIVE_TMP_DIR / "bacdive.tsv"
        with self.consume_input("bacdive_taxon_lookup", bacdive_input_file) as bacdive_file:
            bacdive_df = pd.read_csv(bacdive_file, sep="\t", usecols=[BACDIVE_ID_COLUMN, NCBITAXON_ID_COLUMN])
        self.verify_consumed_inputs()
        self._preflight_bulk_records(input_json)
        self._material_scope_audit = MaterialScopeAudit(self, input_json)

        # Create dictionary lookup for O(1) access instead of O(n) DataFrame filtering
        bacdive_strain_to_ncbi = dict(zip(bacdive_df[BACDIVE_ID_COLUMN], bacdive_df[NCBITAXON_ID_COLUMN], strict=True))

        COLUMN_NAMES = [
            MEDIADIVE_ID_COLUMN,
            NAME_COLUMN,
            MEDIADIVE_COMPLEX_MEDIUM_COLUMN,
            MEDIADIVE_SOURCE_COLUMN,
            MEDIADIVE_LINK_COLUMN,
            MEDIADIVE_MIN_PH_COLUMN,
            MEDIADIVE_MAX_PH_COLUMN,
            MEDIADIVE_REF_COLUMN,
            MEDIADIVE_DESC_COLUMN,
            SOLUTIONS_COLUMN,
            INGREDIENTS_COLUMN,
        ]

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        with (
            open(str(MEDIADIVE_TMP_DIR / "mediadive.tsv"), "w") as tsvfile,
            open(self.output_node_file, "w") as node,
            open(self.output_edge_file, "w") as edge,
        ):
            writer = tsv_writer(tsvfile)
            # Write the column names to the output file
            writer.writerow(COLUMN_NAMES)

            node_writer = tsv_writer(node)
            node_writer.writerow(self.node_header)
            edge_writer = tsv_writer(edge)
            edge_writer.writerow(self.edge_header)

            # Choose the appropriate context manager based on the flag
            progress_class = tqdm if show_status else DummyTqdm
            with progress_class(total=len(input_json[DATA_KEY]) + 1, desc="Processing files") as progress:
                # medium type nodes — defined media have known composition
                # (biolink:ChemicalMixture), complex media have undefined
                # composition like yeast extract / peptone
                # (biolink:ComplexMolecularMixture).
                node_writer.writerows(
                    [
                        self._create_node_row(
                            MEDIADIVE_MEDIUM_TYPE_COMPLEX_ID,
                            MEDIUM_TYPE_COMPLEX_CATEGORY,
                            MEDIADIVE_MEDIUM_TYPE_COMPLEX_LABEL,
                        ),
                        self._create_node_row(
                            MEDIADIVE_MEDIUM_TYPE_DEFINED_ID,
                            MEDIUM_TYPE_DEFINED_CATEGORY,
                            MEDIADIVE_MEDIUM_TYPE_DEFINED_LABEL,
                        ),
                    ]
                )
                for dictionary in input_json[DATA_KEY]:
                    id = str(dictionary[ID_COLUMN])
                    dictionary[NAME_COLUMN] = (
                        dictionary[NAME_COLUMN].translate(self.translation_table).replace('""', "").strip()
                    )
                    fn: Path = Path(str(MEDIADIVE_MEDIUM_YAML_DIR / id) + ".yaml")
                    fn_medium_strain = Path(str(MEDIADIVE_MEDIUM_STRAIN_YAML_DIR / id) + ".yaml")
                    json_obj = self.get_json_object(fn, MEDIUM + id, MEDIADIVE_MEDIUM_YAML_DIR)
                    json_obj_medium_strain = self.get_json_object(
                        fn_medium_strain, MEDIUM_STRAINS + id, MEDIADIVE_MEDIUM_STRAIN_YAML_DIR
                    )

                    medium_id = MEDIADIVE_MEDIUM_PREFIX + str(id)  # SUBJECT

                    # Medium and Medium type edge
                    medium_type_edges = []
                    complex_medium_type = bool(dictionary[MEDIADIVE_COMPLEX_MEDIUM_COLUMN])
                    # Pick the type-specific multi-cat category for the
                    # individual medium node so downstream queries can filter
                    # defined vs. complex media via biolink categories alone.
                    medium_category = MEDIUM_COMPLEX_CATEGORY if complex_medium_type else MEDIUM_DEFINED_CATEGORY
                    if complex_medium_type:
                        medium_type_edges = [
                            [
                                medium_id,
                                SUBCLASS_PREDICATE,
                                MEDIADIVE_MEDIUM_TYPE_COMPLEX_ID,
                                RDFS_SUBCLASS_OF,
                                self.knowledge_source,
                                OBSERVATION,
                                MANUAL_AGENT,
                            ]
                        ]
                    else:
                        medium_type_edges = [
                            [
                                medium_id,
                                SUBCLASS_PREDICATE,
                                MEDIADIVE_MEDIUM_TYPE_DEFINED_ID,
                                RDFS_SUBCLASS_OF,
                                self.knowledge_source,
                                OBSERVATION,
                                MANUAL_AGENT,
                            ]
                        ]
                    edge_writer.writerows(medium_type_edges)

                    # Emit the medium's own node row HERE — before any of the
                    # downstream `continue` short-circuits (e.g. when the
                    # medium has no SOLUTIONS_KEY in its detail JSON, see
                    # ``if SOLUTIONS_KEY not in json_obj: continue`` below).
                    # Previously this lived at the very end of the loop, so
                    # short-circuiting media (P1–P10 pharmacopoeial entries
                    # without solution definitions) emitted their
                    # subclass_of edge to a medium-type without a node row,
                    # surfacing as merge-time NamedThing fallbacks. Found by
                    # the `orphan-edges` archetype in kg-path-review.
                    node_writer.writerow(self._create_node_row(medium_id, medium_category, dictionary[NAME_COLUMN]))

                    # Medium-Strains KG
                    medium_strain_nodes = []
                    if json_obj_medium_strain:
                        medium_strain_edge = []
                        for strain in json_obj_medium_strain:
                            if strain.get(BACDIVE_ID_COLUMN):
                                strain_id = BACDIVE_PREFIX + str(strain[BACDIVE_ID_COLUMN])
                                # Fast O(1) dictionary lookup instead of O(n) DataFrame filtering
                                ncbi_strain_id = bacdive_strain_to_ncbi.get(
                                    strain_id, STRAIN_PREFIX + strain_id.replace(":", "_")
                                )

                                if not (isinstance(ncbi_strain_id, float) and math.isnan(ncbi_strain_id)):
                                    # Check growth value to determine edge type
                                    # MediaDive uses: growth=1 (positive), growth=0 (negative)
                                    growth_value = strain.get("growth")

                                    # Only create edge if growth value is explicitly 0 or 1
                                    if growth_value in [0, 1]:
                                        if growth_value == 1:
                                            # Positive growth: organism grows in this medium
                                            predicate = NCBI_TO_MEDIUM_EDGE
                                            relation = IS_GROWN_IN
                                        else:  # growth_value == 0
                                            # Negative growth: organism does not grow in this medium
                                            predicate = NCBI_TO_MEDIUM_NEGATIVE_EDGE
                                            relation = DOES_NOT_GROW_IN

                                        medium_strain_nodes.extend(
                                            [
                                                self._create_node_row(
                                                    ncbi_strain_id,
                                                    NCBI_CATEGORY,
                                                    strain[SPECIES],
                                                ),
                                                self._create_node_row(
                                                    medium_id,
                                                    medium_category,
                                                    dictionary[NAME_COLUMN],
                                                ),
                                            ]
                                        )

                                        # The resource is scalar; its public record page is
                                        # publication evidence, matching BacDive (#688, #1070).
                                        medium_strain_edge.extend(
                                            [
                                                [
                                                    ncbi_strain_id,
                                                    predicate,
                                                    medium_id,
                                                    relation,
                                                    "infores:bacdive",
                                                    OBSERVATION,
                                                    MANUAL_AGENT,
                                                    "",
                                                    "",
                                                    bacdive_record_url(strain_id),
                                                ],
                                            ]
                                        )

                                        edge_writer.writerows(medium_strain_edge)

                    if SOLUTIONS_KEY not in json_obj:
                        continue
                    # solution_id_list = [solution[ID_COLUMN] for solution in json_obj[SOLUTIONS_KEY]]
                    solutions_dict = {
                        solution[ID_COLUMN]: solution[NAME_COLUMN].strip().translate(self.translation_table)
                        for solution in json_obj[SOLUTIONS_KEY]
                    }
                    ingredient_occurrences = []
                    ingredient_declarations = {}
                    solution_ingredient_edges = []

                    for solution_id in solutions_dict.keys():
                        solution_curie = MEDIADIVE_SOLUTION_PREFIX + str(solution_id)
                        # Every source occurrence drives its own assertion, even
                        # equal-name/equal-quantity repeats. Node declarations are
                        # accumulated separately by identity and display label;
                        # another solution cannot overwrite a same-named target.
                        solution_ingredients = self.get_solution_recipe_occurrences(str(solution_id))
                        ingredient_occurrences.extend(solution_ingredients)
                        for occurrence in solution_ingredients:
                            ingredient_declarations[(occurrence[ID_COLUMN], occurrence[NAME_COLUMN])] = occurrence
                        solution_ingredient_edges.extend(
                            [
                                [
                                    solution_curie,
                                    MEDIUM_TO_INGREDIENT_EDGE,
                                    v[ID_COLUMN],
                                    HAS_PART,
                                    self.knowledge_source,  # Use infores:mediadive
                                    OBSERVATION,
                                    MANUAL_AGENT,
                                    v.get(AMOUNT_COLUMN) if v.get(AMOUNT_COLUMN) is not None else "",
                                    v.get(UNIT_COLUMN) if v.get(UNIT_COLUMN) is not None else "",
                                    "",
                                    v[SOURCE_ASSERTION_ID_COLUMN],
                                    v[SOURCE_RECORD_COLUMN],
                                    v.get(GRAMS_PER_LITER_COLUMN) if v.get(GRAMS_PER_LITER_COLUMN) is not None else "",
                                    v.get(MMOL_PER_LITER_COLUMN) if v.get(MMOL_PER_LITER_COLUMN) is not None else "",
                                ]
                                for v in solution_ingredients
                            ]
                        )
                        solution_ingredient_edges.append(
                            # Add medium_solution_edge here too
                            [
                                medium_id,
                                MEDIUM_TO_SOLUTION_EDGE,
                                solution_curie,
                                HAS_PART,
                                self.knowledge_source,  # Use infores:mediadive
                                OBSERVATION,
                                MANUAL_AGENT,
                            ]
                        )

                    ingredient_nodes = []
                    ingredient_subclass_edges = []
                    for (_, k), v in ingredient_declarations.items():
                        ingredient_id = v[ID_COLUMN]
                        enrichment = self.chemical_loader.get_node_enrichment(ingredient_id)
                        ingredient_nodes.append(
                            self._create_node_row(
                                ingredient_id,
                                self._classify_ingredient_category(ingredient_id, k),
                                k,
                                xref=enrichment["xref"] or None,
                                synonym=enrichment["synonym"] or None,
                            )
                        )
                        # If MIM curators have anchored this ingredient to a
                        # parent via skos:broadMatch (e.g. MIM:Vermont_Soil
                        # broadMatch ENVO:00001998), the unified mappings file
                        # carries those rows and the loader exposes them via
                        # get_parents(). MIM's contract (MAPPING_SEMANTICS.md
                        # Section 1, #245) is that the parent is the *closest
                        # broader term* -- the ingredient may be a salt, hydrate,
                        # solution or racemate of it, which ChEBI models with
                        # has-part, not is_a -- so emit biolink:broad_match,
                        # never biolink:subclass_of, one edge per parent.
                        for parent_id in self.chemical_loader.get_parents(ingredient_id):
                            ingredient_subclass_edges.append(
                                [
                                    ingredient_id,
                                    BROAD_MATCH_PREDICATE,
                                    parent_id,
                                    BROAD_MATCH_RELATION,
                                    self.knowledge_source,
                                    "knowledge_assertion",
                                    "manual_agent",
                                    "",
                                    "",
                                ]
                            )
                    solution_nodes = [
                        self._create_node_row(MEDIADIVE_SOLUTION_PREFIX + str(k), SOLUTION_CATEGORY, v)
                        for k, v in solutions_dict.items()
                    ]
                    # Each MediaDive solution is a chemical mixture — subclass it under
                    # CHEBI:60004 (mixture) so OBO-aware reasoners can navigate from any
                    # solution back to the canonical chemical hierarchy. Edge schema is
                    # the standard edge_header, with the final publications cell empty.
                    solution_subclass_edges = [
                        [
                            MEDIADIVE_SOLUTION_PREFIX + str(k),
                            "biolink:subclass_of",
                            "CHEBI:60004",
                            "rdfs:subClassOf",
                            self.knowledge_source,
                            "knowledge_assertion",
                            "manual_agent",
                            "",
                            "",
                        ]
                        for k in solutions_dict.keys()
                    ]

                    # Get ChEBI role relationships using fast TSV lookup
                    chebi_list = [
                        v[ID_COLUMN]
                        for v in ingredient_declarations.values()
                        if str(v[ID_COLUMN]).startswith(CHEBI_PREFIX)
                    ]
                    if len(chebi_list) > 0 and self.chebi_roles:
                        # Collect all role relationships for these compounds
                        role_set = set()
                        role_edges_data = self._generate_chebi_role_edges(chebi_list)
                        for chebi_id in chebi_list:
                            if chebi_id in self.chebi_roles:
                                for role_id in self.chebi_roles[chebi_id]:
                                    role_set.add(role_id)
                        # Write role nodes with labels
                        role_nodes = []
                        for role in role_set:
                            role_enrich = self.chemical_loader.get_node_enrichment(role)
                            role_nodes.append(
                                self._create_node_row(
                                    role,
                                    ROLE_CATEGORY,
                                    self.chebi_labels.get(role, ""),
                                    xref=role_enrich["xref"] or None,
                                    synonym=role_enrich["synonym"] or None,
                                )
                            )
                        node_writer.writerows(role_nodes)
                        edge_writer.writerows(role_edges_data)

                    data = [
                        medium_id,
                        dictionary[NAME_COLUMN],
                        dictionary[MEDIADIVE_COMPLEX_MEDIUM_COLUMN],
                        dictionary[MEDIADIVE_SOURCE_COLUMN],
                        dictionary[MEDIADIVE_LINK_COLUMN],
                        dictionary[MEDIADIVE_MIN_PH_COLUMN],
                        dictionary[MEDIADIVE_MAX_PH_COLUMN],
                        dictionary[MEDIADIVE_REF_COLUMN],
                        dictionary[MEDIADIVE_DESC_COLUMN],
                        str(solutions_dict),
                        str(ingredient_occurrences),
                    ]

                    writer.writerow(data)  # writing the data

                    # The medium's own node row was already written earlier,
                    # before the SOLUTIONS_KEY short-circuit. Solution and
                    # ingredient rows are still emitted here.
                    nodes_data_to_write = [
                        *solution_nodes,
                        *ingredient_nodes,
                        *medium_strain_nodes,
                    ]
                    node_writer.writerows(nodes_data_to_write)

                    edge_writer.writerows(solution_ingredient_edges)
                    if solution_subclass_edges:
                        edge_writer.writerows(solution_subclass_edges)
                    if ingredient_subclass_edges:
                        edge_writer.writerows(ingredient_subclass_edges)

                    progress.set_description(f"Processing mediadive: {medium_id}")
                    # After each iteration, call the update method to advance the progress bar.
                    progress.update()

        drop_duplicates(
            self.output_node_file,
            sort_by_column=ID_COLUMN,
            dedup_on_sort_column=True,
        )
        drop_duplicates(self.output_edge_file)
        self.verify_consumed_inputs()
        self._material_scope_audit.write()

        # Print data source and API call statistics
        print("\n" + "=" * 80)
        print("MediaDive Transform Complete")
        print("=" * 80)
        if self.using_bulk_data:
            print(f"Data source: Bulk downloaded files ({self.bulk_data_dir}/)")
            print(f"API calls avoided: {self.api_calls_avoided}")
            print(f"API calls made: {self.api_calls_made}")
            print("YAML/HTTP fallback: disabled in bulk mode")
        else:
            print("Data source: MediaDive API (slow - consider running bulk download)")
            print(f"API calls made: {self.api_calls_made}")
            print("To speed up future transforms, run: poetry run kg download")
        print("=" * 80 + "\n")

        # ! Commented out after discussing with Marcin. This is not needed for now.
        # establish_transitive_relationship(
        #     self.output_edge_file,
        #     MEDIADIVE_MEDIUM_PREFIX,
        #     MEDIADIVE_SOLUTION_PREFIX,
        #     MEDIUM_TO_INGREDIENT_EDGE,
        #     [
        #         MEDIADIVE_INGREDIENT_PREFIX,
        #         CHEBI_PREFIX,
        #         KEGG_PREFIX,
        #         PUBCHEM_PREFIX,
        #         CAS_RN_PREFIX,
        #     ],
        # )

        # # dump_ont_nodes_from(
        # #     self.output_node_file, self.input_base_dir / CHEBI_NODES_FILENAME, CHEBI_PREFIX
        # # )
        # get_ingredients_overlap(self.output_edge_file, MEDIADIVE_TMP_DIR / "ingredient_overlap.tsv")
