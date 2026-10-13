# Native Rhea direction contract (#1395, #1396)

The candidate Rhea transform reads a single local, hash-pinned native snapshot.
It does not select a PyOBO home cache, download mutable inputs during transform,
or infer direction from iteration order or arithmetic on identifiers.

## Graph meaning

| `rhea_direction` | Native meaning | Participation edges |
| --- | --- | --- |
| `UN` | Direction unspecified | `biolink:has_participant` |
| `LR` | Left-to-right variant | `biolink:has_input` / `biolink:has_output` |
| `RL` | Right-to-left variant | Input/output sides reversed |
| `BI` | Bidirectional variant | `biolink:has_participant` |

Every active reaction node also carries `rhea_master_id` and `rhea_status`.
`Preliminary` is retained as preliminary, not promoted to `Approved`.
Undefined direction is not equilibrium, neutral flux, or bidirectionality.
These reaction descriptions do not establish physiological flux in an organism.
See the [native Rhea direction documentation](https://www.rhea-db.org/help/reaction-side-direction).

The master links to LR and RL using the exact native
`rheav:directionalReaction`, and to BI using `rheav:bidirectionalReaction`.
These are neither identity nor subclass edges. `rheav` expands to
`http://rdf.rhea-db.org/`; numeric reaction IDs retain the established `RHEA`
namespace. Native predicates are intentional project extensions, **not strict
Biolink conformance**. Strict predicate and domain/range diagnostics remain
visible; namespace registration does not waive them.

Participation edges retain `rhea_side`, `rhea_participant`, `rhea_compound`, and
`rhea_participant_route` witnesses. A direct native `chebi` route uses that
ChEBI entity. For generic compounds and polymers, the candidate keeps the
native compound as participant: `reactivePart` then `chebi`, or
`underlyingChebi`, remain distinct native paths. A protein's reactive moiety is
not the whole protein, and polymers at n, n+1, and n-1 are not identical merely
because they reference the same underlying ChEBI term. Native compound names
and `rhea_polymerization_index` survive. Stoichiometric coefficients are not yet
separately modeled; no complete stoichiometric integration is claimed.

## Inputs and acquisition boundary

Required local files beneath the chosen input directory:

- `rhea/rhea-directions.tsv`
- `rhea/rhea.rdf.gz`

Their complete SHA-256 values and byte sizes must match
`mappings/rhea_release.json`. The pins are Rhea release 142 (2026-09-02): both
files are byte-identical to the members of the archived release tarball
`old_releases/142.tar.bz2` named in the policy (verified 2026-10-12, #1420).
Stage only that reviewed pair. Mutable FTP latest downloads cannot silently
replace it; a new snapshot requires review and a pin update. Existing
`rhea2ec.tsv` and `rhea2go.tsv` are no longer consumed by this
producer. EC/GO cross-references come from the same pinned RDF and are emitted
once per assertion on their exact native subjects (usually the master, with
native variant exceptions retained). Provisional EC identifiers such as
`EC:3.6.5.n1` are preserved, not discarded by a numeric-only parser.

`kg download -t rhea` downloads the archived release tarball (about 412 MB)
into **`data/raw/rhea_download/`**, an acquisition quarantine, not the admitted
input directory. The URL-only download manifest does not certify the snapshot.
Explicitly extract and stage the reviewed pair before transforming:

```bash
poetry run python -m kg_microbe.transform_utils.rhea_mappings.stage_snapshot \
  --source-archive data/raw/rhea_download/142.tar.bz2 --input-dir data/raw
```

The stager reads the archive once as a stream and writes only the two members
the policy names, under their fixed payload names; a missing, repeated, linked
or non-regular member is refused. Alternatively, point `--source-dir` to an
explicitly selected local export with the pinned bytes. The stager makes no
network requests. It verifies both exact hashes/sizes, native family/cohort
agreement, participant joins and selected cross-reference structure before
publishing the complete directory. It verifies identical existing inputs
without rewriting them and refuses different, partial or symlink destinations.
It never deletes or replaces an existing raw generation, changes the pin,
repairs a source, or declares transform/release acceptance. A member that
differs from its pin fails staging; review a new snapshot before changing pins.
Existing legacy raw mapping files are left untouched but are not input
authorities for this producer.

External node labels require prepared `chebi.db`, `go.db` and `ec.db` in that
same selected raw directory. The producer reads byte-tracked immutable copies
through read-only SQLite, checks the ontology declaration/schema and indexed
exact-ID lookup, and never builds a database, downloads one, or consults a global
adapter/cache. Conflicting or nonliteral labels fail; missing labels remain blank
and are counted by namespace. Unconsumed SQLite journal/WAL state fails at read,
source finalization and merge admission. Temporary snapshots need space roughly
equal to the three database files. Their hashes identify the actual authorities;
ontology preparation/version alignment remains an upstream prerequisite.

`mappings/rhea_legacy_xref_dispositions.json` binds six observed old-only
cross-references to the two reviewed RDF snapshots. The mandatory producer audit
`rhea_legacy_xref_dispositions.tsv` preserves each original assertion and its
evidence, including the separate old GO:0018581 → GO:0047074 normalization.
These are explicit historical exclusions, not global identifier invalidations
or replacement rules. The new native annotations remain on their exact subjects;
all seven native directional GO assertions are checked, including their side
roles. Current indexed context is verified against the consumed RDF; historical
comments and GO hierarchy explanations are retained as reviewed evidence, not
falsely reported as revalidated at runtime. This audit never edits graph rows.

Path-derived participation is tagged `logical_entailment` / `automated_agent`.
Human review of the transform code is not per-assertion manual validation.

At the initial KGX serialization boundary, the four Rhea node annotations are
scalar: identical source contributions coalesce, empty contributions remain
absent, and conflicting nonempty values fail. Direction/master/status tokens
are validated, while polymer expressions remain literal text. This is transport
and cross-source conflict checking, not semantic editing of a merged archive.
The separate pre-existing blank-xref list aggregation finding in #1398 remains
outside this bounded Rhea-field repair.

The directions table must exactly cover every Approved or Preliminary numeric
RDF reaction, with native family links and side-role agreement. Missing,
ambiguous, conflicting, or unknown statuses fail. Only explicitly Obsolete
records are excluded, each in the mandatory
`rhea_reaction_dispositions.tsv` audit. All active members are also listed in
that report. Input reads and producer audit bytes participate in source
finalization and merge admission.

## Acceptance still required

Hermetic tests check input integrity, family/side semantics, generic/polymer
identity, obsolete and preliminary handling, and canonical output transport.
Those tests are not a rebuilt release. Full producer execution, independent model/path review,
all-producer rebuild, and review of the exact resulting archive remain required.
No merged graph is semantically edited by this implementation.
