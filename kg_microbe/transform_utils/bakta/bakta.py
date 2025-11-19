"""Transform for Bakta genome annotations."""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd
from oaklib import get_adapter
from tqdm import tqdm

from kg_microbe.transform_utils.bakta.utils import (
    create_gene_id,
    extract_samn_from_path,
    find_bakta_tsv,
    get_all_samn_directories,
    get_biolink_category_for_go,
    get_biolink_predicate_for_go,
    get_go_aspect,
    get_protein_id,
    load_samn_to_ncbitaxon_mapping,
    parse_bakta_tsv,
    parse_dbxrefs,
)
from kg_microbe.transform_utils.constants import (
    BAKTA,
    BAKTA_DIR,
    BAKTA_RAW_DIR,
    CATEGORY_COLUMN,
    DESCRIPTION_COLUMN,
    GO_SOURCE,
    ID_COLUMN,
    NAME_COLUMN,
    OBJECT_COLUMN,
    PREDICATE_COLUMN,
    PRIMARY_KNOWLEDGE_SOURCE_COLUMN,
    PROVIDED_BY_COLUMN,
    RELATION_COLUMN,
    SUBJECT_COLUMN,
    XREF_COLUMN,
)
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.dummy_tqdm import DummyTqdm

logger = logging.getLogger(__name__)


