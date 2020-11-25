import csv
import re
import os
from typing import Dict, List, Optional
from collections import defaultdict

from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils.transform_utils import parse_header, parse_line, write_node_edge_item

import pdb
"""
Ingest environment dataset

Essentially just ingests and transforms this file:
https://github.com/bacteria-archaea-traits/bacteria-archaea-traits/blob/master/data/conversion_tables/environments.csv

And extracts the following columns:
    - Main group
    - Type
    - ENVO_terms
    - ENVO_ids
    - Salinity
    - salinity variability
    - pH
"""

class EnvironmentDataTransform(Transform):
    def __init__(self, input_dir: str = None, output_dir: str = None, nlp: bool = False) -> None:
        source_name = "environments"
        super().__init__(source_name, input_dir, output_dir, nlp)  # set some variables

        self.node_header = ['id', 'entity', 'group', 'envo_term', 'envo_id']
        '''self.edge_header = ['subject', 'edge_label', 'object', 'relation',
                            'reference', 'curie']'''

    def run(self, data_file: Optional[str] = None):
        """Method is called and performs needed transformations to process the 
        Environment data, additional information on this data can be found in the comment 
        at the top of this script"""

        if data_file is None:
            data_file = "environments.csv"
        
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
            #edge.write("\t".join(self.edge_header) + "\n")
            
            header_items = parse_header(f.readline(), sep=',')

            seen_sample_type: dict = defaultdict(int)

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
                

                line = re.sub(r'(?!(([^"]*"){2})*[^"]*$),', '|', line) # ENVO:00001998, ENVO:01000256 => ENVO:00001998| ENVO:01000256
                items_dict = parse_line(line, header_items, sep=',')
                
                group = items_dict['Main group']
                sample_type = items_dict['Type']
                envo_terms = [x.strip() for x in items_dict['ENVO_terms'].split('|')]
                envo_ids = [x.strip() for x in items_dict['ENVO_ids'].split('|')]
                
            # Write Node ['id', 'entity', 'category', 'reference', 'ref_type']
                if len(envo_terms) == len(envo_ids) \
                    and len(envo_ids) > 1:
                    for idx, eId in enumerate(envo_ids):
                        sample_id = sample_type.lower()+'-'+eId
                        if sample_id not in seen_sample_type:
                            write_node_edge_item(fh=node,
                                         header=self.node_header,
                                         data=[sample_id,
                                               sample_type,
                                               group,
                                               envo_terms[idx],
                                               eId])
                            seen_sample_type[sample_id] += 1
        return None
