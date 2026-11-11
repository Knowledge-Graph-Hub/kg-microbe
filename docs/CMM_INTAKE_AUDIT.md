# Explicit-local CMM intake audit

This is a **reporting-only extraction** from the old `cmm-ai` branch. That branch
only added merge inputs; it did not establish a current canonical producer. The
audit does not activate CMM in the transform registry or merge configuration.

Run from the repository root, with an existing output parent and a new output
directory:

```bash
python -m scripts.adhoc.audit_cmm_intake \
  --nodes /path/to/cmm-ai_nodes.tsv \
  --edges /path/to/cmm-ai_edges.tsv \
  --output data/cmm-intake-reviewed-input
```

Both inputs must be explicit local regular files, not symlinks. No inputs are
downloaded or selected from an ambient cache. The command uses Python's standard
library and the repository's column constants; it does not import the package's
download/transform stack, KGX, OAK, or pandas. No credentials are needed.

## What is retained

- `original_nodes.tsv` and `original_edges.tsv`: byte-identical originals,
  including quotes, extra columns, duplicate declarations and duplicate claims.
- `findings.jsonl`: every finding, with input role, one-based physical line,
  field, original value, and a finite finding code.
- `counts.jsonl`: streamed exact node-prefix and predicate frequencies. Arbitrary
  source-controlled vocabulary counts stay in an on-disk index, not a growing
  in-memory dictionary or the manifest.
- `manifest.json`: profile version, input paths/SHA-256/byte counts, tool hashes,
  counts, output-file hashes, and explicit limitations.

Rows are streamed as **literal unquoted TSV**: quotes are ordinary characters,
not CSV escapes; a record is one physical line. UTF-8, unique nonempty headers,
consistent field counts and nonblank graph identities are required. Malformed
structure fails the command without publishing a bundle. Missing non-identity
schema/provenance columns are findings, not silently filled fields. Header-only
tables and non-LF line endings are reported; their original bytes are preserved.

The audit uses a temporary on-disk index for node declarations, endpoint closure,
duplicate full edge rows and source-controlled vocabulary frequencies. Memory is
bounded by a record/header, database cache, and finite finding-code counters; it
does not grow with distinct graph identifiers or predicates. The audit does not
load a graph into a dataframe.
Each original and retained copy is fingerprinted and rechecked before publication.
The complete output is staged beside its destination, then published by one
directory rename after an exclusive empty-directory reservation. Existing outputs,
including empty directories and symlinks, are refused. A failed run cleans up only
its own temporary directory and still-empty reservation; it never replaces or
deletes source files or another run's output. This protects ordinary concurrent
invocations; it is not a security boundary against a hostile filesystem owner.

## Meaning of the findings

The finite `cmm-explicit-local-intake-v1` profile compares headers with the current
shared core schema and reports missing fields, internal edge columns, blank
values, pooled/non-infores primary provenance, unrecognized knowledge/agent enums,
relative dangling endpoints, self-loops, and selected legacy namespaces/categories.
It identifies custom/native predicates as requiring their own authority review.

These are **review prompts, not automatic corrections**. For example,
`kgmicrobe.genome:*` must not be replaced with an assembly identifier solely by
string manipulation, and `biolink:Enzyme` must not be assigned a new category
without establishing what the node denotes. A missing endpoint might be declared
by a separate authoritative ontology producer; this audit checks only the supplied
pair. A syntactically well-formed infores value is not proof of registered or
accurate provenance. No field is assigned `manual_agent` or `observation` merely
because those fields were absent.

Exit zero means **the intake report was produced**, even if it contains findings.
Every result remains `INTAKE_AUDIT_ONLY_NOT_ADMITTED`, with source activation,
canonical admission, and release readiness false. It never certifies upstream
authority, licensing, current releases, scientific identity, complete Biolink
categories, domain/range, native predicates, or graph paths. An empty findings file
does not establish acceptance. Structural/I/O failures exit 2.

## Follow-up before onboarding

Establish the authoritative upstream export and how it was generated, select the
intended scope of observations, review namespace/category/predicate decisions and
assertion provenance, then implement a separate source producer with consumed-input
bindings, mandatory audits, source finalization and regression tests. A future merge
configuration change must follow those checks and the canonical variant-generation
workflow. This intake PR makes none of those decisions on the user's behalf.
