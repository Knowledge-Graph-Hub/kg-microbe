# Immutable PubChem authority evidence for #788/#1155

`pubchem_cysteine_scope.json` is the byte-identical response fetched on
2026-09-25 from the primary PubChem PUG REST property endpoint:

https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/5862,60960/property/MolecularFormula,IUPACName,Title/JSON

SHA-256: `3a6a21b65b509f290c812ea4640c54e97103e6b9611fbcd7d2db89abc82eabfe`.

CID 5862 is **L-(+)-Cysteine**, formula **C3H7NO2S**. CID 60960 is
**Cysteine Hydrochloride**, formula **C3H8ClNO2S**, with `hydrochloride`
explicit in the IUPAC name. The historical MediaDive `Cysteine-HCl` alias
and raw legacy mapping to PubChem:5862 erase the explicitly reported salt.

This evidence supports rejecting that parent/salt exact identity, not guessing
that every recipe's unqualified hydrochloride selects CID 60960 or a particular
hydrate. Tests use 60960 only when a fixture independently supplies it as an
embedded source assertion; the policy does not mint a replacement mapping.

The finite PubChem:/pubchem.compound: and CAS-RN:/cas: namespace aliases are
already used by the consolidator. Applying them to policy keys prevents a
serialization spelling from bypassing a reviewed rejection; it does not infer
chemical equivalence or a KEGG subtype.
