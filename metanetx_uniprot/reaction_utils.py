'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
from enzyme_utils import EnzymeManager

from numpy import *


class ReactionManager(object):
    '''Class to implement a manager of Reaction data.'''

    def __init__(self):
        '''Constructor.'''
        self.__nodes = {}
        self.__reac_ids = {}
        self.__reac_enz_rels = []
        self.__enz_reac_rels = []
        self.__org_enz_rels = []
        self.__enz_man = EnzymeManager()

    def write_files(self, writer):
        '''Write neo4j import files.'''
        return ([writer.write_nodes(self.__nodes.values(),
                                    'Reaction'),
                 writer.write_nodes(self.__enz_man.get_nodes(),
                                    'Enzyme')],
                [writer.write_rels(self.__reac_enz_rels,
                                   'Reaction', 'Enzyme'),
                #Gets reactions connected to all enzymes
                writer.write_rels(self.__enz_reac_rels,
                                   'Reaction', 'Enzyme'),
                 writer.write_rels(self.__enz_man.get_org_enz_rels(),
                                   'Organism', 'Enzyme')])

    def add_reaction(self, source, reac_id, properties):
        '''Adds a reaction to the collection of nodes, ensuring uniqueness.'''
        reac_id = self.__reac_ids[source + reac_id] \
            if source + reac_id in self.__reac_ids else reac_id

        if reac_id not in self.__nodes:
            properties[':LABEL'] = 'Reaction'
            properties['id:ID(Reaction)'] = reac_id
            properties['source'] = source
            properties[source] = reac_id
            self.__nodes[reac_id] = properties

            if 'mnx' in properties:
                self.__reac_ids['mnx' + properties['mnx']] = reac_id

            if 'kegg.reaction' in properties:
                self.__reac_ids[
                    'kegg.reaction' + properties['kegg.reaction']] = reac_id

            if 'rhea' in properties:
                self.__reac_ids['rhea' + properties['rhea']] = reac_id
        else:
            self.__nodes[reac_id].update(properties)

        return reac_id

    def add_react_to_enz(self, data, source, num_threads=0):
        '''Submit data to the graph.'''
        # Create Reaction and Enzyme nodes:
        enzyme_ids = self.__create_react_enz(data, source)

        # Create Enzyme nodes:
        self.__enz_man.add_uniprot_data(enzyme_ids, source, num_threads) 

    def add_react_to_enz_organism(self, data, source, num_threads=0):

        #Create Reaction relationships
        reaction_ids = self.__create_enz_react(data, source)

        return reaction_ids

    def __create_react_enz(self, data, source):
        '''Creates Reaction and Enzyme nodes and their Relationships.'''
        enzyme_ids = []

        for reac_id, uniprot_ids in data.items():
            reac_id = self.add_reaction(source, reac_id, {})

            for uniprot_id in uniprot_ids:
                enzyme_ids.append(uniprot_id)
                self.__reac_enz_rels.append([reac_id, 'catalysed_by',
                                             uniprot_id,
                                             {'source': source}])

        return list(set(enzyme_ids))

    def __create_enz_react(self, data, source):
        '''Creates Reaction and Enzyme nodes and their Relationships.'''
        print('adding reaction to enzyme relationships')
        reaction_ids = []
        enzyme_ids = self.__enz_man.get_nodes()

        for enz_id in enzyme_ids:
            reac_ids = [key for key, value in data.items() if enz_id['entry'] in value]
            reaction_ids = reaction_ids+reac_ids
            for j in reac_ids:
                self.__enz_reac_rels.append([j, 'catalysed_by',
                                                enz_id['entry'],
                                                {'source': source}])
        return list(set(reaction_ids))

    def add_org_to_enz(self, nodes, source, num_threads=0):
        '''Submit data to the graph.'''
        # Create Organism nodes:
        organism_ids = self.__create_organism_ids(nodes, source)

        ## For testing
        #organism_ids = organism_ids[0:10]

        # Create Organism and Enzyme nodes:
        self.__enz_man.add_uniprot_data_organism(organism_ids, source, num_threads)

    def __create_organism_ids(self, data, source):

        ids = unique(list(data.keys()))

        return ids

