'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
import os
import sys
import tarfile
import tempfile
import urllib
from urllib.request import urlretrieve

from kgx.cli.cli_utils import transform
import pandas as pd


__NCBITAXONOMY_URL = 'ftp://ftp.ncbi.nih.gov/pub/taxonomy/taxdump.tar.gz'


def load(reaction_manager, writer, array_delimiter, source=__NCBITAXONOMY_URL):
    '''Loads NCBI Taxonomy data.'''
    #Not used currently
    #nodes_filename, names_filename = _get_ncbi_taxonomy_files(source)
    #nodes, rels = _parse_nodes(nodes_filename, array_delimiter)
    #_parse_names(nodes, names_filename, array_delimiter)
    #######
    nodes_filename = os.getcwd()+'/Files/ncbitaxon.json'
    #nodes_filename = os.getcwd()+'/TestingFiles/ncbitaxon.json'
    print('parsing ncbi taxon json file')
    kgx_nodes_json,kgx_edges_json = _parse_nodes_kgmicrobe(nodes_filename, array_delimiter)
    nodes,rels = transform_kgx_output_format(kgx_nodes_json,kgx_edges_json)

    writer.write_nodes(nodes.values(), 'Organism')
    writer.write_rels(rels, 'Organism', 'Organism')

    print('adding organism-enzyme relationships')
    reaction_manager.add_org_to_enz(nodes, 'uniprot')


def _get_ncbi_taxonomy_files(source):
    '''Downloads and extracts NCBI Taxonomy files.'''
    temp_dir = tempfile.gettempdir()
    temp_gzipfile = tempfile.NamedTemporaryFile()
    urlretrieve(source, temp_gzipfile.name)

    temp_tarfile = tarfile.open(temp_gzipfile.name, 'r:gz')
    temp_tarfile.extractall(temp_dir)

    temp_gzipfile.close()
    temp_tarfile.close()

    return os.path.join(temp_dir, 'nodes.dmp'), \
        os.path.join(temp_dir, 'names.dmp')

def _parse_nodes_kgmicrobe(filename, array_delimiter):
    '''Parses nodes file.'''

    output_dir = '/Users/brooksantangelo/Documents/HunterLab/biochem4j/biochem4j/'
    name = 'ncbitaxon_transformed'
    
    transform(inputs=[filename], input_format='obojson', output= os.path.join(output_dir, name), output_format='tsv')

    return output_dir+name+'_nodes.tsv',output_dir+name+'_edges.tsv'
    
def transform_kgx_output_format(transformed_nodes_tsv,transformed_edges_tsv):

    labels = pd.read_csv(transformed_nodes_tsv, sep = '\t', usecols = ['id','name'])
    triples_df = pd.read_csv(transformed_edges_tsv,sep = '\t', usecols = ['subject', 'object', 'predicate'])
    triples_df.columns.str.lower()

    nodes = {}
    rels = []

    for i in range(len(labels)):
        tax_id = labels.iloc[i].loc['id'].split('NCBITaxon:')[1]
        nodes[tax_id] = {'taxonomy:ID(Organism)': tax_id,
                             ':LABEL':
                             'Organism,unknown'}

    for i in range(len(triples_df)):
        s = triples_df.iloc[i].loc['subject']
        p = triples_df.iloc[i].loc['predicate']
        o = triples_df.iloc[i].loc['object']
        rels.append([s, p, o])

    return nodes,rels


def _parse_nodes(filename, array_delimiter):
    '''Parses nodes file.'''
    nodes = {}
    rels = []

    with open(filename, 'r') as textfile:
        for line in textfile:
            tokens = [x.strip() for x in line.split('|')]
            tax_id = tokens[0]

            if tax_id != '1':
                rels.append([tax_id, 'is_a', tokens[1]])

            nodes[tax_id] = {'taxonomy:ID(Organism)': tax_id,
                             ':LABEL':
                             'Organism' + array_delimiter + tokens[2]}

    return nodes, rels


def _parse_names(nodes, filename, array_delimiter):
    '''Parses names file.'''

    with open(filename, 'r') as textfile:
        for line in textfile:
            tokens = [x.strip() for x in line.split('|')]
            node = nodes[tokens[0]]

            if 'name' not in node:
                node['name'] = tokens[1]
                node['names:string[]'] = set([node['name']])
            else:
                node['names:string[]'].add(tokens[1])

    for _, node in nodes.items():
        if 'names:string[]' in node:
            node['names:string[]'] = \
                array_delimiter.join(node['names:string[]'])



def main(argv):
    '''main method'''
    load(*argv)


if __name__ == "__main__":
    main(sys.argv[1:])
