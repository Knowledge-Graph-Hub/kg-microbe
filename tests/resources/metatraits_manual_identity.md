# MetaTraits manual identity regression (#1184)

The two TSV data rows are verbatim projections of the already promoted supported
MIM SSSOM, lines 1414 and 1573. The original member SHA256 is
`6b52b30e018b369aa322d41dfd4e81fcfae0e895e34d7fe48900abf5835815fb`,
from immutable producer commit `1848b0fe521bc2462f165912fcf92d09ad9a8cec`.
The original header calls its alias extension `other`; the selected
rows have empty values there. Neither this fixture nor the correction adds chemical
equivalence, CAS, synonyms, or a parent relation.

These existing source-local identities preserve Soyton and Proteose separately.
They do not identify either ingredient as proteose peptone, fresh bratwurst
(`FOODON:00002992`), or one another. The two canonical MetaTraits overrides had
incorrectly assigned that FoodOn target. The generic manual Tier 2 route also
bypassed the ingredient guards already used by the special resolver.

The tests construct synthetic trait summaries with these exact observed trait
names (`growth: soyton`, `growth: proteose`). Their taxonomy, percentages, and
polarity combinations are route controls, not claims about the organisms.
Real manual and special readers, real bounded chemical-loader ingestion, both
serial and worker paths, and both MetaTraits source classes are exercised.
The tiny generated loader includes deliberately stale FoodOn aliases as a
negative control; the fixture is not an ontology export or a production audit.

The live promoted SSSOM and release pin are read only. Tests compare the two
selected supported rows with this fixture, while all generated inputs and
outputs remain under pytest's temporary directory. Production source/archive
rebuild and independent occurrence/projection review remain separate gates.
