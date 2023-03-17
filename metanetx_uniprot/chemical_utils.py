'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
import math
import uuid

from libchebipy._chebi_entity import ChebiEntity, ChebiException

import namespace_utils as ns_utils
from synbiochem.utils import chem_utils


class ChemicalManager(object):
    '''Class to implement a manager of Chemical data.'''

    def __init__(self, array_delimiter):
        '''Constructor.'''
        self.__array_delimiter = array_delimiter
        self.__nodes = {}
        self.__chem_ids = {}

    def write_files(self, writer):
        '''Write neo4j import files.'''
        return writer.write_nodes(self.__nodes.values(), 'Chemical')

    def add_chemical(self, properties):
        '''Adds a chemical to the collection of nodes, ensuring uniqueness.'''
        chem_id, chebi_ent = self.__get_chem_id(properties)

        if 'charge:float' in properties:
            charge = properties.pop('charge:float')

            if not math.isnan(charge):
                properties['charge:float'] = int(charge)

        if chem_id not in self.__nodes:
            properties[':LABEL'] = 'Chemical'
            properties['id:ID(Chemical)'] = chem_id
            properties['source'] = 'chebi' if 'chebi' in properties else 'mnx'

            _normalise_mass(properties)
            self.__nodes[chem_id] = properties
        else:
            self.__nodes[chem_id].update(properties)

        return chem_id, chebi_ent

    def get_props(self, prop, default=None):
        '''Gets all chem_ids to property as a dict.'''
        return {key: self.__nodes[chem_id].get(prop, default)
                for key, chem_id in self.__chem_ids.items()}

    def get_prop(self, chem_id, prop, default=None):
        '''Gets a property.'''
        return self.__nodes[self.__chem_ids[chem_id]].get(prop, default)

    def __get_chem_id(self, properties):
        '''Manages chemical id mapping.'''
        chebi_id = properties.get('chebi', None)
        chebi_ent = None

        if chebi_id:
            try:
                chebi_id, chebi_ent = _get_chebi_data(chebi_id, properties,
                                                      self.__array_delimiter)
            except ChebiException as exception:
                properties.pop('chebi')
                chebi_id = None
                print(exception)
            except ValueError as exception:
                properties.pop('chebi')
                chebi_id = None
                print(exception)

        mnx_id = properties.get('mnx', None)
        inchi_id = properties.get('inchi', None)

        if chebi_id:
            self.__chem_ids[chebi_id] = chebi_id

            if inchi_id:
                self.__chem_ids[inchi_id] = chebi_id

            if mnx_id:
                self.__chem_ids[mnx_id] = chebi_id

            return chebi_id, chebi_ent

        if inchi_id:
            chem_id = self.__chem_ids.get(inchi_id, None)

            if chem_id:
                return chem_id, None

        if mnx_id:
            chem_id = self.__chem_ids.get(mnx_id, None)

            if chem_id:
                return chem_id, None

            if inchi_id:
                self.__chem_ids[inchi_id] = mnx_id

            self.__chem_ids[mnx_id] = mnx_id
            return mnx_id, None

        new_id = str(uuid.uuid4())
        self.__chem_ids[inchi_id] = new_id

        return new_id, None


def _get_chebi_data(chebi_id, properties, array_delimiter):
    '''Gets ChEBI data.'''
    chebi_ent = ChebiEntity(str(chebi_id))

    if chebi_ent.get_parent_id():
        chebi_id = chebi_ent.get_parent_id()
    else:
        chebi_id = chebi_ent.get_id()

    properties['chebi'] = chebi_id

    formula = chebi_ent.get_formula()
    charge = chebi_ent.get_charge()
    inchi = chebi_ent.get_inchi()
    smiles = chebi_ent.get_smiles()

    if formula:
        properties['formula'] = formula

    if not math.isnan(charge):
        properties['charge:float'] = charge

    if inchi:
        properties['inchi'] = inchi

    if smiles:
        properties['smiles'] = smiles

    properties['name'] = chebi_ent.get_name()
    properties['names:string[]'] = \
        array_delimiter.join([name.get_name()
                              for name in chebi_ent.get_names()] +
                             [chebi_ent.get_name()])

    for db_acc in chebi_ent.get_database_accessions():
        namespace = ns_utils.resolve_namespace(
            db_acc.get_type(), True)

        if namespace is not None:
            properties[namespace] = db_acc.get_accession_number()

    return chebi_id, chebi_ent


def _normalise_mass(properties):
    '''Removes ambiguity in mass values by recalculating according to chemical
    formula.'''
    properties.pop('mass:float', None)

    if 'formula' in properties and properties['formula'] is not None:
        mono_mass = chem_utils.get_molecular_mass(properties['formula'])

        if not math.isnan(mono_mass):
            properties['monoisotopic_mass:float'] = mono_mass
