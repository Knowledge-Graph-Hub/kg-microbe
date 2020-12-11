import os
import shutil
from typing import Optional
import yaml


class Transform:
    """Parent class for transforms, that sets up a lot of default file info
    """

    DEFAULT_INPUT_DIR = os.path.join('data', 'raw')
    DEFAULT_OUTPUT_DIR = os.path.join('data', 'transformed')
    # NLP
    DEFAULT_NLP_DIR = os.path.join('data','nlp')
    DEFAULT_NLP_TERMS_DIR = os.path.join(DEFAULT_NLP_DIR,'terms')
    DEFAULT_NLP_INPUT_DIR = os.path.join(DEFAULT_NLP_DIR,'input')
    DEFAULT_NLP_OUTPUT_DIR = os.path.join(DEFAULT_NLP_DIR,'output')
    DEFAULT_NLP_STOPWORDS_DIR = os.path.join(DEFAULT_NLP_DIR, 'stopwords')
    

    def __init__(self, source_name, input_dir: str = None, output_dir: str = None, nlp: bool = False):
        # default columns, can be appended to or overwritten as necessary
        self.source_name = source_name
        self.node_header = ['id', 'name', 'category']
        self.edge_header = ['subject', 'edge_label', 'object', 'relation',
                            'provided_by']

        # default dirs
        self.input_base_dir = input_dir if input_dir else self.DEFAULT_INPUT_DIR
        self.output_base_dir = output_dir if output_dir else self.DEFAULT_OUTPUT_DIR
        self.output_dir = os.path.join(self.output_base_dir, source_name)
        
        
        

        # default filenames
        self.output_node_file = os.path.join(self.output_dir, "nodes.tsv")
        self.output_edge_file = os.path.join(self.output_dir, "edges.tsv")
        self.output_json_file = os.path.join(self.output_dir, "nodes_edges.json")
        self.subset_terms_file = os.path.join(self.input_base_dir,"subset_terms.tsv")
        
        os.makedirs(self.output_dir, exist_ok=True)

        if nlp:
            
            self.nlp_dir = self.DEFAULT_NLP_DIR
            self.nlp_input_dir = self.DEFAULT_NLP_INPUT_DIR
            self.nlp_output_dir = self.DEFAULT_NLP_OUTPUT_DIR
            self.nlp_terms_dir = self.DEFAULT_NLP_TERMS_DIR
            self.nlp_stopwords_dir = self.DEFAULT_NLP_STOPWORDS_DIR

            # Delete previously developed files
            if os.path.exists(self.nlp_input_dir):
                shutil.rmtree(self.nlp_input_dir)
                shutil.rmtree(self.nlp_stopwords_dir)

            
            os.makedirs(self.nlp_dir,exist_ok=True)
            os.makedirs(self.nlp_input_dir, exist_ok=True)
            os.makedirs(self.nlp_output_dir, exist_ok=True)
            os.makedirs(self.nlp_terms_dir, exist_ok=True)
            os.makedirs(self.nlp_stopwords_dir, exist_ok=True)

            with open('stopwords.yaml', 'r') as stop_list:
                doc = yaml.load(stop_list, Loader=yaml.FullLoader)
                stop_words =  doc['English']
                
            with open(os.path.join(self.nlp_stopwords_dir,'stopWords.txt'), 'w') as stop_terms:
                #stop_terms.write(stop_words)
                for word in stop_words.split(' '):
                    stop_terms.write(word + '\n')


            self.output_nlp_file = os.path.join(self.nlp_output_dir, "nlpOutput.tsv")


            


    def run(self, data_file: Optional[str] = None):
        pass
