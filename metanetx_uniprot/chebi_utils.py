'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
from libchebipy._chebi_entity import ChebiEntity


def load(chem_manager, writer):
    '''Loads ChEBI data from libChEBIpy.'''
    chebi_ids = []
    rels = []

    _add_node('CHEBI:24431', chebi_ids, rels, chem_manager)

    writer.write_rels(rels, 'Chemical', 'Chemical')


def _add_node(chebi_id, chebi_ids, rels, chem_manager):
    '''Constructs a node from libChEBI.'''
    if chebi_id not in chebi_ids:
        chebi_ids.append(chebi_id)

        chem_id, entity = chem_manager.add_chemical({'chebi': chebi_id})

        for incoming in entity.get_incomings():
            target_id = incoming.get_target_chebi_id()

            chebi_ent = ChebiEntity(target_id)

            if chebi_ent.get_parent_id():
                target_id = chebi_ent.get_parent_id()

            _add_node(target_id, chebi_ids, rels, chem_manager)
            rels.append([target_id, incoming.get_type(), chem_id])
