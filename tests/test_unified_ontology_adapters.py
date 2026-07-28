"""
Tests that every ontology adapter goes through the guarded accessors.

OAK treats ``get_adapter("sqlite:<something>.owl")`` as a request to *build* the
SemSQL DB for that OWL, and runs its own `semsql make` to do it — unannounced,
outside `KG_SEMSQL_BUILD`, and without the size floor, keep-aside or version
gates this module provides. Seven transforms did exactly that, so
`kg transform -s bacdive` could silently start a multi-hour, 13 GB NCBITaxon
build. The guard test below is the durable part: it fails if any source file
reintroduces the pattern.
"""

import ast
from pathlib import Path

import pytest

from kg_microbe.utils import ontology_utils as ou

SOURCE_ROOT = Path(__file__).parent.parent / "kg_microbe"

# Constants that name an .owl path. Passing one to get_adapter means "build".
OWL_SOURCE_NAMES = {"NCBITAXON_SOURCE", "CHEBI_SOURCE", "GO_SOURCE", "EC_SOURCE"}


def _get_adapter_calls():
    """Yield (file, lineno, rendered-arg) for every get_adapter(...) call."""
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "get_adapter" or not node.args:
                continue
            yield path.relative_to(SOURCE_ROOT), node.lineno, ast.dump(node.args[0])


class TestNoUnguardedAdapters:

    """No source file may construct an adapter from an OWL-path constant."""

    def test_no_module_maps_prefixes_to_owl_sources(self):
        """
        Indirection must not smuggle an OWL path into get_adapter either.

        ner_utils used to map prefixes to GO_SOURCE/CHEBI_SOURCE and interpolate
        the result, which the constant-name check below cannot see.
        """
        ner = (SOURCE_ROOT / "utils" / "ner_utils.py").read_text(encoding="utf-8")
        assert "PREFIX_SOURCE_MAP" not in ner, "map prefixes to ontology keys, not OWL paths"

    def test_no_get_adapter_uses_an_owl_source_constant(self):
        """The regression guard: an .owl path here means an unguarded build."""
        offenders = [
            f"{path}:{lineno}"
            for path, lineno, arg in _get_adapter_calls()
            if any(f"'{const}'" in arg or f'"{const}"' in arg for const in OWL_SOURCE_NAMES)
        ]
        assert offenders == [], (
            "get_adapter must never be handed an OWL path — use "
            f"get_ontology_adapter()/get_*_adapter() instead. Offenders: {offenders}"
        )

    def test_remaining_adapter_calls_are_in_known_places(self):
        """Every direct get_adapter call should be a guarded accessor or a real .db."""
        allowed = {
            "utils/ontology_utils.py",  # the accessors themselves
            "transform_utils/metatraits/metatraits.py",  # validated ncbitaxon.db
            "transform_utils/ontologies_stubs/ontologies_stubs_transform.py",  # downloaded .db.gz
            "transform_utils/bakta/bakta.py",  # explicit go.db path
            # Experimental `llm:sqlite:` spec the accessors do not model; it goes
            # through ontology_db_path(), so it points at the .db not the OWL.
            "utils/ner_utils.py",
        }
        unexpected = {str(path) for path, _, _ in _get_adapter_calls() if str(path) not in allowed}
        assert unexpected == set(), (
            f"new direct get_adapter call sites: {sorted(unexpected)} — route them "
            "through get_ontology_adapter() or add them here with a reason"
        )


