Final read-only review of PR #1836 found a P2 repository-contract violation in
the new required LPSN record audit. `csv.writer(..., delimiter="\t")` uses CRLF
by default. The repository requires LF-only TSV writers; the AST guard in
`tests/test_tsv_line_endings.py` rejects this call.

Use the existing `tsv_writer` utility for `lpsn_api_records.tsv`. Add a persisted
ledger regression requiring LF and rejecting CRLF, run the TSV contract tests,
and refresh the canary/full audit receipts. Graph assertions and citation labels
should remain unchanged.
