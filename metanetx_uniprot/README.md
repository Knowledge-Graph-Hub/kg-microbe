# MetaNetX and UniProt Content

Code is reused from Biochem4j: https://github.com/neilswainston/biochem4j/tree/master/sbcdb

Access chemical, reaction, enzyme, and organism information from the following sources:
- libchebipy (note, the _parsers.py file found in this repo must be updated for the libchebipy library at ~/libchebipy/_parsers.py)
- NCBITaxonomy
- MetaNetX
- Rhea
- UniProt

To run the full pipeline to get all relationships: 

```
python build.py ~/biochem4j ',' 1
```

To run and only get reference proteome taxa that also exist in kg-microbe:
```
python build_taxa_ids.py ~/biochem4j 1
```
*Note, uses ncbitaxon.json (built from kg-microbe) which is expected to be in the Files directory.

To build the entire graph by combining all separate triples files, and creating a kgx format nodes file:
```
python combine_rels.py --directory ~/biochem4j/rels
python create_labels_file.py --directory ~/biochem4j/rels
```
This will output the following files:
- ~/biochem4j/rels/combined_kg.csv
- ~/biochem4j/combined_kgx_merged-kg_nodes.csv
