# MetaNetX and UniProt Content

Code is reused from Biochem4j: https://github.com/neilswainston/biochem4j/tree/master/sbcdb

Access chemical, reaction, enzyme, and organism information from the following sources:
- libchebipy
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
