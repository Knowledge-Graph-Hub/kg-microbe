'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
from enzyme_utils import EnzymeManager

from numpy import *
import pandas as pd
from tqdm import tqdm
import csv


class ReactionManager(object):
    '''Class to implement a manager of Reaction data.'''

    def __init__(self):
        '''Constructor.'''
        self.__nodes = {}
        self.__reac_ids = {}
        self.__reac_enz_rels = []
        self.__enz_reac_rels = []
        self.__go_reac_rels = []
        self.__org_enz_rels = []
        self.__enz_man = EnzymeManager()

    def write_files(self, writer):
        '''Write neo4j import files.'''
        return ([writer.write_nodes(self.__nodes.values(),
                                    'Reaction'),
                 writer.write_nodes(self.__enz_man.get_nodes(),
                                    'Enzyme'),
                 writer.write_nodes(self.__enz_man.get_enz_nodes(),
                                    'Enzyme_nodes')],
                [writer.write_rels(self.__reac_enz_rels,
                                   'Reaction', 'Enzyme'),
                #Gets reactions connected to all enzymes
                writer.write_rels(self.__enz_reac_rels,
                                   'Reaction', 'Enzyme'),
                #Gets reactions connected to all go processes
                writer.write_rels(self.__go_reac_rels,
                                   'Reaction', 'Process'),
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

        print('from add_reaction in reaction_utils.py')
        print(self.__nodes.values())

        return reac_id

    def add_react_to_enz(self, data, source, num_threads=0):
        '''Submit data to the graph.'''
        # Create Reaction and Enzyme nodes:
        enzyme_ids = self.__create_react_enz(data, source)

        # Create Enzyme nodes:
        self.__enz_man.add_uniprot_data(enzyme_ids, source, num_threads) 

    #data here is rhea-enzyme file, go_data is rhea-go file
    def add_react_to_enz_organism(self, data, source, go_data, num_threads=0):

        #Create Reaction relationships
        reaction_ids,process_ids = self.__create_enz_react(data, go_data, source)

        return reaction_ids,process_ids

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

    def __create_enz_react(self, data, go_data, source):
        '''Creates Reaction and Enzyme nodes and their Relationships.'''
        print('adding reaction to enzyme relationships')
        reaction_ids = []
        process_ids = []
        enzyme_ids = self.__enz_man.get_nodes()

        for enz_id in enzyme_ids:
            #Gets relationships between reactions and enzymes from Rhea only if they exist in the enzymes pulled from organism filtering step
            reac_ids = [key for key, value in data.items() if enz_id['entry'] in value]
            
            reaction_ids = reaction_ids+reac_ids
            for j in reac_ids:
                #reac_ids should have rhea to help identify and protein should have UniProt
                self.__enz_reac_rels.append(['Rhea:'+j, 'catalysed_by',
                                                'Uniprot:'+enz_id['entry'],
                                                {'source': source}])

        print('adding reaction to process relationships')
        #Gets relationships between reactions and Go processes from Rhea only if they exist in above reaction ids
        go_reac_ids = [key for key, value in go_data.items() if key in reaction_ids]
        reaction_ids = reaction_ids+go_reac_ids

        for j in go_reac_ids:
            rxns = go_data[j]
            for k in rxns:
                process_ids.append(k)
                #reac_ids should have rhea to help identify
                self.__go_reac_rels.append(['Rhea:'+j, 'affects',
                                                k,
                                                {'source': source}])

        return list(set(reaction_ids)),list(set(process_ids))

    def add_org_to_enz(self, nodes, source, num_threads=0):
        '''Submit data to the graph.'''
        # Create Organism nodes:
        organism_ids = self.__create_organism_ids(nodes, source)

        print('number of orgs for just reference proteomes')
        print(len(organism_ids))

        ## For testing
        #organism_ids = organism_ids[0:10]

        # Create Organism and Enzyme nodes:
        self.__enz_man.add_uniprot_data_organism(organism_ids, source, num_threads)

    def __create_organism_ids(self, data, source):

        ids = unique(list(data.keys()))

        return ids

    def read_go_plus(self,go_plus_file,process_ids,chemical_ids):
        '''Read chemical properties and create Nodes.'''
        go_keys = ['Class ID', 'Preferred Label', 'Synonyms','Definitions','Obsolete','CUI','Semantic Types','Parents']

        rels = []
        
        d = pd.read_csv(go_plus_file, delimiter=',',keep_default_na=False)
        go_data = d[go_keys]
        go_data = go_data.replace(regex=['http://purl.obolibrary.org/obo/'],value='').replace(regex=['_'],value=':')

        #Create go-plus nodes
        #add to nodes: http://www.w3.org/2000/01/rdf-schema#label
        
        d = d.drop(go_keys,axis=1)  #+['Parents'], axis=1)
        #Update values
        #Ensure subject is not deprecated
        d = d[d['http://www.w3.org/2002/07/owl#deprecated'] != 'TRUE']
        d = d.replace(regex=['http://purl.obolibrary.org/obo/'],value='').replace(regex=['_'],value=':')
        d = d.replace(regex=['go#'],value='')
        
        #Update columns
        #Columns to ignore
        cols_to_drop = ['http://data.bioontology.org/metadata/prefixIRI','http://data.bioontology.org/metadata/treeView','go#','http://purl.obolibrary.org/obo/IAO_','http://www.w3.org/2000/01/rdf-schema#','http://www.w3.org/2004/02/skos/core#','http://www.w3.org/2002/07/owl#deprecated','http://www.w3.org/2000/01/rdf-schema#label','http://purl.org/dc/terms/','obsolete ','has_narrow_synonym','has_obo_format_version','has_obo_namespace','has_related_synonym','has_scope','has_synonym_type','definition','http://www.geneontology.org/formats/oboInOwl#id','has_alternative_id','http://purl.obolibrary.org/obo/go#creation_date','http://www.geneontology.org/formats/oboInOwl#creation_date','synonym_type_property','Systematic synonym','temporally related to','term replaced by','term tracker item','title','http://www.geneontology.org/formats/oboInOwl#created_by','has_exact_synonym']
        cols_to_drop = d.columns[d.columns.str.contains('|'.join(cols_to_drop))]
        d = d.drop(cols_to_drop, axis=1)
        #There are 2 contains relationships, develops_from
        d.columns = d.columns.str.replace('http://data.bioontology.org/metadata/obo/contains','biontology_contains', regex=False)
        d.columns = d.columns.str.replace('http://data.bioontology.org/metadata/obo/develops_from','biontology_develops_from', regex=False)
        d.columns = d.columns.str.replace('http://data.bioontology.org/metadata/obo/','', regex=False)
        d.columns = d.columns.str.replace('http://purl.obolibrary.org/obo/', '', regex=False)
        d.columns = d.columns.str.replace('http://www.geneontology.org/formats/oboInOwl#', '', regex=False)
        
        for i in tqdm(range(len(d))):
            s_id = go_data.iloc[i].loc['Class ID']
            for p_label in d.columns:
                if d.iloc[i].loc[p_label] != '':
                    if (s_id in chemical_ids or p_label in process_ids) or (s_id in process_ids or p_label in chemical_ids):
                        all_objects = d.iloc[i].loc[p_label].split('|')
                        for j in all_objects:
                            rels.append([s_id, p_label,
                                                j,
                                                {'source': 'go-plus'}])
        
        go_process_ids = []
        for i, v in enumerate(rels):
            for x in v:
                if "GO:" in x:
                    go_process_ids.append(x)

        go_process_ids = list(set(go_process_ids))

        print('len process_ids before adding go plus terms: ',len(process_ids))
        process_ids = process_ids+go_process_ids
        process_ids = list(set(process_ids))
        print('len process_ids after adding go plus terms: ',len(process_ids))

        return rels,process_ids

    def transform_kgx_output_format_hp(self,transformed_nodes_tsv,transformed_edges_tsv):

        labels = pd.read_csv(transformed_nodes_tsv, sep = '\t', usecols = ['id','name'])
        triples_df = pd.read_csv(transformed_edges_tsv,sep = '\t', usecols = ['subject', 'object', 'predicate'])
        triples_df.columns.str.lower()

        nodes = {}
        rels = []


        #Constrain rels and nodes to only GO process: HP relationships
        #Constrain rels and nodes to only GO processes that are used in prior rels
        for i in range(len(triples_df)):
            s = triples_df.iloc[i].loc['subject']
            p = triples_df.iloc[i].loc['predicate']
            o = triples_df.iloc[i].loc['object']
            if ('GO:' in s and 'HP:' in o) or ('GO:' in o and 'HP:' in s):
                rels.append([s, p, o])


        for i in range(len(labels)):
            if any(labels.iloc[i].loc['id'] in sublist for sublist in labels):
                nodes[labels.iloc[i].loc['id']] = {'class:ID': labels.iloc[i].loc['id'],
                                    ':LABEL':
                                    labels.iloc[i].loc['id'].split(':')[0]}

        return nodes,rels

    def process_pkl_files(self,triples_file,labels_file):
    
        triples_df = pd.read_csv(triples_file,sep = '	', quoting=csv.QUOTE_NONE)
        triples_df.columns.str.lower()

        triples_df.replace({'<': ''}, regex=True, inplace=True)
        triples_df.replace({'>': ''}, regex=True, inplace=True)

        labels = pd.read_csv(labels_file, sep = '	', quoting=csv.QUOTE_NONE)
        labels.columns.str.lower()

        #Remove brackets from URI
        labels['entity_uri'] = labels['entity_uri'].str.replace("<","")
        labels['entity_uri'] = labels['entity_uri'].str.replace(">","")


        return triples_df,labels

    def get_process_disease_pkl_data(self,triples_file,labels_file,process_ids):

        print('Extracting PKL relationships')
        triples_df, labels_dict = self.process_pkl_files(triples_file,labels_file)

        rels = []

        for i in tqdm(range(len(triples_df))):
            if triples_df.iloc[i].loc['object'] in process_ids and 'MONDO_' in triples_df.iloc[i].loc['subject']:
                rels.append([triples_df.iloc[i].loc['subject'].replace('http://purl.obolibrary.org/obo/','').replace('_',':'), labels_dict.loc[labels_dict['entity_uri'] == triples_df.iloc[i].loc['predicate'],'label'].values[0],
                                        triples_df.iloc[i].loc['object'].replace('http://purl.obolibrary.org/obo/','').replace('_',':'),
                                        {'source': 'pheknowlator'}])

        return rels


    def process_kg_phenio_files(self,triples_file,labels_file):

        triples_df = pd.read_csv(triples_file,sep = '\t', usecols = ['subject', 'object', 'predicate'])
        triples_df.columns.str.lower()

        labels = pd.read_csv(labels_file, sep = '\t', usecols = ['id','category', 'name','description'])
        labels.columns = ['entity_uri','category', 'label','description/definition']

        triples_df_relevant = triples_df.loc[((triples_df['subject'].str.contains('MONDO:')) & (triples_df['object'].str.contains('GO:'))) | ((triples_df['object'].str.contains('MONDO:')) & (triples_df['subject'].str.contains('GO:')))]
        
        #1785727 total, 435 total MONDO/GO or GO/MONDO relationships
        print(len(triples_df),len(triples_df_relevant))
        
        return triples_df_relevant,labels

    def get_process_disease_phenio_data(self,triples_file,labels_file,process_ids):

        print('Extracting kg-phenio relationships')
        triples_df, labels_dict = self.process_kg_phenio_files(triples_file,labels_file)

        rels = []

        for i in tqdm(range(len(triples_df))):
            if triples_df.iloc[i].loc['object'] in process_ids and 'MONDO:' in triples_df.iloc[i].loc['subject']:
                rels.append([triples_df.iloc[i].loc['subject'], triples_df.iloc[i].loc['predicate'],
                                        triples_df.iloc[i].loc['object'],
                                        {'source': 'kg-phenio'}])

        return rels