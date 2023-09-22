


from tqdm import tqdm
import pandas as pd
import argparse
from collections import defaultdict 



def process_kg_covid19_files(triples_file,labels_file):
    triples_df = pd.read_csv(triples_file,sep = '\t', usecols = ['subject', 'object', 'predicate'])
    triples_df.columns.str.lower()

    labels = pd.read_csv(labels_file, sep = '\t', usecols = ['id','category', 'name','description'])

    triples_df_relevant = triples_df.loc[((triples_df['subject'].str.contains('MONDO:')) & (triples_df['object'].str.contains('GO:'))) | ((triples_df['object'].str.contains('MONDO:')) & (triples_df['subject'].str.contains('GO:')))]

    labels_relevant = labels.loc[(labels['id'].str.contains('MONDO:')) | (labels['id'].str.contains('GO:')) | (labels['id'].str.contains('CHEBI:')) | (labels['id'].str.contains('NCBITaxon:'))]
    
    #1785727 total, 435 total MONDO/GO or GO/MONDO relationships
    print(len(labels_relevant),len(labels))
    
    return triples_df_relevant,labels_relevant

def get_process_disease_phenio_data(triples_file,labels_file,process_ids):

    print('Extracting kg-phenio relationships')
    triples_df, labels_dict = process_kg_covid19_files(triples_file,labels_file)

    #triples_df = triples_df.replace(regex=['http://purl.obolibrary.org/obo/'],value='').replace(regex=['_'],value=':')
    
    rels = []

    for i in tqdm(range(len(triples_df))):
        if triples_df.iloc[i].loc['object'] in process_ids and 'MONDO:' in triples_df.iloc[i].loc['subject']:
        #if ('GO_' in triples_df.iloc[i].loc['subject'] and 'MONDO_' in triples_df.iloc[i].loc['object']) or ('GO_' in triples_df.iloc[i].loc['object'] and 'MONDO_' in triples_df.iloc[i].loc['subject']):
            print(triples_df.iloc[i])
            rels.append([triples_df.iloc[i].loc['subject'], triples_df.iloc[i].loc['predicate'],
                                    triples_df.iloc[i].loc['object'],
                                    {'source': 'kg-phenio'}])

    return rels

#Define arguments for each required and optional input
def defineArguments():
    parser=argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("--directory",dest="Directory",required=True,help="Directory")

    return parser

def main():

    #directory = '/Users/brooksantangelo/Documents/HunterLab/Exploration/biochem4j/kg-microbe/metanetx_uniprot/refProteome/LocalRun_0915'

    #Generate argument parser and define arguments
    parser = defineArguments()
    args = parser.parse_args()
    
    directory = args.Directory

    phenio_labels_file = '/Users/brooksantangelo/Documents/HunterLab/Exploration/kg-phenio/phenio_merged-kg_nodes.tsv'
    phenio_triples_file = '/Users/brooksantangelo/Documents/HunterLab/Exploration/kg-phenio/phenio_merged-kg_edges.tsv'

    #Updated 6/19 based on file location
    kg_covid19_triples_file = '/Users/brooksantangelo/Documents/HunterLab/Cartoomics/PostRevisionUpdates/Inputs/kg-covid19/merged-kg_edges.tsv'
    kg_covid19_labels_file = '/Users/brooksantangelo/Documents/HunterLab/Cartoomics/PostRevisionUpdates/Inputs/kg-covid19/merged-kg_nodes.tsv'

    enzyme_file = directory + '/nodes' + '/Enzyme.csv' 

    kg_filename = directory + '/rels' + '/combined_kg.csv' 

    kg = pd.read_csv(kg_filename,delimiter='\t')
    kg = kg[['subject','object']]
    kg_vals = pd.unique(kg[['subject', 'object']].values.ravel()).tolist()
    kg_vals = [str(x) for x in kg_vals]

    kg_labels = {}

    phenio_triples,phenio_labels = process_kg_covid19_files(phenio_triples_file,phenio_labels_file)
    covid19_triples,covid19_labels = process_kg_covid19_files(kg_covid19_triples_file,kg_covid19_labels_file)

    enzyme_df = pd.read_csv(enzyme_file,delimiter=';')
    enz_list = []

    #Get uri (ex: O88037) and labels (ex: Probable SapB synthase) for all enzymes 
    print('extracting enzyme labels')
    for i in range(len(enzyme_df)):
        enz_list.append({'id': 'Uniprot:'+enzyme_df.iloc[i].loc['uniprot:ID(Enzyme)'] ,
                   'category': 'biolink:Protein' ,
                   'name': enzyme_df.iloc[i].loc['names'],
                   'description': ''})
        
    enzyme_new_df = pd.DataFrame(enz_list)
    
    kg_list = []
    #Convert all uris that exist in phenio or kg-covid19 to labels
    for i in tqdm(kg_vals):
        #Determine category of node. What if GO term is not biological process?
        if 'NCBITaxon:' in i: cat = 'biolink:OrganismalEntity'
        if 'MONDO:' in i: cat = 'biolink:Disease'
        if 'CHEBI:' in i: cat = 'biolink:ChemicalSubstance'
        if 'GO:' in i: cat = 'biolink:BiologicalProcess'
        try:
            kg_list.append({'id': i ,
                   'category':  cat ,
                   'name': phenio_labels.loc[phenio_labels['id'] == i,'name'].values[0],
                   'description': ''})
        except (KeyError,IndexError):
            #print('val doesnt exist in phenio: ',i)
            pass
        try:
            kg_list.append({'id': i ,
                   'category':  cat ,
                   'name': covid19_labels.loc[covid19_labels['id'] == i,'name'].values[0],
                   'description': ''})
        except (KeyError,IndexError):
            #print('val doesnt exist in kg-covid19: ',i)
            pass

    kg_new_df = pd.DataFrame(kg_list)

    #Combine enzymes df with other labels from phenio and kg-covid19
    combined_nodes = pd.concat([kg_new_df, enzyme_new_df], axis=0)

    #Add Rhea labels:
    rhea_vals = [i for i in kg_vals if 'rhea' in i.lower()]
    rhea_list = []
    #Dictionary to output Rhea nodes in current kg form, not kgx
    rhea_labels = {}
    for i in rhea_vals:
        rhea_list.append({'id': i ,
                   'category':  'biolink:Reaction' ,
                   'name': i,
                   'description': ''})
        rhea_labels[i] = {'id':i, 'label':i}

    #Output Rhea_nodes file
    rhea_kg_df = pd.DataFrame(rhea_labels.values())
    rhea_kg_df.to_csv(directory + '/nodes' + '/Rhea_nodes.csv', index=False, encoding='utf-8', sep=';')

    rhea_new_df = pd.DataFrame(rhea_list)

    #Combine all df label types and output
    combined_nodes = pd.concat([combined_nodes, rhea_new_df], axis=0)
    combined_nodes.to_csv(directory + '/combined_kgx_merged-kg_nodes.csv',sep='\t',index=False)
    

if __name__ == '__main__':
    main()