'''
synbiochem (c) University of Manchester 2015

synbiochem is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
__CHEMICAL_NAMESPACE = {
    # value (namespace) corresponds to identifiers.org:
    'bigg': 'bigg.metabolite',
    'CAS Registry Number': 'cas',
    'chebi': 'chebi',
    'ChemIDplus accession': 'chemidplus',
    'Chemspider accession': 'chemspider',
    'DrugBank accession': 'drugbank',
    'hmdb': 'hmdb',
    'HMDB accession': 'hmdb',
    'kegg': 'kegg.compound',
    'KEGG COMPOUND accession': 'kegg.compound',
    'KEGG DRUG accession': 'kegg.drug',
    'KEGG GLYCAN accession': 'kegg.glycan',
    'KNApSAcK accession': 'knapsack',
    'lipidmaps': 'lipidmaps',
    'LIPID MAPS instance accession': 'lipidmaps',
    'MolBase accession': 'molbase',
    'PDB accession': 'pdb',
    'PubMed citation': 'pubmed',
    'reactome': 'reactome',
    'RESID accession': 'resid',
    'seed': 'seed.compound',
    'umbbd': 'umbbd.compound',
    'UM-BBD compID': 'umbbd.compound',
    'upa': 'unipathway',
    'Wikipedia accession': 'wikipedia.en',

    # Not in identifiers.org:
    'metacyc': 'metacyc',
    'MetaCyc accession': 'metacyc',
    'mnx': 'mnx'
}

__REACTION_NAMESPACE = {
    # value (namespace) corresponds to identifiers.org:
    'bigg': 'bigg.reaction',
    'kegg': 'kegg.reaction',
    'reactome': 'reactome',
    'rhea': 'rhea',
    'seed': 'seed',

    # Not in identifiers.org:
    'metacyc': 'metacyc',
    'mnx': 'mnx',
}


def resolve_namespace(name, chemical):
    '''Maps name to distinct namespace from identifiers.org.'''
    namespace = __CHEMICAL_NAMESPACE if chemical else __REACTION_NAMESPACE
    return namespace[name] if name in namespace else None
