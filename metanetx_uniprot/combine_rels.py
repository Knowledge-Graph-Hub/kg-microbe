import os
import pandas as pd
import argparse


def parse_kg_file(kg_filename):

    kg = pd.read_csv(kg_filename,delimiter=';')

    if len(kg.columns) == 3: kg.columns = [['subject','predicate','object']]
    if len(kg.columns) == 4:
        kg.columns = [['subject','predicate','object','source']]
        kg = kg[['subject','predicate','object']]

    return kg

def concat_kgs(kg1,kg2):

    combined_kg = pd.concat([kg1, kg2], axis=0)
    combined_kg = combined_kg.drop_duplicates().reset_index(drop=True)

    return combined_kg

#Define arguments for each required and optional input
def defineArguments():
    parser=argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("--directory",dest="Directory",required=True,help="Directory")

    return parser

def main():

    #rels_files_dir = '/Users/brooksantangelo/Documents/HunterLab/Exploration/biochem4j/kg-microbe/metanetx_uniprot/refProteome/LocalRun_0915

    #Generate argument parser and define arguments
    parser = defineArguments()
    args = parser.parse_args()
    
    directory = args.Directory

    rels_files_dir = directory+'/rels/'
    rels_files = os.listdir(rels_files_dir)

    rels_files = [i for i in rels_files if 'combined_kg' not in i]

    kg_0 = parse_kg_file(rels_files_dir+rels_files[0])

    for fname in rels_files[1:]:

        if fname.endswith('.csv'):

            kg = parse_kg_file(rels_files_dir+fname)
            kg_0 = concat_kgs(kg_0,kg)

    kg_0.to_csv(rels_files_dir + 'combined_kg.csv', sep = "\t", index = False)


if __name__ == '__main__':
    main()


    

