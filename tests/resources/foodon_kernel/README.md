# Reviewed FOODON kernel native excerpts (#1296)

These fixtures contain 69 actual, ancestor-closed declarations from the reviewed native FOODON export. They are excerpts, not full native snapshots. Every field of the selected 25 JSON declarations, 31 incident edges, kernel logical definitions, and 25 complete OWL class elements is preserved. XML namespace prefixes and formatting are serialization details; expanded element/attribute names, complete nested structure, text, and child ordering are preserved by the evidence verifier.

Full source SHA-256 values (not fixture hashes):

- `foodon.json`: `8dfba179356a84d8ddad4087dc1fa89a76f6511456c298b9dd7b09df9eb6d853`
- `foodon.owl`: `1e11fc50283c6498697a7aca9606c9d914f1cda71cc5510e006d949c32df7db0`

The independently code-pinned curated policy contains the complete selected semantic witnesses and their hashes. Tests do not replace these pins or manufacture successful kernel declarations. Negative tests deliberately damage copies under `tmp_path`.

The only rejected edge is `FOODON:00005106 rdfs:subClassOf FOODON:00005088`. The valid kernel parent and source-plant restriction remain. The whole-plant controls retain `OrganismTaxon`; exactly 22 affected kernel classes become `Food` in source finalization. No graph rows are changed after merge.
