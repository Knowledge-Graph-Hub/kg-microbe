# MediaDive repeated recipe occurrence evidence

`mediadive_solution_5787.json` preserves the complete parsed solution `5787`
record from `data/raw/mediadive/solutions.json`, inspected on 2026-09-25.
Source-file SHA256:
`9ab0fbf72c2e5ac25ecab3ada268dfe524db971daa86d67532dea6a5412a5c44`.
Formatting differs from the complete JSON file; every field and value of this
solution record is retained. No chemical target or concentration correction is
asserted by this fixture.

Positions 2 and 4 both reference compound 981 (`NiCl2 x 2 H2O`) but carry
different amount, mass concentration and molar concentration. Both observations
must survive; the upstream quantities are evidence, not values to recompute.
The test module separately constructs synthetic equal-quantity, name-collision,
nested-solution and missing/repeated-order cases to establish software behavior.

`mediadive_recipe_alternatives.json` preserves the four complete raw item
payloads selected from the same source JSON: water entries in solution 815
(source positions 7 and 8) and yeast-extract entries in solution 485 (positions
2 and 3). The fixture contains excerpts, not their complete solution recipes;
the tests retain the recorded qualifiers and optional flags without interpreting
the occurrences as simultaneous mandatory additions or summing their amounts.
