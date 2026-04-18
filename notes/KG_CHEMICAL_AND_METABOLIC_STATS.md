# KG-Microbe Chemical and Metabolic Statistics

**Build Version:** `/data/merged/20260120`
**Analysis Date:** 2026-02-25

---

## Table of Contents

1. [Chemical Entities in KG-Microbe](#chemical-entities-in-kg-microbe)
2. [Media Ingredients and Growth Media](#media-ingredients-and-growth-media)
3. [BacDive Metabolic Relations to Chemicals](#bacdive-metabolic-relations-to-chemicals)

---

## Chemical Entities in KG-Microbe

### Total Chemical Count

**Total unique chemical entity nodes: 224,886**

#### Breakdown by Chemical Identifier Type

| Identifier Type       | Count   | Description                              |
|-----------------------|---------|------------------------------------------|
| CHEBI                 | 224,106 | ChEBI chemical entities                  |
| mediadive.ingredient  | 732     | Named media ingredients                  |
| PubChem               | 36      | PubChem compound identifiers             |
| CAS-RN                | 12      | CAS Registry Number identifiers          |
| **TOTAL**             | **224,886** | **Total unique chemicals**           |

#### Chemical-Related Node Categories

Nodes categorized as chemical-related (by Biolink category):

| Biolink Category         | Count |
|--------------------------|-------|
| biolink:ChemicalMixture  | 4,371 |
| biolink:ChemicalEntity   | 1,772 |
| biolink:ChemicalRole     | 1,468 |
| **Total**                | **7,611** |

#### Additional Chemical-Related Nodes

- **Chemical mixtures (solutions):** 5,403
- **Growth media formulations:** 3,350

---

## Media Ingredients and Growth Media

### Media Ingredient Count: 1,098 Unique Entities

Chemical entities used in growth media solutions:

| Type                 | Count | Description                                    |
|----------------------|-------|------------------------------------------------|
| mediadive.ingredient | 732   | Named ingredients (salts, buffers, compounds)  |
| CHEBI                | 309   | ChEBI chemical entities                        |
| PubChem              | 36    | PubChem compound identifiers                   |
| CAS-RN               | 12    | CAS Registry Number identifiers                |
| FOODON               | 6     | Food ontology terms (e.g., yeast extract)      |
| UBERON               | 3     | Anatomical parts (e.g., tissue extracts)       |
| **TOTAL**            | **1,098** | **Total unique ingredient/chemical entities** |

### MediaDive Hierarchical Structure

The media system is organized hierarchically with three levels:

```
Media (3,350) → Solutions (5,403) → Ingredients/Chemicals (1,098)
```

#### Node Counts

- **3,350 media** (growth media formulations)
- **5,403 solutions** (stock solutions)
- **1,098 unique ingredients/chemicals** (actual chemical constituents)

#### Relationship Statistics

Solutions use `biolink:has_part` to link to their chemical constituents:

- **16,202 edges:** solution → mediadive.ingredient
- **38,660 edges:** solution → CHEBI chemical
- **76,910 total edges** from solutions to their components

Media reference solutions, which in turn contain the actual chemical ingredients.

---

## BacDive Metabolic Relations to Chemicals

### Overview

**Total BacDive metabolic edges to CHEBI chemicals: 1,539,435**

- **Positive relations:** 466,144 (30.28%)
- **Negative relations:** 1,073,290 (69.72%)

BacDive provides extensive negative data (what organisms *don't* do with chemicals), which is valuable for knowledge graph completion and machine learning applications.

### Top Positive Metabolic Relations

Top 5 positive metabolic activities with their most common chemicals:

| METPO ID      | Relation              | Total Edges | Top Chemical (edges)               |
|---------------|-----------------------|-------------|------------------------------------|
| METPO:2000003 | builds acid from      | 104,968     | CHEBI:17306 - maltose (8,105)      |
| METPO:2000002 | assimilates           | 86,953      | CHEBI:17306 - maltose (6,960)      |
| METPO:2000011 | ferments              | 84,907      | CHEBI:17992 - sucrose (5,179)      |
| METPO:2000012 | uses for growth       | 68,948      | CHEBI:17234 - D-glucose (2,737)    |
| METPO:2000006 | uses as carbon source | 57,006      | CHEBI:17234 - D-glucose (2,508)    |

**Common substrates in positive relations:** sugars (maltose, glucose, sucrose, fructose) and organic acids

### Top Negative Metabolic Relations

Top 5 negative metabolic relationships:

| METPO ID      | Relation                     | Total Edges | Top Chemical (edges)                 |
|---------------|------------------------------|-------------|--------------------------------------|
| METPO:2000028 | does not build acid from     | 321,601     | CHEBI:18333 - D-arabitol (10,714)    |
| METPO:2000037 | does not ferment             | 281,355     | CHEBI:28087 - glycogen (7,732)       |
| METPO:2000027 | does not assimilate          | 158,998     | CHEBI:16899 - D-mannitol (8,163)     |
| METPO:2000038 | does not use for growth      | 157,768     | CHEBI:17113 - erythritol (3,429)     |
| METPO:2000039 | does not hydrolyze           | 51,581      | CHEBI:16199 - urea (14,429)          |

**Common substrates in negative relations:** sugar alcohols (arabitol, mannitol, erythritol), complex carbohydrates (glycogen, raffinose), and various polymeric substrates (gelatin, starch)

### All METPO Metabolic Relations

#### Positive Relations (24 relation types)

| METPO ID      | Relation                             | Total Edges |
|---------------|--------------------------------------|-------------|
| METPO:2000003 | builds acid from                     | 104,968     |
| METPO:2000002 | assimilates                          | 86,953      |
| METPO:2000011 | ferments                             | 84,907      |
| METPO:2000012 | uses for growth                      | 68,948      |
| METPO:2000006 | uses as carbon source                | 57,006      |
| METPO:2000013 | hydrolyzes                           | 23,097      |
| METPO:2000017 | reduces                              | 10,964      |
| METPO:2000202 | produces                             | 8,616       |
| METPO:2000019 | uses for respiration                 | 5,024       |
| METPO:2000007 | degrades                             | 4,938       |
| METPO:2000010 | uses as energy source                | 3,932       |
| METPO:2000016 | oxidizes                             | 3,351       |
| METPO:2000014 | uses as nitrogen source              | 1,892       |
| METPO:2000005 | builds gas from                      | 424         |
| METPO:2000009 | uses as electron donor               | 411         |
| METPO:2000008 | uses as electron acceptor            | 237         |
| METPO:2000043 | uses for aerobic growth              | 107         |
| METPO:2000049 | uses for anaerobic growth            | 104         |
| METPO:2000015 | uses in other way                    | 100         |
| METPO:2000004 | builds base from                     | 50          |
| METPO:2000032 | uses for aerobic catabolization      | 48          |
| METPO:2000051 | uses for anaerobic growth with light | 28          |
| METPO:2000048 | uses for anaerobic catabolization    | 23          |
| METPO:2000020 | uses as sulfur source                | 16          |

#### Negative Relations (23 relation types)

| METPO ID      | Relation                                       | Total Edges |
|---------------|------------------------------------------------|-------------|
| METPO:2000028 | does not build acid from                       | 321,601     |
| METPO:2000037 | does not ferment                               | 281,355     |
| METPO:2000027 | does not assimilate                            | 158,998     |
| METPO:2000038 | does not use for growth                        | 157,768     |
| METPO:2000039 | does not hydrolyze                             | 51,581      |
| METPO:2000222 | does not produce                               | 27,197      |
| METPO:2000044 | does not reduce                                | 19,074      |
| METPO:2000031 | does not use as carbon source                  | 18,229      |
| METPO:2000033 | does not degrade                               | 13,219      |
| METPO:2000036 | does not use as energy source                  | 11,978      |
| METPO:2000046 | does not use for respiration                   | 6,186       |
| METPO:2000042 | does not oxidize                               | 2,120       |
| METPO:2000030 | does not build gas from                        | 1,760       |
| METPO:2000040 | does not use as nitrogen source                | 994         |
| METPO:2000034 | does not use as electron acceptor              | 375         |
| METPO:2000035 | does not use as electron donor                 | 360         |
| METPO:2000022 | does not use for aerobic growth                | 186         |
| METPO:2000024 | does not use for anaerobic growth              | 123         |
| METPO:2000045 | is not required for growth                     | 73          |
| METPO:2000041 | does not use in other way                      | 69          |
| METPO:2000029 | does not build base from                       | 23          |
| METPO:2000025 | does not use for anaerobic growth in the dark  | 16          |
| METPO:2000026 | does not use for anaerobic growth with light   | 3           |
| METPO:2000047 | does not use as sulfur source                  | 2           |

### Key Insights

1. **Negative data dominance:** BacDive provides ~70% negative relations vs ~30% positive, which is valuable for:
   - Knowledge graph completion (knowing what organisms *cannot* do)
   - Machine learning training with negative examples
   - Constraining metabolic predictions

2. **Common metabolic substrates:**
   - **Positive:** Simple sugars (glucose, maltose, sucrose, fructose), organic acids
   - **Negative:** Sugar alcohols (arabitol, mannitol, erythritol), complex polymers (glycogen, starch, gelatin)

3. **Metabolic relationship diversity:** 47 different METPO predicates covering:
   - Carbon metabolism (fermentation, acid production, carbon source utilization)
   - Nitrogen/sulfur metabolism
   - Electron transport (donors/acceptors)
   - Polymer degradation (hydrolysis)
   - Energy metabolism

4. **Top individual chemicals by edge count:**
   - **Positive:** maltose (8,105), D-glucose (5,666), sucrose (5,179)
   - **Negative:** D-arabitol (10,714), melezitose (9,493), D-tagatose (9,108)

---

## Data Sources

- **METPO:** Microbial Environmental and Trait Phenotype Ontology
- **BacDive:** Bacterial Diversity Metadatabase
- **MediaDive:** Growth Media Database
- **ChEBI:** Chemical Entities of Biological Interest

## Metadata

- **Total KG nodes:** 1,511,670
- **Total KG edges:** 6,325,020
- **BacDive strain nodes:** 252,156
- **NCBITaxon nodes:** 883,097
