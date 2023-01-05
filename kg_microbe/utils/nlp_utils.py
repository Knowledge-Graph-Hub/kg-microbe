"""Utilities for natural language processing."""

import configparser
import os

import pandas as pd
from kgx.cli.cli_utils import transform
from oger.ctrl.run import run as og_run

from kg_microbe.utils import biohub_converter as bc

SETTINGS_FILENAME = "settings.ini"


def create_settings_file(path: str, ont: str = "ALL") -> None:
    """
    Create the settings.ini file for OGER to get parameters.

    :param path: Path of the 'nlp' folder
    :param ont: The ontology to be used as dictionary ['ALL', 'ENVO', 'CHEBI']
    :return: None.
    -   The 'Shared' section declares global variables that
        can be used in other sections
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
    config["Section"] = {}
    config["Shared"] = {}

    # Settings required by OGER
    config["Main"] = {
        "input-directory": os.path.join(path, "input"),
        "output-directory": os.path.join(path, "output"),
        "pointer-type": "glob",
        "pointers": "*.tsv",
        "iter-mode": "collection",
        "article-format": "txt_tsv",
        "export_format": "tsv",
        "termlist_stopwords": os.path.join(path, "stopwords", "stopwords.txt"),
    }

    if ont == "ENVO":
        config.set(
            "Main", "termlist_path", os.path.join(path, "terms/envo_termlist.tsv")
        )
    elif ont == "CHEBI":
        config.set(
            "Main", "termlist_path", os.path.join(path, "terms/chebi_termlist.tsv")
        )
    elif ont == "ECOCORE":
        config.set(
            "Main", "termlist_path", os.path.join(path, "terms/ecocore_termlist.tsv")
        )
    elif ont == "GO":
        config.set("Main", "termlist_path", os.path.join(path, "terms/go_termlist.tsv"))
    elif ont == "PATO":
        config.set(
            "Main", "termlist_path", os.path.join(path, "terms/pato_termlist.tsv")
        )
    else:
        config.set(
            "Main", "termlist1_path", os.path.join(path, "terms/chebi_termlist.tsv")
        )

    # This is how OGER prescribes in it's test file but above works too.
    """config['Termlist1'] = {
        'path' : os.path.join(path,'terms/envo_termlist.tsv')
    }

    config['Termlist2'] = {
        'path' : os.path.join(path,'terms/chebi_termlist.tsv')
    }"""
    # Write
    with open(os.path.join(path, SETTINGS_FILENAME), "w") as settings_file:
        config.write(settings_file)


def create_termlist(path: str, ont: str) -> None:
    """
    Create termlist.tsv files from ontology JSON files for NLP.

    TODO: Replace this code once runNER is installed and remove
    'kg_microbe/utils/biohub_converter.py'
    """
    ont_int = ont + ".json"

    json_input = os.path.join(path, ont_int)
    tsv_output = os.path.join(path, ont)

    transform(
        inputs=[json_input],
        input_format="obojson",
        output=tsv_output,
        output_format="tsv",
    )

    ont_nodes = os.path.join(path, ont + "_nodes.tsv")
    ont_terms = os.path.abspath(
        os.path.join(
            os.path.dirname(json_input), "..", "nlp/terms/", ont + "_termlist.tsv"
        )
    )
    bc.parse(ont_nodes, ont_terms)


def prep_nlp_input(path: str, columns: list, dic: str) -> str:
    """
    Create a tsv which forms the input for OGER.

    :param path: Path to the file which has text to be analyzed
    :param columns: The first column HAS to be an id column.
    :param dic: The Ontology to be used as a dictionary for NLP
    :return: Filename (str)
    """
    df = pd.read_csv(path, low_memory=False, usecols=columns)
    sub_df = df.dropna()

    if "pathways" in columns:
        sub_df["pathways"] = sub_df["pathways"].str.replace("_", " ")

    # New way of doing this : PR submitted to Ontogene for merging code.
    fn = "nlp" + dic
    nlp_input = os.path.abspath(
        os.path.join(os.path.dirname(path), "..", "nlp/input/" + fn + ".tsv")
    )
    sub_df.to_csv(nlp_input, sep="\t", index=False)
    return fn


def run_oger(path: str, input_file_name: str, n_workers: int = 1) -> pd.DataFrame:
    """
    Run OGER using the settings.ini file created previously.

    :param path: Path of the input file.
    :param input_file_name: Filename.
    :param n_workers: Number of threads to run (default: 1).
    :return: Pandas DataFrame containing the output of OGER analysis.
    """
    config = configparser.ConfigParser()
    config.read(os.path.join(path, SETTINGS_FILENAME))
    sections = config._sections
    settings = sections["Main"]
    settings["n_workers"] = n_workers
    og_run(**settings)
    df = process_oger_output(path, input_file_name)

    return df


def process_oger_output(path: str, input_file_name: str) -> pd.DataFrame:
    """
    Process output TSV from OGER.

    The OGER output is a TSV which is imported and only the terms
    that occurred in the text file are considered and a dataframe
    of relevant information is returned.
    :param path: Path to the folder containing relevant files
    :param input_file_name: OGER output (tsv file)
    :return: Pandas Dataframe containing required data for further analyses.
    """
    cols = [
        "TaxId",
        "Biolink",
        "BeginTerm",
        "EndTerm",
        "TokenizedTerm",
        "PreferredTerm",
        "CURIE",
        "NaN1",
        "SentenceID",
        "NaN2",
        "UMLS_CUI",
    ]
    df = pd.read_csv(
        os.path.join(path, "output", input_file_name + ".tsv"), sep="\t", names=cols
    )
    sub_df = df[["TaxId", "Biolink", "TokenizedTerm", "PreferredTerm", "CURIE"]]

    sub_df["StringMatch"] = sub_df.apply(
        lambda row: assign_string_match_rating(row), axis=1
    )
    sub_df = sub_df.drop_duplicates()
    sub_df.to_csv(
        os.path.join(path, "output", input_file_name + "Filtered.tsv"),
        sep="\t",
        index=False,
    )

    """
    TODO: Figure out synonym categories amongst nodes using OBO Format
    -   Synonyms are always scoped into one of four disjoint categories:
        EXACT, BROAD, NARROW, RELATED
    LOGIC:
        IF TokenizedTerm and PreferredTerm are used interchangeably: EXACT
        ELIF TokenizedTerm is parent of PreferredTerm: BROAD
        ELIF TokenizedTerm is child of PreferredTerm: NARROW
        ELSE: RELATED
    """
    return sub_df


def assign_string_match_rating(dfrow):
    """
    Assign a column categorizing match between TokenizedTerm and PreferredTerm.

    -   Exact
    -   Partial
    -   Synonym
    :param dfRow: each row of the OGER output
    :returns: Same dataframe with an extra 'matchRating' column
    """
    result = None
    if dfrow["TokenizedTerm"] == dfrow["PreferredTerm"]:
        result = "Exact"
    elif dfrow["TokenizedTerm"] in dfrow["PreferredTerm"]:
        result = "Partial"
    else:
        result = "NoMatch"
    return result
