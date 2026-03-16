"""
Metatraits transform class.

Reads metatraits summary JSONL files from data/raw, resolves taxon names to NCBITaxon IDs,
maps trait names to METPO/ontology terms, and outputs KGX nodes.tsv and edges.tsv.
"""

import csv
import gzip
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

import yaml
from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.constants import (
    AUTOMATED_AGENT,
    BIOLOGICAL_PROCESS,
    CURIE_COLUMN,
    CUSTOM_CURIES_YAML_FILE,
    HAS_PHENOTYPE,
    ID_COLUMN,
    METATRAITS,
    NCBI_CATEGORY,
    NCBITAXON_NODES_FILE,
    NCBITAXON_SOURCE,
    OBSERVATION,
    PRODUCES_RELATION,
    RAW_DATA_DIR,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.mapping_file_utils import load_metpo_mappings, uri_to_curie
from kg_microbe.utils.microbial_trait_mappings import load_microbial_trait_mappings
from kg_microbe.utils.oak_utils import search_by_label
from kg_microbe.utils.pandas_utils import drop_duplicates

# METPO predicate -> biolink predicate (for relation lookup)
METPO_TO_BIOLINK_PREDICATE = {
    "METPO:2000103": "biolink:capable_of",  # capable of
    "METPO:2000202": "biolink:produces",  # produces
    "METPO:2000222": "biolink:produces",  # does not produce (negative)
}

# Biolink predicate -> RO relation
PREDICATE_TO_RELATION = {
    "biolink:produces": PRODUCES_RELATION,
    "biolink:capable_of": BIOLOGICAL_PROCESS,
    "biolink:has_phenotype": HAS_PHENOTYPE,
}

# Input file names (transform accepts either ncbi_* or metatraits_* convention)
METATRAITS_INPUT_FILES = [
    "ncbi_species_summary.jsonl.gz",
    "ncbi_genus_summary.jsonl.gz",
    "ncbi_family_summary.jsonl.gz",
    "metatraits_species_summary.jsonl.gz",
    "metatraits_genus_summary.jsonl.gz",
    "metatraits_family_summary.jsonl.gz",
]


def _get_ncbitaxon_adapter():
    """Get OAK adapter for NCBITaxon; use pre-built sqlite:obo:ncbitaxon if local source invalid."""
    local_path = f"sqlite:{NCBITAXON_SOURCE}"
    try:
        adapter = get_adapter(local_path)
        # Verify adapter works (e.g. has statements table)
        list(adapter.basic_search("Bacteria", limit=1))
        return adapter
    except Exception:
        return get_adapter("sqlite:obo:ncbitaxon")


def _open_jsonl(path: Path):
    """
    Open JSONL file; use gzip for .gz files, plain text otherwise.

    If a .gz file is not actually gzip-compressed (e.g. misnamed plain JSON),
    falls back to plain text.
    """
    if path.name.endswith(".gz"):
        try:
            f = gzip.open(path, "rt", encoding="utf-8")
            f.read(1)  # Trigger gzip header read
            f.seek(0)
            return f
        except gzip.BadGzipFile:
            return open(path, "r", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


class MetatraitsTransform(Transform):

    """Transform metatraits summary JSONL files into KGX nodes and edges."""

    def __init__(
        self,
        input_dir: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
    ):
        """
        Initialize MetatraitsTransform.

        :param input_dir: Input directory (default: data/raw)
        :param output_dir: Output directory (default: data/transformed)
        """
        super().__init__(METATRAITS, input_dir, output_dir)
        self.knowledge_source = "infores:metatraits"
        self.microbial_mappings = load_microbial_trait_mappings()
        self.metpo_mappings = load_metpo_mappings("madin synonym or field")
        # Defer adapter creation until first cache miss (avoids ~2GB download when
        # ncbitaxon_nodes.tsv has full coverage)
        self._ncbi_adapter = None

        # Taxon name -> NCBITaxon ID cache
        self.ncbitaxon_name_to_id: Dict[str, str] = {}
        self._load_ncbitaxon_labels()

        # Trait name -> (curie, category, predicate) from METPO + custom_curies (fallback)
        self.trait_mapping: Dict[str, dict] = {}
        self._build_trait_mapping()

        self.unmapped_traits_file = self.output_dir / "unmapped_traits.tsv"
        self.unresolved_taxa_file = self.output_dir / "unresolved_taxa.tsv"

    def _load_ncbitaxon_labels(self) -> None:
        """Load NCBITaxon labels from ontologies output, data/raw, or OAK fallback."""
        # Prefer ontologies transform output, then data/raw/ncbitaxon_nodes.tsv (manual placement)
        for path in [NCBITAXON_NODES_FILE, RAW_DATA_DIR / "ncbitaxon_nodes.tsv"]:
            if path.exists():
                try:
                    with open(path) as f:
                        f.readline()  # skip header
                        for line in f:
                            parts = line.strip().split("\t")
                            if len(parts) >= 3:
                                node_id = parts[0]
                                name = parts[2]
                                if node_id.startswith("NCBITaxon:") and name:
                                    self.ncbitaxon_name_to_id[name.lower()] = node_id
                    print(f"  Loaded {len(self.ncbitaxon_name_to_id)} NCBITaxon labels from {path.name}")
                    return
                except Exception as e:
                    print(f"Warning: Could not load NCBITaxon labels from {path}: {e}")

    def _get_ncbitaxon_impl(self):
        """Return OAK adapter for NCBITaxon, creating it on first use."""
        if self._ncbi_adapter is None:
            self._ncbi_adapter = _get_ncbitaxon_adapter()
        return self._ncbi_adapter

    def _search_ncbitaxon_by_label(self, search_name: str) -> Optional[str]:
        """Resolve taxon name to NCBITaxon ID. Caches OAK results to avoid repeated lookups."""
        key = search_name.lower()
        ncbitaxon_id = self.ncbitaxon_name_to_id.get(key)
        if ncbitaxon_id:
            return ncbitaxon_id
        results = search_by_label(self._get_ncbitaxon_impl(), search_name, limit=1)
        if results:
            ncbitaxon_id = results[0]
            self.ncbitaxon_name_to_id[key] = ncbitaxon_id
            return ncbitaxon_id
        return None

    def _build_trait_mapping(self) -> None:
        """Build trait name -> (curie, category, predicate) from METPO and custom_curies."""
        for synonym, metpo_data in self.metpo_mappings.items():
            category_url = metpo_data.get("inferred_category", "")
            category = uri_to_curie(category_url) if category_url else "biolink:PhenotypicQuality"
            predicate_biolink = metpo_data.get("predicate_biolink_equivalent", "")
            predicate = uri_to_curie(predicate_biolink) if predicate_biolink else "biolink:has_phenotype"
            self.trait_mapping[synonym] = {
                "curie": metpo_data["curie"],
                "category": category,
                "name": metpo_data["label"],
                "predicate": predicate,
            }
            self.trait_mapping[synonym.lower()] = self.trait_mapping[synonym]

        if CUSTOM_CURIES_YAML_FILE.exists():
            with open(CUSTOM_CURIES_YAML_FILE) as f:
                custom_data = yaml.safe_load(f)
            custom_map = {
                k: v for first in (custom_data or {}).values() if isinstance(first, dict) for k, v in first.items()
            }
            for key, value in custom_map.items():
                if not isinstance(value, dict):
                    continue
                if key not in self.trait_mapping and key.lower() not in self.trait_mapping:
                    curie = value.get("curie") or value.get(CURIE_COLUMN)
                    if curie:
                        self.trait_mapping[key] = {
                            "curie": curie,
                            "category": value.get("category", "biolink:PhenotypicQuality"),
                            "name": value.get("name", key),
                            "predicate": value.get("predicate", "biolink:has_phenotype"),
                        }
                        self.trait_mapping[key.lower()] = self.trait_mapping[key]

    def _create_node_row(
        self,
        node_id: str,
        category: str,
        name: str,
        description: Optional[str] = None,
        xref: Optional[str] = None,
        synonym: Optional[str] = None,
        same_as: Optional[str] = None,
    ) -> List:
        """Create a node row matching node_header."""
        node_row = [None] * len(self.node_header)
        node_row[0] = node_id
        node_row[1] = category
        node_row[2] = name
        node_row[3] = description
        node_row[4] = xref
        node_row[5] = self.knowledge_source
        node_row[6] = synonym
        node_row[7] = same_as
        return node_row

    def _to_biolink_predicate(self, predicate: str) -> str:
        """Map METPO or other predicate to biolink predicate for relation lookup."""
        if predicate.startswith("biolink:"):
            return predicate
        return METPO_TO_BIOLINK_PREDICATE.get(predicate, "biolink:has_phenotype")

    def _get_relation_for_predicate(self, predicate: str) -> str:
        """Return RO relation for a given predicate (preserves produces/capable_of/has_phenotype)."""
        biolink_pred = self._to_biolink_predicate(predicate)
        return PREDICATE_TO_RELATION.get(biolink_pred, HAS_PHENOTYPE)

    def run(
        self,
        data_file: Union[Optional[Path], Optional[str]] = None,
        show_status: bool = True,
    ) -> None:
        """
        Run MetatraitsTransform.

        :param data_file: Ignored; uses configured input file list.
        :param show_status: Whether to show progress bar.
        """
        input_base = Path(self.input_base_dir)

        # Find which input files exist
        input_files: List[Path] = []
        seen: Set[str] = set()
        for name in METATRAITS_INPUT_FILES:
            p = input_base / name
            if p.exists() and str(p) not in seen:
                input_files.append(p)
                seen.add(str(p))
            else:
                plain_name = name.replace(".gz", "")
                p = input_base / plain_name
                if p.exists() and str(p) not in seen:
                    input_files.append(p)
                    seen.add(str(p))

        if not input_files:
            raise FileNotFoundError(
                f"No metatraits JSONL files found in {input_base}. Expected one of: {METATRAITS_INPUT_FILES}"
            )

        seen_taxon_nodes: Set[str] = set()
        seen_trait_nodes: Set[str] = set()
        node_rows: List[List] = []
        edge_rows: List[List] = []
        unmapped_traits: List[Tuple[str, str, str, int]] = []
        unresolved_taxa: List[str] = []

        iterable = tqdm(input_files, desc="Processing files") if show_status else input_files

        for input_path in iterable:
            with _open_jsonl(input_path) as f:
                line_iter = tqdm(f, desc=f"  {input_path.name}", leave=False) if show_status else f
                for line in line_iter:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    tax_name = obj.get("tax_name")
                    if not tax_name:
                        continue

                    tax_id = self._search_ncbitaxon_by_label(tax_name)
                    if not tax_id:
                        unresolved_taxa.append(tax_name)
                        continue

                    summaries = obj.get("summaries", [])
                    for s in summaries:
                        trait_name = s.get("name", "").strip()
                        if not trait_name:
                            continue

                        # Skip explicit negative (false: 100%)
                        majority_label = s.get("majority_label", "")
                        percentages = s.get("percentages", {}) or {}
                        pct_true = percentages.get("true", 0) or 0

                        if pct_true <= 0:
                            continue

                        # Lookup order: microbial-trait-mappings first, then METPO/custom_curies
                        micro_mapping = self.microbial_mappings.get(trait_name) or self.microbial_mappings.get(
                            trait_name.lower()
                        )
                        if micro_mapping:
                            curie = micro_mapping["object_id"]
                            category = micro_mapping["object_category"]
                            pred = micro_mapping["biolink_predicate"]
                            label = micro_mapping["object_label"]
                        else:
                            mapping = self.trait_mapping.get(trait_name) or self.trait_mapping.get(trait_name.lower())
                            if not mapping:
                                unmapped_traits.append(
                                    (
                                        trait_name,
                                        tax_name,
                                        majority_label,
                                        s.get("num_observations", 0),
                                    )
                                )
                                continue
                            curie = mapping["curie"]
                            category = mapping["category"]
                            # Use biolink predicate for KGX compliance
                            pred = self._to_biolink_predicate(mapping["predicate"])
                            label = mapping["name"]

                        if tax_id not in seen_taxon_nodes:
                            seen_taxon_nodes.add(tax_id)
                            node_rows.append(
                                self._create_node_row(
                                    tax_id,
                                    NCBI_CATEGORY,
                                    tax_name,
                                )
                            )

                        if curie not in seen_trait_nodes:
                            seen_trait_nodes.add(curie)
                            node_rows.append(self._create_node_row(curie, category, label))

                        relation = self._get_relation_for_predicate(pred)
                        edge_rows.append(
                            [
                                tax_id,
                                pred,
                                curie,
                                relation,
                                self.knowledge_source,
                                OBSERVATION,
                                AUTOMATED_AGENT,
                            ]
                        )

        # Write nodes and edges
        Path.mkdir(self.output_dir, exist_ok=True, parents=True)
        with open(self.output_node_file, "w", newline="") as nf:
            nw = csv.writer(nf, delimiter="\t")
            nw.writerow(self.node_header)
            nw.writerows(node_rows)

        with open(self.output_edge_file, "w", newline="") as ef:
            ew = csv.writer(ef, delimiter="\t")
            ew.writerow(self.edge_header)
            ew.writerows(edge_rows)

        drop_duplicates(self.output_node_file, sort_by_column=ID_COLUMN)
        drop_duplicates(self.output_edge_file)

        # Write unmapped traits and unresolved taxa
        with open(self.unmapped_traits_file, "w", newline="") as uf:
            uw = csv.writer(uf, delimiter="\t")
            uw.writerow(["trait_name", "tax_name", "majority_label", "num_observations"])
            uw.writerows(unmapped_traits)

        with open(self.unresolved_taxa_file, "w", newline="") as rf:
            rw = csv.writer(rf, delimiter="\t")
            rw.writerow(["tax_name"])
            for t in sorted(set(unresolved_taxa)):
                rw.writerow([t])
