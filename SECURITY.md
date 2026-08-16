# Security Policy

## Supported Versions

`kg-microbe` is a research knowledge-graph pipeline developed in-tree on the `master` branch.

The repository does publish [tagged releases](https://github.com/Knowledge-Graph-Hub/kg-microbe/releases) — these are dated snapshots of the built knowledge graph and its inputs, not software versions with independent support windows. **Only `master` is supported.** Security fixes land there and are picked up by consumers on next pull or build; older release tags are not patched in place.

## Reporting a Vulnerability

Please **do not** open a public issue for vulnerabilities.

Use **GitHub private vulnerability reporting**: Security tab → *Report a vulnerability*. This is enabled on the repository and routes the report privately to the maintainers.

If you cannot use it, contact the maintainer listed in the `authors` field of `pyproject.toml`.

## What to expect

- We aim to acknowledge receipt within a few business days.
- Triage and fix timelines depend on severity and scope. This is a research project without a dedicated security team, so please size your expectations accordingly.
- Coordinated disclosure is preferred; please give us a reasonable window before public disclosure.

## Scope

This policy covers code in this repository.

Vulnerabilities in upstream dependencies (`oaklib`, `kgx`, `koza`, …) should be reported to those projects directly. We track them here via Dependabot alerts — note that an open alert on this repository is not by itself evidence of exposure; as of 2026-08-15 every open alert named a package already pinned at or past its patched version in `poetry.lock`.

Data content — a wrong ontology grounding, a mis-attributed edge — is a correctness bug, not a security issue. Please file those as normal public issues.
