'''
SYNBIOCHEM-DB (c) University of Manchester 2015

SYNBIOCHEM-DB is licensed under the MIT License.

To view a copy of this license, visit <http://opensource.org/licenses/MIT/>.

@author:  neilswainston
'''
import os
import tempfile
import urllib
import zipfile
from urllib.request import urlretrieve

import ijson


__MONA_URL = 'http://mona.fiehnlab.ucdavis.edu/rest/downloads/retrieve/' + \
    'd2eb33f0-b22e-49a7-bc31-eb951f8347b2'

__MONA_FILENAME = 'MoNA-export-All_Spectra.json'

_NAME_MAP = {'kegg': 'kegg.compound',
             'molecular formula': 'formula',
             'total exact mass': 'monoisotopic_mass:float'}


def load(writer, chem_manager,
         array_delimiter='|', url=__MONA_URL, filename=__MONA_FILENAME):
    '''Build Spectrum nodes and relationships.'''
    nodes = []
    rels = []

    records = _parse(_get_file(url, filename), array_delimiter)

    for record in records:
        chem_id, _ = chem_manager.add_chemical(record['chemical'])
        nodes.append(record['spectrum'])
        rels.append([chem_id, 'has', record['spectrum']['id:ID(Spectrum)']])

    return [writer.write_nodes(nodes, 'Spectrum')], \
        [writer.write_rels(rels, 'Chemical', 'Spectrum')]


def _parse(filename, array_delimiter):
    '''Parses MoNA json file.'''
    records = []
    record = {'chemical': {'names:string[]': []},
              'spectrum': {':LABEL': 'Spectrum', 'tags:string[]': []}}
    name = None

    for prefix, typ, value in ijson.parse(open(filename)):
        if prefix == 'item' and typ == 'start_map':
            record = {'chemical': {'names:string[]': []},
                      'spectrum': {':LABEL': 'Spectrum',
                                   'tags:string[]': []}}
        elif prefix == 'item.compound.item.inchi':
            record['chemical']['inchi'] = value
        elif prefix == 'item.compound.item.names.item.name':
            if 'name' not in record['chemical']:
                record['chemical']['name'] = value
            record['chemical']['names:string[]'].append(value)
        elif prefix == 'item.compound.item.metaData.item.name' or \
                prefix == 'item.metaData.item.name':
            name = _normalise_name(value.lower())
        elif prefix == 'item.compound.item.metaData.item.value':
            _parse_compound_metadata(name, value, record)
            name = None
        elif prefix == 'item.id':
            record['spectrum']['id:ID(Spectrum)'] = value
        elif prefix == 'item.metaData.item.value':
            record['spectrum'][name] = value
            name = None
        elif prefix == 'item.spectrum':
            values = [float(val) for term in value.split()
                      for val in term.split(':')]
            record['spectrum']['m/z:float[]'] = \
                array_delimiter.join(map(str, values[0::2]))
            record['spectrum']['I:float[]'] = \
                array_delimiter.join(map(str, values[1::2]))
        elif prefix == 'item.tags.item.text':
            record['spectrum']['tags:string[]'].append(value)
        elif prefix == 'item' and typ == 'end_map':
            records.append(record)

    return records


def _get_file(url, filename):
    '''Gets file from url.'''
    destination = os.path.join(os.path.expanduser('~'), 'MoNA')

    if not os.path.exists(destination):
        os.makedirs(destination)

    filepath = os.path.join(destination, filename)

    if not os.path.exists(filepath):
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        urlretrieve(url, tmp_file.name)
        zfile = zipfile.ZipFile(tmp_file.name, 'r')
        filepath = os.path.join(destination, zfile.namelist()[0])
        zfile.extractall(destination)

    return filepath


def _parse_compound_metadata(name, value, record):
    '''Parses compound metadata.'''
    if name == 'chebi' and isinstance(value, str):
        value = value.replace('CHEBI:', '').split()[0]

    record['chemical'][_normalise_name(name)] = value


def _normalise_name(name):
    '''Normalises name in name:value pairs.'''
    if name in _NAME_MAP:
        return _NAME_MAP[name]

    return name.replace(':', '_')
