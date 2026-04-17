# Security Policy

## Supported Versions

`kg-microbe` is a research knowledge-graph pipeline developed in-tree on the `master` branch. We do not currently publish tagged releases with separate security support windows. Security fixes land on `master` and are picked up by consumers on next pull/build.

## Reporting a Vulnerability

Please **do not** open a public issue for vulnerabilities.

Use **GitHub's private vulnerability reporting** feature instead:

> Security tab → Report a vulnerability

This routes the report privately to the maintainers. If private reporting is not enabled on this repo or you cannot use it, email the maintainer listed in `pyproject.toml` (`authors` field).

## What to expect

- We aim to acknowledge receipt within a few business days.
- Triage and fix timelines depend on severity and scope.
- Coordinated disclosure is preferred; please give us a reasonable window before public disclosure.

## Scope

This policy covers code in this repository. Vulnerabilities in upstream dependencies (e.g. `oaklib`, `kgx`, `koza`) should be reported to those projects directly; we track them via Dependabot alerts here.
