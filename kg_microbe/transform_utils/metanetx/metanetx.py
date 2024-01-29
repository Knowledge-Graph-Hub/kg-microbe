from collections import Counter
import csv
import itertools
import math
import re
import urllib
from urllib.request import urlopen
import requests

import numpy
#from subliminal import balance

#import namespace_utils
import os 
import pandas as pd
from pathlib import Path
from typing import Optional, Union

from kg_microbe.transform_utils.transform import Transform
from tqdm import tqdm

from kg_microbe.utils.pandas_utils import drop_duplicates

from kg_microbe.transform_utils.constants import (
    REACTION_TO_CHEMICAL_EDGE,
    CARBON_SUBSTRATE_CATEGORY,
    REACTION_CATEGORY
)

#Write out Reaction_Chemical rels, Reaction, Chemical nodes

class MetaNetxTransform(Transform):

    def __init__(self, input_dir: Optional[Path] = None, output_dir: Optional[Path] = None):

        self.__mnx_id_patt = re.compile(r'(MNX[MR])(\d+)')
        self.__chem_data = {}
        self.__reac_data = {}

        source_name = "MetaNetx"
        super().__init__(source_name, input_dir, output_dir)
        

    def run(self, data_file: Union[Optional[Path], Optional[str]] = None):

        '''Loads MnxRef data from chem_prop.tsv, chem_xref.tsv,
        reac_prop.tsv and reac_xref.tsv files.'''

        # make directory in data/transformed
        os.makedirs(self.output_dir, exist_ok=True)

        input_dir = self.input_base_dir
        #Need to update to include all files here
        ####input_file = str(input_dir) + "/chem_prop.tsv"


        #First gets all chemical data from MxnRef (chem_xref and chem_prop) and adds to __chem_man
        self.get_chem_data(input_dir)



        with open(self.output_node_file, "w") as node, open(
            self.output_edge_file, "w"
        ) as edge:
            node_writer = csv.writer(node, delimiter="\t")
            node_writer.writerow(self.node_header)
            edge_writer = csv.writer(edge, delimiter="\t")
            edge_writer.writerow(self.edge_header)
            #with tqdm(total=1000000, desc="Processing files") as progress:

            #Generates __reac_data and __chem_data
            reac_data = self.get_reac_data(input_dir)
            chem_rels = self.__add_reac_nodes(reac_data,edge_writer,node_writer)


        drop_duplicates(self.output_node_file)
        drop_duplicates(self.output_edge_file)
        

    def __add_reac_nodes(self, reac_data,edge_writer,node_writer):
        '''Get reaction nodes from data.'''
        reac_id_def = {}
        #List of reaction ID's added to nodes that are not obsolete
        added_reactions = []
        added_chemicals = []

        for properties in reac_data.values():
            reac_def = []
            try:
                mnx_id = properties.pop('id')
            except KeyError:
                mnx_id = properties.pop('XREF')

            #Returns original id, not metanetx id
            reac_id,added_reactions = self.add_reaction(self.source_name, mnx_id,
                                                   properties,node_writer,added_reactions)

            try:
                for prt in properties.pop('reac_defn'):
                    chem_id, added_chemicals = self.add_chemical({'mnx': prt[0]},node_writer, added_chemicals)

                    reac_def.append(chem_id)
            #Leaving out reactions that do not have formula in reac_prop
            except KeyError:
                continue

            
            reac_id_def[reac_id] = reac_def   

        for reac_id, defn in tqdm(reac_id_def.items()):
            
            for chem in defn:
                if reac_id in added_reactions and chem in added_chemicals:

                    edges_data_to_write = [
                                    reac_id,
                                    REACTION_TO_CHEMICAL_EDGE,
                                    chem,
                                    '',
                                    self.source_name
                                ]

                    edge_writer.writerow(edges_data_to_write)


    def add_reaction(self, source, reac_id, properties,node_writer,added_reactions):

        try:
            r_id = self.__reac_data[reac_id]['reference']
        except KeyError:
            r_id = reac_id
        synonyms = (self.__reac_data[reac_id]['Description']).replace('||','|')

        if 'obsolete' not in synonyms:
            
            nodes_data_to_write = [
                        r_id, REACTION_CATEGORY, r_id,'','',source,synonyms
                        ]

            node_writer.writerow(nodes_data_to_write)
            added_reactions.append(r_id)


        return r_id,added_reactions


    def add_chemical(self, properties, node_writer, added_chemicals):
        '''Adds a chemical to the collection of nodes, ensuring uniqueness.'''
        #Reference ID, not metanetx ID
        mnx_id,chem_id = self.__get_chem_id(properties)

        source = self.source_name
        synonyms = (self.__chem_data[mnx_id]['Description']).replace('||','|')
        try:
            name = self.__chem_data[mnx_id]['name']
        except KeyError:
            name = chem_id

        if 'obsolete' not in synonyms:
            nodes_data_to_write = [
                    chem_id, CARBON_SUBSTRATE_CATEGORY,name,'','',source,synonyms
                    ]

            node_writer.writerow(nodes_data_to_write)
            added_chemicals.append(chem_id)

        return chem_id, added_chemicals

    def get_chem_data(self,input_dir):
        '''Gets chemical data.'''
        if not self.__chem_data:
            self.__read_chem_prop(input_dir)
            self.__read_chem_xref(input_dir)

    def get_reac_data(self,input_dir):
        '''Gets reaction data.'''
        if not self.__reac_data:
            self.__read_reac_prop(input_dir)
            self.__read_reac_xref(input_dir)
        
        return self.__reac_data

    def __read_chem_prop(self,input_dir):
        '''Read chemical properties and create Nodes.'''
        chem_prop_keys = ['id', 'name', 'reference','formula', 'charge:float',
                          'mass:float', 'inchi', 'inchikey', 'smiles']

        input_file = str(input_dir) + "/chem_prop.tsv"
        for values in self.__read_data(input_file):
            #BIOMASS entities represent growth
            if not values[0].startswith('#'):
                values[0] = self.__parse_id(values[0])
                values[2] = self.__parse_id(values[2])
                props = dict(zip(chem_prop_keys, values)) 


                #props.pop('reference')
                _convert_to_float(props, 'charge:float')
                _convert_to_float(props, 'mass:float')
                props = {key: value for key, value in props.items()
                         if value != ''}

                self.__chem_data[values[0]] = props

    def __read_chem_xref(self, input_dir):
        '''Read xrefs and update Nodes.'''
        xref_keys = ['XREF', 'MNX_ID', 'Description']

        input_file = str(input_dir) + "/chem_xref.tsv"

        for values in self.__read_data(input_file):
            if not values[0].startswith('#'):

                xrefs = dict(zip(xref_keys[:len(values)], values))
                self.__chem_data[xrefs['MNX_ID']].update(xrefs)


    def __read_reac_prop(self,input_dir):
        '''Read reaction properties and create Nodes.'''
        reac_prop_keys = ['id', 'equation', 'reference', 'ec', 'balance', 'transport']

        input_file = str(input_dir) + "/reac_prop.tsv"
        for values in self.__read_data(input_file):
            if not values[0].startswith('#'): 
                if values[0] == 'EMPTY': continue
                values[0] = self.__parse_id(values[0])
                values[2] = self.__parse_id(values[2])
                props = dict(zip(reac_prop_keys, values))
                
                try:
                    participants = parse_equation(
                        props.pop('equation'))

                    for participant in participants:
                        participant[0] = self.__parse_id(participant[0])

                        if participant[0] not in self.__chem_data:
                            self.__add_chem(participant[0])
                            
                    props['reac_defn'] = participants
                    self.__reac_data[values[0]] = props
                except ValueError:
                    print('WARNING: Suspected polymerisation reaction: ' + \
                        values[0] + '\t' + str(props))


    def __read_reac_xref(self, input_dir):
        '''Read xrefs and update Nodes.'''
        xref_keys = ['XREF', 'MNX_ID', 'Description']

        input_file = str(input_dir) + "/reac_xref.tsv"

        for values in self.__read_data(input_file):
            if not values[0].startswith('#') and values[0] != 'EMPTY':

                xrefs = dict(zip(xref_keys[:len(values)], values))
                if xrefs['MNX_ID'] != 'EMPTY':
                    self.__reac_data[xrefs['MNX_ID']].update(xrefs)
                elif xrefs['MNX_ID'] == 'EMPTY':
                    self.__reac_data[xrefs['XREF']] = xrefs

    def __add_chem(self, chem_id):
        '''Adds a chemical with given id.'''
        props = {'id': chem_id}
        self.__chem_data[chem_id] = props
        return props

    def __read_data(self, filename):
        '''Reads tab-limited files into lists of lists of
        strings.'''
    
        ###Reads downloaded file for offline testing
        my_list = []
        with open(filename, newline='') as csv_file:
            reader = csv.reader(csv_file, delimiter='\t')
            rows = list(reader)

        return rows

    def __parse_id(self, item_id):
        '''Parses mnx ids.'''
        matches = self.__mnx_id_patt.findall(item_id)

        for mat in matches:
            return mat[0] + str(mat[1]) 

        if 'BIOMASS' in item_id or 'WATER' in item_id:
            return item_id.split('@')[0]

        return item_id

    def __get_chem_id(self, properties):
        '''Manages chemical id mapping.'''
        
        mnx_id = properties.get('mnx')

        new_id = self.__chem_data[mnx_id]['XREF']

        return mnx_id,new_id



def parse_equation(equation, separator='='):
    '''Parses chemical equation strings.'''
    equation_terms = [re.split('\\s+\\+\\s+', equation_side)
                      for equation_side in
                      re.split('\\s*' + separator + '\\s*', equation)]

    # Add reactants and products:
    return _get_reaction_participants(equation_terms[0], -1) + \
        _get_reaction_participants(equation_terms[1], 1)

def _convert_to_float(dictionary, key):
    '''Converts a key value in a dictionary to a float.'''
    if dictionary.get(key, None):
        dictionary[key] = float(dictionary[key] if dictionary[key] != 'NA' else 'NaN')
    else:
        # Remove key:
        dictionary.pop(key, None)


def _get_reaction_participants(equation_term, stoich_factor):
    '''Adds reaction participants to a list of participants.'''
    if len(equation_term) == 1 and not equation_term[0]:
        return []

    all_terms = [participant.split() for participant in equation_term]
    return [[terms[0], stoich_factor]
            if len(terms) == 1
            else [terms[1], stoich_factor * float(terms[0])]
            for terms in all_terms]
