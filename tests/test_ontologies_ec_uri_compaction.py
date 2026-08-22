"""
Regression tests for EC output URI → CURIE compaction.

Round 29's single-source EC fix (derive ec.json from ec.owl.gz via ROBOT)
regressed the ontologies transform. The fresh ec.json emitted full URIs
(`https://bioregistry.io/eccode:1.1.1`, `http://purl.obolibrary.org/obo/GO_...`,
`https://bioregistry.io/uniprot:...`) instead of CURIEs. The ontologies
transform's generic URI→CURIE compaction reads ``prefixmap.json``, which
was missing the EC and GO entries — and the ec-branch UniProt filter
matches the ``UniprotKB:`` substring, so the ROBOT-emitted URI form
slipped past it. The merged KG inflated by 21× with 236 K junk nodes and
every downstream ``EC:...`` reference landed on a node that did not
exist.

The fix is a two-line data addition (JSON + constants). These tests pin
the resulting invariant end-to-end so the same regression cannot recur.
"""

import contextlib
import csv
import io
import tempfile
from pathlib import Path
from unittest import TestCase

from kg_microbe.transform_utils.ontologies.ontologies_transform import OntologiesTransform

_NODE_HEADER = [
    "id",
    "category",
    "name",
    "description",
    "xref",
    "provided_by",
    "synonym",
    "deprecated",
    "same_as",
]
_EDGE_HEADER = [
    "subject",
    "predicate",
    "object",
    "relation",
    "primary_knowledge_source",
    "knowledge_level",
    "agent_type",
]


def _write_tsv(path: Path, header: list, rows: list) -> None:
    """Write a TSV with ``header`` and ``rows`` at ``path``."""
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def _fixture_nodes() -> list:
    """Return the mixed URI fixture that reproduces the round-34 pollution."""

    def _node(node_id: str, category: str, name: str = "") -> list:
        row = [""] * len(_NODE_HEADER)
        row[0] = node_id
        row[1] = category
        row[2] = name
        row[5] = "ec.json"
        return row

    return [
        # Real EC entries in ROBOT's bioregistry URI form.
        _node("https://bioregistry.io/eccode:1", "biolink:MolecularActivity|biolink:Protein", "Oxidoreductases"),
        _node("https://bioregistry.io/eccode:1.1", "biolink:MolecularActivity|biolink:Protein", "Acting on CH-OH"),
        _node(
            "https://bioregistry.io/eccode:1.1.1",
            "biolink:MolecularActivity|biolink:Protein",
            "with NAD(+) as acceptor",
        ),
        # GO cross-references in ROBOT's OBO URI form.
        _node("http://purl.obolibrary.org/obo/GO_0004022", "biolink:BiologicalProcess", "alcohol dehydrogenase"),
        _node("http://purl.obolibrary.org/obo/GO_0016491", "biolink:BiologicalProcess", "oxidoreductase activity"),
        # UniProt xrefs ROBOT surfaces as bioregistry URIs. These must be
        # dropped by the ec-branch UniProt filter (they are provided
        # elsewhere in the KG), not silently retained as OntologyClass stubs.
        _node("https://bioregistry.io/uniprot:A0A009IHW8", "biolink:OntologyClass"),
        _node("https://bioregistry.io/uniprot:A0A011QK89", "biolink:OntologyClass"),
    ]


def _fixture_edges() -> list:
    """Return edges wired to the same URI-form nodes."""

    def _edge(sub: str, pred: str, obj: str) -> list:
        return [sub, pred, obj, "rdfs:subClassOf", "ec.json", "knowledge_assertion", "manual_agent"]

    return [
        _edge("https://bioregistry.io/eccode:1.1", "biolink:subclass_of", "https://bioregistry.io/eccode:1"),
        _edge("https://bioregistry.io/eccode:1.1.1", "biolink:subclass_of", "https://bioregistry.io/eccode:1.1"),
        # An EC → GO cross-reference: subject compacts to EC:, object to GO:.
        _edge(
            "https://bioregistry.io/eccode:1.1.1",
            "biolink:related_to",
            "http://purl.obolibrary.org/obo/GO_0016491",
        ),
        # An EC → UniProt edge that must be dropped alongside the node.
        _edge(
            "https://bioregistry.io/eccode:1.1.1",
            "biolink:enabled_by",
            "https://bioregistry.io/uniprot:A0A009IHW8",
        ),
    ]


