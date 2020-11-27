#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import configparser
from oger.ctrl.router import Router, PipelineServer
from oger.ctrl.run import run as og_run

import pandas as pd

SETTINGS_FILENAME = 'settings.ini'

def create_settings_file(path: str, ont: str = 'ALL') -> None:
    """
    Creates the settings.ini file for OGER to get parameters.
    -   Parameters: 
        -   path - path of the 'nlp' folder
        -   ont - the ontology to be used as dictionary ['ALL', 'ENVO', 'CHEBI']

    -   The 'Shared' section declares global variables that can be used in other sections
        e.g. Data root.
        root = location of the working directory
        accessed in other sections using => ${Shared:root}/

    -   Input formats accepted:
        txt, txt_json, bioc_xml, bioc_json, conll, pubmed,
        pxml, pxml.gz, pmc, nxml, pubtator, pubtator_fbk,
        becalmabstracts, becalmpatents

    -   Two iter-modes available: [collection or document]
        document:- 'n' input files = 'n' output files
        (provided every file has ontology terms)
        collection:- n input files = 1 output file

    -   Export formats possible:
        tsv, txt, text_tsv, xml, text_xml, bioc_xml,
        bioc_json, bionlp, bionlp.ann, brat, brat.ann,
        conll, pubtator, pubanno_json, pubtator, pubtator_fbk,
        europepmc, europepmc.zip, odin, becalm_tsv, becalm_json
        These can be passed as a list for multiple outputs too.

    -   Multiple Termlists can be declared in separate sections
        e.g. [Termlist1], [Termlist2] ...[Termlistn] with each having
        their own paths



    """
    config = configparser.ConfigParser()
    config['Section'] = {}
    config['Shared'] = {}
    
    # Settings required by OGER
    config['Main'] = {
        'input-directory' : os.path.join(path,'input'),
        'output-directory' : os.path.join(path,'output'),
        'pointer-type' : 'glob',
        'pointers' : '*.tsv',
        'iter-mode' : 'collection',
        'article-format' : 'txt_tsv',
        'export_format': 'tsv'
    }

    if ont == 'ENVO':
        config.set('Main','termlist1_path', os.path.join(path,'terms/envo_termlist.tsv'))
        
    elif ont == 'CHEBI':
        config.set('Main','termlist1_path', os.path.join(path,'terms/chebi_termlist.tsv'))
        
    else:
        config.set('Main', 'termlist1_path', os.path.join(path,'terms/envo_termlist.tsv'))
        config.set('Main', 'termlist2_path', os.path.join(path,'terms/chebi_termlist.tsv'))
    
    # This is how OGER prescribes in it's test file but above works too.
    '''config['Termlist1'] = {
        'path' : os.path.join(path,'terms/envo_termlist.tsv')
    }

    config['Termlist2'] = {
        'path' : os.path.join(path,'terms/chebi_termlist.tsv')
    }'''
    # Write
    with open(os.path.join(path, SETTINGS_FILENAME), 'w') as settings_file:
        config.write(settings_file)

def prep_nlp_input(path: str, columns: list)-> str:
    '''
    Arguments: 
        path - path to the file which has text to be analyzed
        columns - The first column HAS to be an id column.
    '''
    df = pd.read_csv(path, sep=',', low_memory=False, usecols=columns)
    sub_df = df.dropna()
    
    # Hacky way of creating i/p files to run OGER
    '''for idx, row in sub_df.T.iteritems():
        new_file = 'nlp/input/'+str(row[0])+'.txt'
        path_to_new_file = os.path.abspath(os.path.join(os.path.dirname(path),'..',new_file))

        if os.path.exists(path_to_new_file):
            mode = 'a'
        else:
            mode = 'w'

        with open(path_to_new_file, mode) as txt_file:
            txt_file.write(row[1])'''
    # New way of doing this : PR submitted to Ontogene for merging code.
    fn = 'nlp'
    nlp_input = os.path.abspath(os.path.join(os.path.dirname(path),'..','nlp/input/'+fn+'.tsv'))
    sub_df.to_csv(nlp_input, sep='\t', index=False)
    return fn
            


def run_oger(path: str , input_file_name: str , n_workers :int = 1 ) -> pd.DataFrame:
    config = configparser.ConfigParser()
    config.read(os.path.join(path, SETTINGS_FILENAME))
    sections = config._sections
    settings = sections['Main']
    settings['n_workers'] = n_workers
    og_run(**settings)
    df = process_oger_output(path, input_file_name)
    
    return df

def process_oger_output(path: str, input_file_name: str) -> pd.DataFrame:
    """
    The OGER output is a TSV which is imported and only the terms that occurred in the text file
    are considered and a dataframe of relevant information is returned
    """
    cols = ['TaxId', 'Biolink', 'BeginTerm', 'EndTerm', 'TokenizedTerm', 'PreferredTerm', \
            'CURIE', 'NaN1', 'SentenceID', 'NaN2', 'UMLS_CUI']
    df = pd.read_csv(os.path.join(path, 'output',input_file_name+'.tsv'), sep='\t', names=cols)
    sub_df = df[['TaxId', 'Biolink','TokenizedTerm', 'PreferredTerm', 'CURIE']]
    interested_df = sub_df.loc[(df['TokenizedTerm'] == df['PreferredTerm'].str.replace(r"\(.*\)",""))]
    interested_df = interested_df.drop(columns = ['PreferredTerm']).drop_duplicates()
    interested_df.to_csv(os.path.join(path, 'output',input_file_name +'Filtered.tsv'), sep='\t', index=False)
    return interested_df