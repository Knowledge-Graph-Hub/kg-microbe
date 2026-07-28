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

REPO_ROOT = Path(__file__).parent.parent
# scripts/ is in scope too: a live offender sat there, in a script the
# chemical-mapping skill tells users to run, and the first version of this guard
# never looked at it.
SEARCH_ROOTS = [REPO_ROOT / "kg_microbe", REPO_ROOT / "scripts"]

# Constants that name an .owl path. Passing one to get_adapter means "build".
OWL_SOURCE_NAMES = {"NCBITAXON_SOURCE", "CHEBI_SOURCE", "GO_SOURCE", "EC_SOURCE"}

# Any spelling of an ontology OWL, however it is arrived at.
OWL_FILENAMES = {"ncbitaxon.owl", "chebi.owl", "go.owl", "ec.owl"}


def _iter_sources():
    """Yield every .py file the guard covers."""
    for root in SEARCH_ROOTS:
        if root.exists():
            yield from root.rglob("*.py")


def _get_adapter_calls():
    """Yield (relpath, lineno, arg-node, enclosing-source) for get_adapter calls."""
    for path in _iter_sources():
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            # Some scripts/ files use syntax newer than the project's Python
            # (e.g. nested same-quote f-strings, 3.12+). They cannot be scanned
            # here; test_unparsable_files_are_known keeps that list from growing.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "get_adapter" or not node.args:
                continue
            yield path.relative_to(REPO_ROOT), node.lineno, node.args[0], text


def _mentions_owl(node, source):
    """
    Report whether an argument expression reaches an ontology OWL.

    Covers the four shapes the name-only check missed: an aliased import, a bare
    literal path, an intermediate variable, and a path built from RAW_DATA_DIR.
    """
    rendered = ast.dump(node)
    if any(f"'{const}'" in rendered for const in OWL_SOURCE_NAMES):
        return True
    try:
        segment = ast.get_source_segment(source, node) or ""
    except Exception:  # noqa: BLE001 — best effort on odd nodes
        segment = ""
    if any(owl in segment for owl in OWL_FILENAMES):
        return True
    # An f-string interpolating a plain Name: resolve that name's assignments.
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            for assigned in _assignments_of(sub.id, source):
                if any(f"'{c}'" in assigned or c in assigned for c in OWL_SOURCE_NAMES):
                    return True
                if any(owl in assigned for owl in OWL_FILENAMES):
                    return True
    return False