def _build_transform(output_dir: Path) -> OntologiesTransform:
    """Instantiate an OntologiesTransform without running __init__ side effects."""
    transform = OntologiesTransform.__new__(OntologiesTransform)
    transform.output_dir = output_dir
    transform.node_header = list(_NODE_HEADER)
    transform.edge_header = list(_EDGE_HEADER)
    # post_process's ec branch reads the knowledge source table when writing
    # the normalized edges.
    transform.ONTOLOGY_KNOWLEDGE_SOURCES = {"ec": "infores:ec"}
    return transform


class TestEcPostProcessUriCompaction(TestCase):
    """post_process('ec') must convert every URI to its CURIE and drop UniProt stubs."""

    def _run_post_process(self, tmp: Path):
        """Materialize fixtures, run post_process('ec'), return (nodes_path, edges_path)."""
        nodes_path = tmp / "ec_nodes.tsv"
        edges_path = tmp / "ec_edges.tsv"
        _write_tsv(nodes_path, _NODE_HEADER, _fixture_nodes())
        _write_tsv(edges_path, _EDGE_HEADER, _fixture_edges())
        _build_transform(tmp).post_process("ec")
        return nodes_path, edges_path

    def test_no_uri_survives_in_node_ids(self):
        """A ``https://`` prefix in any node ID would silently disconnect the node."""
        with tempfile.TemporaryDirectory() as tmp:
            nodes_path, _ = self._run_post_process(Path(tmp))
            with open(nodes_path) as fh:
                reader = csv.DictReader(fh, delimiter="\t")
                ids = [row["id"] for row in reader]
            offenders = [i for i in ids if i.startswith("http://") or i.startswith("https://")]
            self.assertEqual(
                offenders,
                [],
                f"URI-form node IDs escaped compaction: {offenders}",
            )

    def test_no_uri_survives_in_edge_subject_or_object(self):
        """Edges must reference CURIEs, not the URIs upstream ROBOT emitted."""
        with tempfile.TemporaryDirectory() as tmp:
            _, edges_path = self._run_post_process(Path(tmp))
            with open(edges_path) as fh:
                reader = csv.DictReader(fh, delimiter="\t")
                offenders = [
                    (row["subject"], row["object"])
                    for row in reader
                    if row["subject"].startswith(("http://", "https://"))
                    or row["object"].startswith(("http://", "https://"))
                ]
            self.assertEqual(
                offenders,
                [],
                f"URI-form edge endpoints escaped compaction: {offenders}",
            )

    def test_ec_and_go_curies_are_preserved(self):
        """The real EC and GO content must survive with the expected CURIEs."""
        with tempfile.TemporaryDirectory() as tmp:
            nodes_path, edges_path = self._run_post_process(Path(tmp))
            with open(nodes_path) as fh:
                ids = {row["id"] for row in csv.DictReader(fh, delimiter="\t")}
            self.assertIn("EC:1", ids)
            self.assertIn("EC:1.1", ids)
            self.assertIn("EC:1.1.1", ids)
            self.assertIn("GO:0004022", ids)
            self.assertIn("GO:0016491", ids)

            with open(edges_path) as fh:
                edges = [(r["subject"], r["object"]) for r in csv.DictReader(fh, delimiter="\t")]
            self.assertIn(("EC:1.1.1", "EC:1.1"), edges)
            self.assertIn(("EC:1.1.1", "GO:0016491"), edges)

    def test_uniprot_bioregistry_uris_are_filtered(self):
        """
        The ec-branch UniProt filter must catch the ROBOT bioregistry URI form.

        Round-34 regression: the filter checked for the ``UniprotKB:``
        substring in each line, so URI-form UniProt xrefs slipped past
        it and became 236 K OntologyClass stubs in the ec output.
        Compaction of the URI to its CURIE (via the new SPECIAL_PREFIXES
        entry) happens before the substring check, so the filter matches
        and the node is dropped along with any edge that references it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            nodes_path, edges_path = self._run_post_process(Path(tmp))
            with open(nodes_path) as fh:
                ids = {row["id"] for row in csv.DictReader(fh, delimiter="\t")}
            # The UniProt stubs and any CURIE they might have compacted to
            # must be absent.
            for banned in (
                "https://bioregistry.io/uniprot:A0A009IHW8",
                "UniprotKB:A0A009IHW8",
                "https://bioregistry.io/uniprot:A0A011QK89",
                "UniprotKB:A0A011QK89",
            ):
                self.assertNotIn(banned, ids, f"{banned} must be filtered out of ec_nodes.tsv")

            with open(edges_path) as fh:
                edges = list(csv.DictReader(fh, delimiter="\t"))
            for row in edges:
                self.assertFalse(
                    "uniprot" in row["subject"].lower() or "uniprot" in row["object"].lower(),
                    f"UniProt edge survived: {row}",
                )

    def test_edge_header_is_written_exactly_once(self):
        """
        The ec branch must not leave the incoming header as a data row.

        The branch rewrites ec_edges.tsv with a canonical header, and the
        read loop that feeds it skipped headers by matching ``id`` — the
        node header's first column. An edges header starts with
        ``subject``, so it never matched and survived into the body. KGX
        then read ``subject``/``object`` as endpoint CURIEs and
        synthesized two bare ``biolink:NamedThing`` nodes in the merged
        KG. DictReader-based assertions cannot see this, so compare raw
        lines.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _, edges_path = self._run_post_process(Path(tmp))
            with open(edges_path) as fh:
                lines = [line.rstrip("\n") for line in fh if line.strip()]
            header = lines[0].split("\t")
            self.assertEqual(header[:3], ["subject", "predicate", "object"])
            duplicates = [i for i, line in enumerate(lines[1:], start=2) if line.split("\t")[:3] == header[:3]]
            self.assertEqual(
                duplicates,
                [],
                f"edges header repeated as a data row at line(s) {duplicates}",
            )


