import csv
import re
import os
import pandas as pd
from typing import Dict, List, Optional
from collections import defaultdict

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.transform_utils import parse_header, parse_line, write_node_edge_item

import pdb
"""
Ingest fierer dataset

Essentially just ingests and transforms this file:
https://github.com/bacteria-archaea-traits/bacteria-archaea-traits/blob/master/output/prepared_data/fierer.csv

And extracts the following columns:
    - tax_id
    - org_name
    - metabolism
    - carbon_substrates
    - cell_shape
    - isolation_source
"""

class FiererDataTransform(Transform):

    def __init__(self, input_dir: str = None, output_dir: str = None) -> None:
        source_name = "fierer"
        super().__init__(source_name, input_dir, output_dir)  # set some variables

        self.node_header = ['id', 'entity', 'category', 'reference', 'CURIE']
        self.edge_header = ['subject', 'edge_label', 'object', 'relation',
                            'reference', 'CURIE']

    def run(self, data_file: Optional[str] = None):
        """Method is called and performs needed transformations to process the 
        Fierer data, additional information on this data can be found in the comment 
        at the top of this script"""
        
        if data_file is None:
            data_file = "fierer.csv"
        
        input_file = os.path.join(
            self.input_base_dir, data_file)

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)



        # transform data, something like:
        with open(input_file, 'r') as f, \
                open(self.output_node_file, 'w') as node, \
                open(self.output_edge_file, 'w') as edge:

            # write headers (change default node/edge headers if necessary
            node.write("\t".join(self.node_header) + "\n")
            edge.write("\t".join(self.edge_header) + "\n")
            
            header_items = parse_header(f.readline(), sep=',')

            seen_organism: dict = defaultdict(int)
            seen_carbon_substrate: dict = defaultdict(int)
            seen_shape: dict = defaultdict(int)
            seen_isolation_source: dict = defaultdict(int)
            seen_metab_type: dict = defaultdict(int)


            # Nodes
            org_node_type = "biolink:OrganismTaxon" # [org_name]
            chem_node_type = "biolink:ChemicalSubstance" # [carbon_substrate]
            shape_node_type = "biolink:AbstractEntity" # [cell_shape]
            #metabolism_node_type = "biolink:ActivityAndBehavior" # [metabolism]
            source_node_type = "biolink:Association" # [isolation_source]
            
            #Prefixes
            org_prefix = "NCBITaxon:"
            chem_prefix = "Carbon:"
            shape_prefix = "Shape:"
            #activity_prefix = "Metab:"
            source_prefix = "Env:"

            # Edges
            org_to_shape_edge_label = "biolink:has_phenotype" #  [org_name -> cell_shape, metabolism]
            org_to_shape_edge_relation = "RO:0002200" #  [org_name -> cell_shape, metabolism]
            org_to_chem_edge_label = "biolink:produces" # [org_name -> carbon_substrate]
            org_to_chem_edge_relation = "RO:0003000" # [org_name -> carbon_substrate]
            org_to_source_edge_label = "biolink:EnvironmentalFeature"# [org -> isolation_source]
            org_to_source_edge_relation = "ENVO:01000254"

            
            
            # transform
            for line in f:
                """
                This dataset is a csv and also has commas 
                present within a column of data. 
                Hence a regex solution
                """
                # transform line into nodes and edges
                # node.write(this_node1)
                # node.write(this_node2)
                # edge.write(this_edge)
                

                line = re.sub(r'(?!(([^"]*"){2})*[^"]*$),', '|', line) # alanine, glucose -> alanine| glucose
                items_dict = parse_line(line, header_items, sep=',')

                #nodesExtract = extract_nodes(items_dict, self.node_header)

                org_name = items_dict['org_name']
                tax_id = items_dict['tax_id']
                strain = items_dict['Strain']
                metabolism = items_dict['metabolism']
                carbon_substrates = set([x.strip() for x in items_dict['carbon_substrates'].split('|')])
                cell_shape = items_dict['cell_shape']
                isolation_source = set([x.strip() for x in items_dict['isolation_source'].split('|')])
                reference = items_dict['reference']
                curie = "NEED-CURIE"

            # Write Node ['id', 'entity', 'category', 'reference', 'ref_type']
                # Write organism node 
                org_id = org_prefix + str(tax_id)
                if org_id not in seen_organism:
                    write_node_edge_item(fh=node,
                                         header=self.node_header,
                                         data=[org_id,
                                               org_name,
                                               org_node_type,
                                               reference,
                                               curie])
                    seen_organism[tax_id] += 1

                # Write chemical node
                for chem_name in carbon_substrates:
                    chem_id = chem_prefix + chem_name.lower().replace(' ','_')
                    if chem_id not in seen_carbon_substrate:
                        write_node_edge_item(fh=node,
                                            header=self.node_header,
                                            data=[chem_id, # NEEDS TO BE UPDATED
                                                chem_name,
                                                chem_node_type,
                                                reference,
                                                curie])
                        seen_carbon_substrate[chem_id] += 1

                # Write shape node
                shape_id = shape_prefix + cell_shape
                if shape_id not in seen_shape:
                    write_node_edge_item(fh=node,
                                         header=self.node_header,
                                         data=[shape_id,
                                               cell_shape,
                                               shape_node_type,
                                               reference,
                                               curie])
                    seen_shape[shape_id] += 1

                # Write source node
                for source_name in isolation_source:
                    source_id = source_prefix + source_name.lower().replace(' ','_')
                    if source_id not in seen_isolation_source:
                        write_node_edge_item(fh=node,
                                            header=self.node_header,
                                            data=[source_id, # NEEDS TO BE UPDATED
                                                source_name,
                                                source_node_type,
                                                reference,
                                                curie])
                        seen_isolation_source[source_id] += 1

                


            # Write Edge
                # org-chem edge
                write_node_edge_item(fh=edge,
                                         header=self.edge_header,
                                         data=[org_id,
                                               org_to_chem_edge_label,
                                               chem_id,
                                               org_to_chem_edge_relation,
                                               reference,
                                               curie])
                # org-shape edge
                write_node_edge_item(fh=edge,
                                         header=self.edge_header,
                                         data=[org_id,
                                               org_to_shape_edge_label,
                                               shape_id,
                                               org_to_shape_edge_relation,
                                               reference,
                                               curie])
                
                # org-source edge
                write_node_edge_item(fh=edge,
                                         header=self.edge_header,
                                         data=[org_id,
                                               org_to_source_edge_label,
                                               source_id,
                                               org_to_source_edge_relation,
                                               reference,
                                               curie])
                #pdb.set_trace()
                #pdb.set_trace = lambda:None
        return None