def _assignments_of(name, source):
    """Yield the rendered right-hand side of every assignment to `name`."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    yield ast.get_source_segment(source, node.value) or ast.dump(node.value)


class TestNoUnguardedAdapters:

    """No source file may construct an adapter that points at an OWL."""

    def test_unparsable_files_are_known(self):
        """The scanner skips files it cannot parse; keep that set from growing."""
        unparsable = set()
        for path in _iter_sources():
            try:
                ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                unparsable.add(str(path.relative_to(REPO_ROOT)))
        assert unparsable <= {
            # Pre-existing: uses 3.12+ nested same-quote f-strings.
            "scripts/validate_knowledge_sources.py",
        }, f"new unparsable files escape the adapter guard: {sorted(unparsable)}"

    def test_no_module_maps_prefixes_to_owl_sources(self):
        """
        Indirection must not smuggle an OWL path into get_adapter either.

        ner_utils used to map prefixes to GO_SOURCE/CHEBI_SOURCE and interpolate
        the result, which a constant-name check cannot see.
        """
        ner = (REPO_ROOT / "kg_microbe" / "utils" / "ner_utils.py").read_text(encoding="utf-8")
        assert "PREFIX_SOURCE_MAP" not in ner, "map prefixes to ontology keys, not OWL paths"
        assert "GO_SOURCE" not in ner and "CHEBI_SOURCE" not in ner, (
            "ner_utils must not reference OWL source constants at all"
        )

    def test_no_get_adapter_reaches_an_owl(self):
        """
        The regression guard: an OWL here means an unguarded OAK build.

        Checks the rendered argument, its source text, and the assignments behind
        any variable it interpolates — the name-only version passed for aliased
        imports, literal paths and intermediate variables alike.
        """
        offenders = [
            f"{path}:{lineno}" for path, lineno, arg, source in _get_adapter_calls() if _mentions_owl(arg, source)
        ]
        assert offenders == [], (
            "get_adapter must never be handed an OWL path — use "
            f"get_ontology_adapter()/get_*_adapter() instead. Offenders: {offenders}"
        )

    def test_remaining_adapter_calls_take_a_db(self):
        """
        Every direct get_adapter call must name a .db, not an ontology source.

        Previously this allow-listed whole *files*, so any new call inside one of
        them — handed anything at all — went unchecked.
        """
        suspicious = []
        for path, lineno, arg, source in _get_adapter_calls():
            segment = ast.get_source_segment(source, arg) or ""
            if ".db" in segment or "db_path" in segment or "local_db" in segment:
                continue
            suspicious.append(f"{path}:{lineno} -> {segment}")
        assert suspicious == [], f"get_adapter calls not clearly pointing at a .db: {suspicious}"


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

    def test_pickling_does_not_resolve(self, monkeypatch):
        """
        Serialising a proxy must not start a build.

        pickle probes __getstate__ on the instance; answering that from
        __getattr__ resolved the adapter, so merely pickling one could kick off a
        multi-hour semsql build.
        """
        import pickle

        calls = []
        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *a: calls.append(a) or True)
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: object())

        blob = pickle.dumps(ou.get_go_adapter())
        assert calls == [], "pickling must not resolve"
        assert isinstance(pickle.loads(blob), ou._LazyOntologyAdapter)

    def test_copy_does_not_recurse(self, monkeypatch):
        """copy/deepcopy construct without __init__; reading _resolved recursed."""
        import copy as copy_mod

        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *a: True)
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: object())
        proxy = ou.get_go_adapter()
        assert isinstance(copy_mod.copy(proxy), ou._LazyOntologyAdapter)
        assert isinstance(copy_mod.deepcopy(proxy), ou._LazyOntologyAdapter)

    def test_private_names_are_not_forwarded(self, monkeypatch):
        """A private name must raise AttributeError rather than resolve."""
        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *a: pytest.fail("resolved"))
        proxy = ou.get_go_adapter()
        with pytest.raises(AttributeError):
            getattr(proxy, "_not_a_real_attribute")  # noqa: B009 — the point is the lookup

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


class TestFatalErrorsAreNotSwallowed:

    """
    A fatal ontology failure must survive every broad handler in the tree.

    Lazy resolution puts the failure wherever the transform first touches the
    adapter, which is almost always inside a `try` whose `except Exception` was
    written for a per-item lookup miss. Patching those handlers one at a time
    was tried and regressed three times; deriving from BaseException makes it
    structural. Each test below drives the *real* production helper, not a mock
    of it.
    """

    class _Boom:

        """A proxy whose resolution raises, standing in for an unusable DB."""

        def __getattr__(self, name):
            """Fail on any public attribute, as a failed resolution would."""
            if name.startswith("_"):
                raise AttributeError(name)
            raise ou.OntologyVersionMismatchError("strict version mismatch")

    def test_fatal_errors_are_not_exceptions(self):
        """The whole mechanism rests on this: `except Exception` must not match."""
        assert not issubclass(ou.FatalOntologyError, Exception)
        assert issubclass(ou.OntologyDbUnavailableError, ou.FatalOntologyError)
        assert issubclass(ou.OntologyVersionMismatchError, ou.FatalOntologyError)

    def test_chebi_category_bulk_path_does_not_degrade(self):
        """
        get_chebi_category's broad handler swallowed the bulk path's abort.

        The comment claiming "the bulk transform path passes an adapter it built
        itself, so there the failure stays loud" was false once that adapter
        became a lazy proxy: resolution moved inside the try, and every ChEBI row
        fell back to the default category.
        """
        with pytest.raises(ou.FatalOntologyError):
            ou.get_chebi_category("CHEBI:50906", self._Boom())

    def test_chebi_category_survives_pandas_apply(self):
        """The production path is df.apply, which must not absorb it either."""
        import pandas as pd

        with pytest.raises(ou.FatalOntologyError):
            pd.Series([f"CHEBI:{i}" for i in range(5)]).apply(lambda c: ou.get_chebi_category(c, self._Boom()))

    def test_bakta_go_aspect_does_not_default(self):
        """Bakta's handler cached molecular_function for every term instead."""
        from kg_microbe.transform_utils.bakta.utils import get_go_aspect

        cache = {}
        with pytest.raises(ou.FatalOntologyError):
            get_go_aspect("GO:0008150", self._Boom(), cache)
        assert cache == {}, "a fatal failure must not poison the aspect cache"

    def test_get_label_does_not_return_a_bare_id(self):
        """
        A strict-gate abort must not degrade to a bare numeric ID.

        oak_utils.get_label re-raised OntologyDbUnavailableError but not the
        strict-gate abort, which was a plain RuntimeError — so a strict run
        emitted bare numeric IDs as labels for every term.
        """
        from kg_microbe.utils.oak_utils import get_label

        with pytest.raises(ou.FatalOntologyError):
            get_label(self._Boom(), "GO:0008150")

    def test_missing_db_still_degrades_for_standalone_chebi_calls(self, monkeypatch):
        """
        The one deliberate degrade must survive.

        An ad-hoc call with no adapter and no DB falls back to the default
        category rather than aborting.
        """
        monkeypatch.setattr(ou, "get_ontology_adapter", _raiser(ou.OntologyDbUnavailableError("no db")))
        assert ou.get_chebi_category("CHEBI:50906") == "biolink:ChemicalEntity"

    def test_strict_abort_is_not_degraded_even_standalone(self, monkeypatch):
        """...but a version mismatch is a deliberate abort, not a missing DB."""
        monkeypatch.setattr(ou, "get_ontology_adapter", _raiser(ou.OntologyVersionMismatchError("drifted")))
        with pytest.raises(ou.OntologyVersionMismatchError):
            ou.get_chebi_category("CHEBI:50906")

    def test_proxy_is_truthy_without_resolving(self, monkeypatch):
        """
        Truthiness must be deliberate, and must not trigger a build.

        `if not adapter:` guards were dead: implicit dunder lookup goes to the
        type, bypassing __getattr__, so the proxy was truthy by accident. Make
        it truthy on purpose, and never resolve to answer.
        """
        calls = []
        monkeypatch.setattr(ou, "_ensure_and_gate", lambda *a: calls.append(a) or True)
        assert bool(ou.get_chebi_adapter()) is True
        assert calls == [], "truthiness must not start a multi-hour build"


def _raiser(exc):
    """Return a callable that raises ``exc`` (BaseException-safe side_effect)."""

    def _raise(*args, **kwargs):
        """Raise the configured error."""
        raise exc

    return _raise