class BaktaTransform(Transform):

    """Transform Bakta genome annotations into KGX format."""

    def __init__(
        self,
        input_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize BaktaTransform.

        :param input_dir: Path to input directory (default: data/raw)
        :param output_dir: Path to output directory (default: data/transformed)
        """
        source_name = BAKTA
        super().__init__(source_name, input_dir, output_dir)

        # Load GO ontology for aspect mapping
        # Try to use GO adapter, but handle gracefully if not available
        try:
            # First try SQLite if .db version exists
            go_db = GO_SOURCE.with_suffix(".db")
            if go_db.exists():
                self.go_adapter = get_adapter(f"sqlite:{go_db}")
            else:
                # Fall back to OWL file (OAK will auto-detect format)
                self.go_adapter = get_adapter(str(GO_SOURCE))
        except Exception as e:
            logger.warning(f"Could not load GO ontology: {e}")
            logger.warning("GO term aspect mapping will default to molecular_function")
            self.go_adapter = None

        # Load SAMN to NCBITaxon mapping
        mapping_file = BAKTA_DIR / "samn_to_ncbitaxon.tsv"
        self.samn_to_ncbitaxon = load_samn_to_ncbitaxon_mapping(mapping_file)

        # Collections for nodes and edges
        self.nodes: List[Dict] = []
        self.edges: List[Dict] = []

        # Track seen entities to avoid duplicates
        self.seen_nodes: Set[str] = set()

        # Knowledge source
        self.knowledge_source = "infores:bakta"

    def run(self, data_file: Optional[Path] = None, show_status: bool = True) -> None:
        """
        Run the Bakta transform.

        :param data_file: Not used (kept for API compatibility)
        :param show_status: Show progress bar (default: True)
        """
        logger.info("Starting Bakta transform")

        # Get all SAMN directories
        samn_dirs = get_all_samn_directories(BAKTA_RAW_DIR)

        if not samn_dirs:
            logger.error(f"No SAMN directories found in {BAKTA_RAW_DIR}")
            return

        logger.info(f"Processing {len(samn_dirs)} genomes")

        # Progress bar
        progress_bar = tqdm(samn_dirs) if show_status else DummyTqdm(samn_dirs)

        # Process each genome
        for samn_dir in progress_bar:
            samn_id = extract_samn_from_path(samn_dir)

            if show_status:
                progress_bar.set_description(f"Processing {samn_id}")

            self.process_genome(samn_dir, samn_id)

        # Write output files
        logger.info(f"Writing {len(self.nodes)} nodes and {len(self.edges)} edges")
        self.write_output()

        logger.info("Bakta transform complete")

    def process_genome(self, samn_dir: Path, samn_id: str) -> None:
        """
        Process a single genome directory.

        :param samn_dir: Path to SAMN directory
        :param samn_id: SAMN identifier
        """
        # Find the .bakta.tsv file
        tsv_file = find_bakta_tsv(samn_dir)
        if not tsv_file:
            return

        # Parse the TSV file (only CDS features)
        genes = parse_bakta_tsv(tsv_file, feature_types={"cds"})

        if not genes:
            logger.warning(f"No CDS features found in {tsv_file}")
            return

        # Create organism node if we have NCBITaxon mapping
        organism_id = self.get_organism_id(samn_id)
        if organism_id:
            self.add_organism_node(organism_id, samn_id)

        # Process each gene
        for gene_data in genes:
            self.process_gene(gene_data, samn_id, organism_id)

    def get_organism_id(self, samn_id: str) -> str:
        """
        Get the organism ID (SAMN-level for strain resolution).

        :param samn_id: SAMN identifier
        :return: SAMN organism ID (e.g., 'SAMN:00139461')
        """
        # Always use SAMN as organism ID to maintain strain-level resolution
        return f"SAMN:{samn_id.replace('SAMN', '')}"

    def get_ncbitaxon_id(self, samn_id: str) -> Optional[str]:
        """
        Get NCBITaxon ID for a SAMN identifier.

        :param samn_id: SAMN identifier
        :return: NCBITaxon ID or None
        """
        if samn_id in self.samn_to_ncbitaxon:
            return self.samn_to_ncbitaxon[samn_id]
        return None

    def add_organism_node(self, organism_id: str, samn_id: str) -> None:
        """
        Add a strain-level organism node (SAMN) and link to species (NCBITaxon).

        :param organism_id: SAMN organism identifier (e.g., 'SAMN:00139461')
        :param samn_id: SAMN identifier for lookup
        """
        if organism_id in self.seen_nodes:
            return

        # Create SAMN organism node (strain level)
        node = {
            ID_COLUMN: organism_id,
            CATEGORY_COLUMN: "biolink:OrganismTaxon",
            NAME_COLUMN: "",  # Would need to query for name
            XREF_COLUMN: "",
            PROVIDED_BY_COLUMN: self.knowledge_source,
        }

        self.nodes.append(node)
        self.seen_nodes.add(organism_id)

        # If we have NCBITaxon mapping, create species node and edge
        ncbitaxon_id = self.get_ncbitaxon_id(samn_id)
        if ncbitaxon_id:
            # Add NCBITaxon species node
            if ncbitaxon_id not in self.seen_nodes:
                species_node = {
                    ID_COLUMN: ncbitaxon_id,
                    CATEGORY_COLUMN: "biolink:OrganismTaxon",
                    NAME_COLUMN: "",
                    XREF_COLUMN: "",
                    PROVIDED_BY_COLUMN: "infores:ncbitaxon",
                }
                self.nodes.append(species_node)
                self.seen_nodes.add(ncbitaxon_id)

            # Add strain -> species edge (subclass_of relationship)
            self.add_edge(
                organism_id,
                "biolink:subclass_of",
                ncbitaxon_id,
                "rdfs:subClassOf",
            )

    def process_gene(
        self, gene_data: Dict[str, str], samn_id: str, organism_id: Optional[str]
    ) -> None:
        """
        Process a single gene annotation.

        :param gene_data: Gene data dictionary from Bakta TSV
        :param samn_id: SAMN identifier
        :param organism_id: Organism identifier (if available)
        """
        locus_tag = gene_data.get("Locus Tag", "")
        if not locus_tag:
            return

        # Create composite gene ID
        gene_id = create_gene_id(samn_id, locus_tag)

        # Parse annotations from DbXrefs
        dbxrefs = gene_data.get("DbXrefs", "")
        annotations = parse_dbxrefs(dbxrefs)

        # Get protein ID (RefSeq preferred, UniRef fallback)
        protein_id = get_protein_id(annotations, prefer_refseq=True)

        # Get gene info
        gene_symbol = gene_data.get("Gene", "")
        product = gene_data.get("Product", "")

        # Add gene node
        self.add_gene_node(gene_id, gene_symbol, product, annotations)

        # Add organism -> gene edge
        if organism_id:
            self.add_edge(
                organism_id,
                "biolink:has_gene",
                gene_id,
                "RO:0002551",  # has gene
            )

        # Add protein node and gene -> protein edge
        if protein_id:
            self.add_protein_node(protein_id, product, annotations)
            self.add_edge(
                gene_id,
                "biolink:has_gene_product",
                protein_id,
                "RO:0002205",  # has gene product
            )

            # Add protein functional annotations
            self.add_functional_annotations(protein_id, gene_id, annotations)

    def add_gene_node(
        self, gene_id: str, gene_symbol: str, product: str, annotations: Dict[str, List[str]]
    ) -> None:
        """
        Add a gene node.

        :param gene_id: Composite gene ID
        :param gene_symbol: Gene symbol (may be empty)
        :param product: Gene product description
        :param annotations: Parsed annotations dictionary
        """
        if gene_id in self.seen_nodes:
            return

        # Build xrefs
        xrefs = []
        if annotations.get("refseq"):
            xrefs.extend([f"RefSeq:{rid}" for rid in annotations["refseq"]])
        if annotations.get("uniparc"):
            xrefs.extend([f"UniParc:{uid}" for uid in annotations["uniparc"]])

        node = {
            ID_COLUMN: gene_id,
            CATEGORY_COLUMN: "biolink:Gene",
            NAME_COLUMN: gene_symbol if gene_symbol else "",
            DESCRIPTION_COLUMN: product if product else "",
            XREF_COLUMN: "|".join(xrefs) if xrefs else "",
            PROVIDED_BY_COLUMN: self.knowledge_source,
        }

        self.nodes.append(node)
        self.seen_nodes.add(gene_id)

    def add_protein_node(
        self, protein_id: str, product: str, annotations: Dict[str, List[str]]
    ) -> None:
        """
        Add a protein node.

        :param protein_id: Protein identifier (RefSeq or UniRef)
        :param product: Protein product description
        :param annotations: Parsed annotations dictionary
        """
        if protein_id in self.seen_nodes:
            return

        # Build xrefs for protein
        xrefs = []
        if annotations.get("uniref"):
            # Add all UniRef levels as xrefs
            for uniref_id in annotations["uniref"]:
                xrefs.append(f"UniRef:{uniref_id}")
        if annotations.get("refseq") and not protein_id.startswith("RefSeq:"):
            # If using UniRef as primary, add RefSeq as xref
            xrefs.extend([f"RefSeq:{rid}" for rid in annotations["refseq"]])

        node = {
            ID_COLUMN: protein_id,
            CATEGORY_COLUMN: "biolink:Protein",
            NAME_COLUMN: product if product else "",
            XREF_COLUMN: "|".join(xrefs) if xrefs else "",
            PROVIDED_BY_COLUMN: self.knowledge_source,
        }

        self.nodes.append(node)
        self.seen_nodes.add(protein_id)

    def add_functional_annotations(
        self, protein_id: str, gene_id: str, annotations: Dict[str, List[str]]
    ) -> None:
        """
        Add functional annotation nodes and edges.

        :param protein_id: Protein identifier
        :param gene_id: Gene identifier
        :param annotations: Parsed annotations dictionary
        """
        # GO terms
        for go_id in annotations.get("go", []):
            self.add_go_annotation(protein_id, go_id)

        # EC numbers
        for ec_id in annotations.get("ec", []):
            self.add_ec_annotation(protein_id, ec_id)

        # COG groups - COMMENTED OUT
        # for cog_id in annotations.get("cog", []):
        #     self.add_cog_annotation(gene_id, cog_id)

        # KEGG orthologs - COMMENTED OUT
        # for kegg_id in annotations.get("kegg", []):
        #     self.add_kegg_annotation(gene_id, kegg_id)

    def add_go_annotation(self, protein_id: str, go_id: str) -> None:
        """
        Add GO term node and protein -> GO edge.

        :param protein_id: Protein identifier
        :param go_id: GO identifier (e.g., 'GO:0003677')
        """
        # Determine GO aspect
        aspect = get_go_aspect(go_id, self.go_adapter)

        # Get Biolink category and predicate
        category = get_biolink_category_for_go(aspect)
        predicate, relation = get_biolink_predicate_for_go(aspect)

        # Add GO term node
        if go_id not in self.seen_nodes:
            node = {
                ID_COLUMN: go_id,
                CATEGORY_COLUMN: category,
                NAME_COLUMN: "",  # Could query GO adapter for label
                PROVIDED_BY_COLUMN: "infores:go",
            }
            self.nodes.append(node)
            self.seen_nodes.add(go_id)

        # Add protein -> GO edge
        self.add_edge(protein_id, predicate, go_id, relation)

    def add_ec_annotation(self, protein_id: str, ec_id: str) -> None:
        """
        Add EC number node and protein -> EC edge.

        :param protein_id: Protein identifier
        :param ec_id: EC identifier (e.g., 'EC:1.4.99.6')
        """
        # Add EC node
        if ec_id not in self.seen_nodes:
            node = {
                ID_COLUMN: ec_id,
                CATEGORY_COLUMN: "biolink:MolecularActivity",
                NAME_COLUMN: "",
                PROVIDED_BY_COLUMN: "infores:ec",
            }
            self.nodes.append(node)
            self.seen_nodes.add(ec_id)

        # Add protein -> EC edge (enables)
        self.add_edge(
            protein_id,
            "biolink:enables",
            ec_id,
            "RO:0002327",  # enables
        )

    def add_cog_annotation(self, gene_id: str, cog_id: str) -> None:
        """
        Add COG node and gene -> COG edge.

        :param gene_id: Gene identifier
        :param cog_id: COG identifier (e.g., 'COG:COG0665')
        """
        # Add COG node
        if cog_id not in self.seen_nodes:
            node = {
                ID_COLUMN: cog_id,
                CATEGORY_COLUMN: "biolink:GeneFamily",
                NAME_COLUMN: "",
                PROVIDED_BY_COLUMN: "infores:cog",
            }
            self.nodes.append(node)
            self.seen_nodes.add(cog_id)

        # Add gene -> COG edge (member_of)
        self.add_edge(
            gene_id,
            "biolink:member_of",
            cog_id,
            "RO:0002350",  # member of
        )

    def add_kegg_annotation(self, gene_id: str, kegg_id: str) -> None:
        """
        Add KEGG KO node and gene -> KEGG edge.

        :param gene_id: Gene identifier
        :param kegg_id: KEGG identifier (e.g., 'KEGG:K19746')
        """
        # Add KEGG node
        if kegg_id not in self.seen_nodes:
            node = {
                ID_COLUMN: kegg_id,
                CATEGORY_COLUMN: "biolink:GeneFamily",
                NAME_COLUMN: "",
                PROVIDED_BY_COLUMN: "infores:kegg",
            }
            self.nodes.append(node)
            self.seen_nodes.add(kegg_id)

        # Add gene -> KEGG edge (orthologous_to)
        self.add_edge(
            gene_id,
            "biolink:orthologous_to",
            kegg_id,
            "RO:HOM0000017",  # orthologous to
        )

    def add_edge(self, subject: str, predicate: str, obj: str, relation: str) -> None:
        """
        Add an edge to the collection.

        :param subject: Subject node ID
        :param predicate: Biolink predicate
        :param obj: Object node ID
        :param relation: RO or other relation ontology term
        """
        edge = {
            SUBJECT_COLUMN: subject,
            PREDICATE_COLUMN: predicate,
            OBJECT_COLUMN: obj,
            RELATION_COLUMN: relation,
            PRIMARY_KNOWLEDGE_SOURCE_COLUMN: self.knowledge_source,
        }

        self.edges.append(edge)

    def write_output(self) -> None:
        """Write nodes and edges to TSV files."""
        # Convert to DataFrames
        nodes_df = pd.DataFrame(self.nodes, columns=self.node_header)
        edges_df = pd.DataFrame(self.edges, columns=self.edge_header)

        # Drop duplicates
        nodes_df = nodes_df.drop_duplicates(subset=[ID_COLUMN])
        edges_df = edges_df.drop_duplicates()

        # Write to TSV
        nodes_df.to_csv(self.output_node_file, sep="\t", index=False)
        edges_df.to_csv(self.output_edge_file, sep="\t", index=False)

        logger.info(f"Wrote {len(nodes_df)} nodes to {self.output_node_file}")
        logger.info(f"Wrote {len(edges_df)} edges to {self.output_edge_file}")
