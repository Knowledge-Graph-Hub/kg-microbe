
## Output all taxa IDs that exist in kg-microbe and as reference proteomes in UniProt.


import os
import sys
import tarfile
import tempfile
import urllib
from urllib.request import urlretrieve

from kgx.cli.cli_utils import transform
import pandas as pd
from seq_utils import _get_uniprot_batch_reference_proteome

import utils, seq_utils


__NCBITAXONOMY_URL = 'ftp://ftp.ncbi.nih.gov/pub/taxonomy/taxdump.tar.gz'

__UNIPROT_REFERENCE_PROTEOMES_URL = 'https://rest.uniprot.org/proteomes/search?&format=tsv&query=%28%28taxonomy_id%3A2%29%20OR%20%28taxonomy_id%3A2157%29%29%20AND%20%28proteome_type%3A1%29&size=500'

def build_csv(dest_dir, num_threads):
    #'''Build database CSV files.'''
<<<<<<< HEAD
=======
    #writer = utils.Writer(dest_dir)
>>>>>>> 79638d7925b65aea0f3e96bf5441ae4a883cfbb0

    # Get Organism data:
    print('Parsing NCBI Taxonomy')
    load(dest_dir) #--> writes Organism_Enzyme.tsv



def load(output_dir, source=__NCBITAXONOMY_URL, ref_source=__UNIPROT_REFERENCE_PROTEOMES_URL):
    '''Loads NCBI Taxonomy data.'''
    #To get data directly from NCBI Taxon
    #nodes_filename, names_filename = _get_ncbi_taxonomy_files(source)
    #nodes, rels = _parse_nodes(nodes_filename, array_delimiter)
    #_parse_names(nodes, names_filename, array_delimiter)
    #######
    #To get data from kg-microbe
<<<<<<< HEAD
    nodes_filename = os.getcwd()+'/Files/ncbitaxon_nodes.tsv'     #ncbitaxon.json
    #For testing
    #nodes_filename = os.getcwd()+'/TestingFiles/ncbitaxon.json'
    print('parsing ncbi taxon tsv file') #json
    #_parse_nodes_kgmicrobe only used if reading ncbitaxon.json
    #kgx_nodes_file = _parse_nodes_kgmicrobe(nodes_filename,'ncbitaxon_transformed',output_dir)
    print('length of ncbitaxon_nodes.tsv: ',len(pd.read_csv(nodes_filename,sep='\t')))  #kgx_nodes))

    #Update to kgx_nodes_file if ncbitaxon.json is input
    nodes,nodes_df = transform_kgx_output_format(nodes_filename)  #kgx_nodes_file)
=======
    nodes_filename = os.getcwd()+'/Files/ncbitaxon.json'
    #For testing
    #nodes_filename = os.getcwd()+'/TestingFiles/ncbitaxon.json'
    print('parsing ncbi taxon json file')
    kgx_nodes_json = _parse_nodes_kgmicrobe(nodes_filename,'ncbitaxon_transformed',output_dir)

    nodes,nodes_df = transform_kgx_output_format(kgx_nodes_json)
>>>>>>> 79638d7925b65aea0f3e96bf5441ae4a883cfbb0

    #Constrain by those that have reference proteomes, don't use if testing
    ref_organisms = _get_uniprot_batch_reference_proteome(ref_source)
    ref_organism_ids = [str(k['Organism Id']) for k in ref_organisms]
    node_vals = [i for i in nodes if i in ref_organism_ids]

<<<<<<< HEAD
    nodes_not_in_refProteome = list(set(ref_organism_ids) - set(nodes))
    print('nodes_not_in_refProteome: ',nodes_not_in_refProteome)

    node_vals = ['NCBITaxon:' + i for i in node_vals]
    kgx_nodes_subset = nodes_df[nodes_df['id'].isin(node_vals)]
    kgx_nodes_subset.to_csv(output_dir+'/Organism.tsv', index=False, sep='\t')
=======
    node_vals = ['NCBITaxon:' + i for i in node_vals]
    kgx_nodes_json_subset = nodes_df[nodes_df['id'].isin(node_vals)]
    kgx_nodes_json_subset.to_csv(output_dir+'/Organism.tsv', index=False, sep='\t')
>>>>>>> 79638d7925b65aea0f3e96bf5441ae4a883cfbb0
    print('Wrote file: ',output_dir+'/Organism.tsv')

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

def _parse_nodes_kgmicrobe(filename, output_name,output_dir):
    '''Parses nodes file.'''
    
<<<<<<< HEAD
    transform(inputs=[filename], input_format='tsv', output= os.path.join(output_dir, output_name), output_format='tsv') #obojson
=======
    transform(inputs=[filename], input_format='obojson', output= os.path.join(output_dir, output_name), output_format='tsv')
>>>>>>> 79638d7925b65aea0f3e96bf5441ae4a883cfbb0

    return output_dir+'/'+output_name+'_nodes.tsv'
    
def transform_kgx_output_format(transformed_nodes_tsv):

    labels = pd.read_csv(transformed_nodes_tsv, sep = '\t', usecols = ['id','name'])

    nodes = []

    #Get node IDs to help subset according to reference proteomes
    for i in range(len(labels)):
<<<<<<< HEAD
        try:
            tax_id = labels.iloc[i].loc['id'].split('NCBITaxon:')[1]
            nodes.append(tax_id)
        except IndexError: print(labels.iloc[i].loc['id'])
=======
        tax_id = labels.iloc[i].loc['id'].split('NCBITaxon:')[1]
        nodes.append(tax_id)
>>>>>>> 79638d7925b65aea0f3e96bf5441ae4a883cfbb0

    return nodes,labels


def _parse_nodes(filename):
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
                             'Organism' + ',' + tokens[2]}

    return nodes, rels


def _parse_names(nodes, filename):
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
                ','.join(node['names:string[]'])


def main(args):
    '''main method'''
    num_threads = 0

    if len(args) > 2:
        try:
            num_threads = int(args[2])
        except ValueError:
            if args[2] == 'True':
                num_threads = multiprocessing.cpu_count()

    print('Running build with ' + str(num_threads) + ' threads')

    build_csv(args[0], num_threads)




if __name__ == '__main__':
    main(sys.argv[1:])