class TestStrayHeaderRowsAreDropped(TestCase):
    """The incoming KGX header must not survive into the edge body."""

    # KGX's edges TSV leads with an `id` column, so its header's first field is
    # "id" — not "subject". Using the canonical header in a fixture here is
    # what let PR #680 ship green while broken: its guard matched "subject",
    # which the test provided and production never does.
    _KGX_EDGE_HEADER = ["id", "subject", "predicate", "object", "relation", "knowledge_source"]

    def _kgx_shaped_edges(self, tmp_path: Path) -> Path:
        """Write an edges file in the shape KGX actually produces."""
        edges_path = tmp_path / "ec_edges.tsv"
        rows = [
            [
                f"urn:uuid:{i}",
                "https://bioregistry.io/eccode:1.1",
                "biolink:subclass_of",
                "https://bioregistry.io/eccode:1",
                "rdfs:subClassOf",
                "ec.json",
            ]
            for i in range(3)
        ]
        _write_tsv(edges_path, self._KGX_EDGE_HEADER, rows)
        return edges_path

    def test_kgx_header_is_consumed_not_left_in_the_body(self):
        """
        The producer must drop the real header, whose first field is "id".

        PR #680 replaced a working ``startswith("id")`` guard with one matching
        "subject", on the mistaken belief that an edges header cannot start
        with "id". That left the real header in the body, and KGX read its
        "subject"/"object" cells as endpoint CURIEs in the merged KG,
        synthesizing two empty biolink:NamedThing nodes. The pre-#680 output on
        disk has zero stray rows; the post-#680 output has one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_tsv(tmp_path / "ec_nodes.tsv", _NODE_HEADER, _fixture_nodes())
            edges_path = self._kgx_shaped_edges(tmp_path)

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                _build_transform(tmp_path).post_process("ec")

            with open(edges_path) as fh:
                lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
            first_fields = [ln.split("\t")[0] for ln in lines[1:]]
            self.assertNotIn("id", first_fields, "the KGX header survived into the body")
            self.assertNotIn("subject", first_fields, "a header row survived into the body")
            self.assertEqual(len(lines), 4, "3 edges plus exactly one header")

            # Assert the leak is stopped at SOURCE, not swept up downstream.
            # Without this the _normalize_schema backstop silently repairs a
            # broken producer and the test passes either way — which is the
            # same masking that let #680 ship green.
            self.assertNotIn(
                "stray header row",
                captured.getvalue(),
                "the backstop fired, so the producer guard is not doing its job",
            )

    def test_normalize_schema_backstops_a_leaked_header(self):
        """
        A leak from any producer is still removed downstream.

        This is defence in depth, not the primary fix: with the producer guard
        correct the backstop should never fire on a real run.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            nodes_path = tmp_path / "ec_nodes.tsv"
            edges_path = tmp_path / "ec_edges.tsv"
            _write_tsv(nodes_path, _NODE_HEADER, _fixture_nodes())
            _write_tsv(edges_path, _EDGE_HEADER, [list(_EDGE_HEADER)] + _fixture_edges())

            transform = _build_transform(tmp_path)
            transform._normalize_schema(nodes_path, edges_path)

            with open(edges_path) as fh:
                lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
            strays = [i for i, ln in enumerate(lines[1:], start=2) if ln.split("\t")[0] == "subject"]
            self.assertEqual(strays, [], f"stray header row(s) survived at line(s) {strays}")
            self.assertEqual(len(lines), 1 + len(_fixture_edges()), "real edges must be untouched")