class TestAccessorContract:

    """The accessors resolve, memoise and fail predictably."""

    @pytest.fixture(autouse=True)
    def _clear(self):
        """Drop memoised adapters so tests cannot see each other's."""
        ou.get_ontology_adapter.cache_clear()
        yield
        ou.get_ontology_adapter.cache_clear()

    @pytest.mark.parametrize(
        ("ontology", "expected"),
        [("ncbitaxon", "ncbitaxon.db"), ("chebi", "chebi.db"), ("go", "go.db"), ("ec", "ec.db")],
    )
    def test_db_path_sits_beside_the_owl(self, ontology, expected):
        """Each DB is resolved next to its OWL source, not somewhere else."""
        assert ou.ontology_db_path(ontology).endswith(expected)

    def test_unknown_ontology_is_rejected(self):
        """A typo must fail loudly rather than resolving to something odd."""
        with pytest.raises(KeyError):
            ou.ontology_db_path("nosuchontology")

    def test_unavailable_db_raises_with_remediation(self, monkeypatch):
        """No usable DB must produce an actionable error, not an opaque OAK failure."""
        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *_: False)
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: pytest.fail("must not open"))
        with pytest.raises(ou.OntologyDbUnavailableError, match="No usable go SemSQL DB"):
            ou.get_ontology_adapter("go")

    def test_failure_is_memoised(self, monkeypatch):
        """A failing ensure must not re-run — it can be a multi-hour build."""
        calls = []
        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *a: calls.append(a) or False)
        for _ in range(3):
            with pytest.raises(ou.OntologyDbUnavailableError):
                ou.get_ontology_adapter("ec")
        assert len(calls) == 1, "the failed ensure should have been cached"

    def test_success_is_memoised(self, monkeypatch):
        """Repeat calls reuse the adapter rather than re-ensuring."""
        calls = []
        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *a: calls.append(a) or True)
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: object())
        first, second = ou.get_ontology_adapter("go"), ou.get_ontology_adapter("go")
        assert first is second
        assert len(calls) == 1


class TestLazyResolution:

    """
    Adapters must cost nothing until they are used.

    Transforms build theirs in __init__. Resolving eagerly meant that merely
    *constructing* a transform raised when a DB was absent — which failed every
    transform-constructor test in CI, where data/raw is empty — and could kick
    off a multi-hour semsql build before the transform did any work.
    """

    @pytest.fixture(autouse=True)
    def _clear(self):
        """Drop memoised adapters between tests."""
        ou.get_ontology_adapter.cache_clear()
        yield
        ou.get_ontology_adapter.cache_clear()

    def test_construction_touches_nothing(self, monkeypatch):
        """Building the proxy must not ensure, gate, or open anything."""
        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *_: pytest.fail("ensured too early"))
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: pytest.fail("opened too early"))
        ou.get_ncbitaxon_adapter()
        ou.get_go_adapter()
        ou.get_ec_adapter()
        ou.get_chebi_adapter()

    def test_construction_survives_a_missing_db(self, tmp_path, monkeypatch):
        """The CI regression: no DB on disk must not break construction."""
        monkeypatch.setattr("kg_microbe.transform_utils.constants.NCBITAXON_SOURCE", tmp_path / "ncbitaxon.owl")
        monkeypatch.setattr(ou.shutil, "which", lambda _: None)  # cannot build
        adapter = ou.get_ncbitaxon_adapter()  # must not raise
        with pytest.raises(ou.OntologyDbUnavailableError):
            adapter.resolve()  # only now

    def test_first_use_resolves_and_forwards(self, monkeypatch):
        """Attribute access resolves once and delegates to the real adapter."""
        calls = []

        class FakeAdapter:

            """Stand-in with one identifiable method."""

            def basic_search(self, term):
                """Return a fixed hit."""
                return [f"hit:{term}"]

        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *a: calls.append(a) or True)
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: FakeAdapter())

        proxy = ou.get_go_adapter()
        assert calls == [], "still untouched"
        assert proxy.basic_search("x") == ["hit:x"]
        assert len(calls) == 1
        proxy.basic_search("y")
        assert len(calls) == 1, "resolution must happen once"

    def test_chebi_alias_still_resolves(self, monkeypatch):
        """ChebiDbUnavailableError is kept as an alias for existing callers."""
        assert ou.ChebiDbUnavailableError is ou.OntologyDbUnavailableError
