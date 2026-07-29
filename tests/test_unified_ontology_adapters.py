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
import re
import time
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _source_texts():
    """
    Read every scanned file once, as (path, text) pairs.

    Each guard assertion used to re-read and re-parse the whole tree; the file
    set does not change during a run, so it is read once and the parses are
    memoised on content.

    :return: Tuple of (Path, str) for every file the guard covers.
    """
    return tuple(
        (path, path.read_text(encoding="utf-8"))
        for root in SEARCH_ROOTS
        if root.exists()
        for path in sorted(root.rglob("*.py"))
    )


def _iter_sources():
    """Yield every .py file the guard covers."""
    for path, _ in _source_texts():
        yield path


@lru_cache(maxsize=1)
def _unparsable_sources():
    """Return the set of scanned files the AST parser cannot handle."""
    unparsable = set()
    for path, text in _source_texts():
        try:
            _parsed(text)
        except SyntaxError:
            unparsable.add(str(path.relative_to(REPO_ROOT)))
    return unparsable


def _get_adapter_calls():
    """Yield (relpath, lineno, arg-node, enclosing-source) for get_adapter calls."""
    for path, text in _source_texts():
        try:
            tree = _parsed(text)
        except SyntaxError:
            # Some scripts/ files use syntax newer than the project's Python
            # (e.g. nested same-quote f-strings, 3.12+). They cannot be scanned
            # here; test_unparsable_files_are_known keeps that list from growing.
            continue
        # `from oaklib import get_adapter as ga` then `ga(...)` was invisible to
        # a name-only match, so an aliased import could reintroduce the pattern
        # with the guard still green.
        aliases = {"get_adapter"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "get_adapter" and alias.asname:
                        aliases.add(alias.asname)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in aliases or not node.args:
                continue
            yield path.relative_to(REPO_ROOT), node.lineno, node.args[0], text


def _string_constants(node):
    """
    Yield every string literal inside an expression.

    Matching on the rendered source segment alone is defeatable by splitting the
    filename across a concatenation — `RAW_DATA_DIR / ("go" + ".owl")` contains
    no contiguous "go.owl" in either the source text or the AST dump, so it
    passed the old check. Looking at the literals individually means the ".owl"
    fragment is caught however the path is assembled.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub.value


def _reaches_suffix(node, source, suffix, _seen=None):
    """
    Report whether an expression reaches a path with ``suffix``.

    Follows three kinds of indirection within the file, so neither an
    intermediate variable nor a helper launders the path: assignment to a plain
    name, tuple-unpacking assignment, and a call to a locally defined function
    (whose ``return`` expressions are then checked). ``_seen`` breaks cycles.
    """
    if any(suffix in const for const in _string_constants(node)):
        return True
    _seen = _seen if _seen is not None else set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id not in _seen:
            _seen.add(sub.id)
            for assigned in _assignments_of_node(sub.id, source):
                if _reaches_suffix(assigned, source, suffix, _seen):
                    return True
        if isinstance(sub, ast.Call):
            called = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
            if called and called not in _seen:
                _seen.add(called)
                for returned in _returns_of(called, source):
                    if _reaches_suffix(returned, source, suffix, _seen):
                        return True
    return False


def _textual_offenders(text):
    """
    Return 1-indexed lines where a regex scan sees get_adapter handed an OWL.

    Used for files the AST parser cannot handle. Factored out so the scan can be
    exercised against content that *does* contain an offender — asserting the
    real tree has none proves nothing about whether the scan works.
    """
    hits = []
    for match in re.finditer(r"get_adapter\s*\(([^)]*)\)", text):
        arg = match.group(1)
        if ".owl" in arg or any(c in arg for c in OWL_SOURCE_NAMES):
            hits.append(text[: match.start()].count("\n") + 1)
    return hits


def _function_is_aliased(func_name, tree):
    """
    Report whether a function is referenced other than by a direct call.

    Any such reference can hide a call from the name match in
    :func:`_is_db_shaped_parameter`, so a db-shaped parameter in that function
    cannot be vouched for.

    Enumerating binding forms was the wrong approach: successive rounds added
    assignment, tuple targets, dict storage, ``setattr``, closures, decorators,
    default arguments, walrus, augmented assignment and for-targets, and a
    review still found ``register([helper])``, ``@helper class C`` and a
    generator expression slipping past. So the test is inverted — walk every
    bare reference in the module and exclude only the two that cannot hide a
    call: the callee of a direct call, and the receiver of an attribute access.
    Anything else counts.

    Deliberately conservative and file-scoped. Being wrong that way fails a
    test, which someone reads; being wrong the other way lets an unguarded
    ontology build reach production silently.

    :param func_name: Name of the function to look for.
    :param tree: Parsed module.
    :return: True if the function is referenced other than by direct call.
    """
    benign = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name:
            benign.add(id(node.func))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == func_name:
            # `helper.cache_clear` reaches an attribute and cannot hide a call.
            # `helper.__call__(...)` invokes the function itself, so the argument
            # is passed straight through — excluding it let an OWL source reach
            # get_adapter with the guard still green.
            if node.attr != "__call__":
                benign.add(id(node.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == func_name and id(node) not in benign:
            # The def itself is not a reference; FunctionDef carries the name as
            # a plain string, so nothing to exclude there.
            return True
    return False


def _calls_exactly(node, func_name):
    """
    Report whether the expression calls exactly ``func_name``.

    Substring matching on the rendered segment is not enough: a helper named
    ``evil_ontology_db_path`` contains the sanctioned name and was accepted on
    that basis alone.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            called = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
            if called == func_name:
                return True
    return False


@lru_cache(maxsize=None)
def _parsed(source):
    """
    Parse a source string once.

    The guard walks assignments, returns, parameters and callers, each of which
    used to re-parse the whole file: five adapter calls cost 233 ast.parse
    invocations and the suite spent 40s here.

    :param source: File contents.
    :return: The parsed module.
    """
    return ast.parse(source)


def _returns_of(func_name, source):
    """Yield every returned expression of a function defined in this file."""
    for node in ast.walk(_parsed(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None:
                    yield sub.value


def _mentions_owl(node, source):
    """
    Report whether an argument expression reaches an ontology OWL.

    Covers an aliased import, a bare literal path, an intermediate variable, a
    path built from RAW_DATA_DIR, and — since the guard was shown to be
    bypassable — a filename split across a string concatenation.
    """
    rendered = ast.dump(node)
    if any(f"'{const}'" in rendered for const in OWL_SOURCE_NAMES):
        return True
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            for assigned in _assignments_of(sub.id, source):
                if any(f"'{c}'" in assigned or c in assigned for c in OWL_SOURCE_NAMES):
                    return True
    return _reaches_suffix(node, source, ".owl")


def _is_db_shaped_parameter(node, source):
    """
    Report whether the expression is a db-named function parameter.

    ``get_adapter(f"sqlite:{db_path}")`` inside a helper whose caller supplies
    ``db_path`` cannot be resolved to a literal by static walking. Rather than
    trust any name containing "db" — which is what let an OWL through before —
    this only fires for names that are genuinely parameters of a function in the
    file, and only after the ``.owl`` check has already cleared the expression.

    Two ways this was still bypassable, both now closed: the parameter's
    *default* could be an OWL constant, and a caller in the same file could pass
    one in positionally or by keyword.
    """
    names = {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}
    if not names or not all("db" in name for name in names):
        return False
    tree = _parsed(source)
    owning = {}
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = func.args
            positional = [*args.posonlyargs, *args.args]
            for arg in [*positional, *args.kwonlyargs]:
                owning.setdefault(arg.arg, []).append(func)
            # A default that reaches an OWL disqualifies the parameter outright.
            for default in [*args.defaults, *[d for d in args.kw_defaults if d is not None]]:
                if _mentions_owl(default, source):
                    return False
    if not names <= set(owning):
        return False
    # Follow same-file callers: helper(GO_SOURCE) must not launder the path.
    for name in names:
        for func in owning[name]:
            positional = [*func.args.posonlyargs, *func.args.args]
            index = next((i for i, a in enumerate(positional) if a.arg == name), None)
            for call in ast.walk(tree):
                if not isinstance(call, ast.Call):
                    continue
                called = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if called != func.name:
                    continue
                if index is not None and len(call.args) > index and _mentions_owl(call.args[index], source):
                    return False
                for kw in call.keywords:
                    # kw.arg is None for **{...} unpacking, whose contents cannot
                    # be matched to a parameter — treat any OWL inside as reaching
                    # this one rather than waving it through.
                    if (kw.arg == name or kw.arg is None) and _mentions_owl(kw.value, source):
                        return False
            # Aliasing hides the call from the name match above, so any form of
            # it disqualifies the parameter. Plain assignment was covered; an
            # annotated assignment, a tuple assignment and functools.partial
            # were not.
            if _function_is_aliased(func.name, tree):
                return False
    return True


def _assignments_of(name, source):
    """Yield the rendered right-hand side of every assignment to `name`."""
    for value in _assignments_of_node(name, source):
        yield ast.get_source_segment(source, value) or ast.dump(value)


def _assignments_of_node(name, source):
    """
    Yield the right-hand side *node* of every assignment to `name`.

    Includes tuple-unpacking targets (``local_db, _ = _ncbitaxon_db_paths()``),
    which a plain-Name-only match silently skipped — leaving the bound name
    unresolvable and the call unchecked.
    """
    for node in ast.walk(_parsed(source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    yield node.value
                elif isinstance(target, (ast.Tuple, ast.List)):
                    if any(isinstance(el, ast.Name) and el.id == name for el in target.elts):
                        yield node.value


class TestNoUnguardedAdapters:

    """No source file may construct an adapter that points at an OWL."""

    def test_unparsable_files_are_known(self):
        """The scanner skips files it cannot parse; keep that set from growing."""
        assert _unparsable_sources() <= {
            # Pre-existing: uses 3.12+ nested same-quote f-strings, so this is
            # unparsable on 3.10/3.11 and parses fine on 3.12.
            "scripts/validate_knowledge_sources.py",
        }, f"new unparsable files escape the adapter guard: {sorted(_unparsable_sources())}"

    def test_unparsable_files_are_still_scanned_textually(self):
        """
        An allow-listed file must not be a free pass.

        The AST scanner skips what it cannot parse, so anything added to
        scripts/validate_knowledge_sources.py escaped every assertion here. It
        cannot be parsed on 3.10/3.11 — that is why it is listed — so it is
        scanned with a regex instead. Crude, but a hole that only exists on some
        interpreter versions is worse.
        """
        offenders = []
        for path in _iter_sources():
            if str(path.relative_to(REPO_ROOT)) not in _unparsable_sources():
                continue
            text = path.read_text(encoding="utf-8")
            offenders += [f"{path.relative_to(REPO_ROOT)}:{ln}" for ln in _textual_offenders(text)]
        assert offenders == [], f"unparsable file hands an OWL to get_adapter: {offenders}"

    @pytest.mark.parametrize(
        "snippet",
        [
            # Codex's bypass: the filename split across a concatenation, so no
            # contiguous "go.owl" appears in the source text or the AST dump.
            'db_path = RAW_DATA_DIR / ("go" + ".owl")\nget_adapter(f"sqlite:{db_path}")',
            # The same trick with an f-string.
            'p = RAW_DATA_DIR / f"{\'go\'}.owl"\nget_adapter(f"sqlite:{p}")',
            # Direct literal, and via one hop of indirection.
            'get_adapter("sqlite:data/raw/go.owl")',
            'x = "data/raw/chebi.owl"\ny = x\nget_adapter(f"sqlite:{y}")',
            # The named constants.
            'get_adapter(f"sqlite:{GO_SOURCE}")',
        ],
    )
    def test_known_bypasses_are_caught(self, snippet):
        """
        Each of these defeated an earlier version of the guard.

        A guard that can be walked around is worse than none, because it reads
        as coverage. These are pinned so a future simplification cannot quietly
        reopen the hole.
        """
        tree = ast.parse(snippet)
        call = next(
            n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "get_adapter"
        )
        assert _mentions_owl(call.args[0], snippet), f"guard missed: {snippet!r}"

    def test_a_real_db_path_is_not_flagged(self):
        """The guard must not cry wolf over the sanctioned .db spellings."""
        for snippet in (
            "get_adapter(f\"sqlite:{ontology_db_path('go')}\")",
            'db = RAW_DATA_DIR / "go.db"\nget_adapter(f"sqlite:{db}")',
        ):
            tree = ast.parse(snippet)
            call = next(
                n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "get_adapter"
            )
            assert not _mentions_owl(call.args[0], snippet), f"false positive: {snippet!r}"

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

        This once allow-listed whole *files*, so any new call inside one of them
        went unchecked. The replacement then keyed on the argument's source text
        *containing* "db_path", which is just as weak in the other direction:
        naming the variable db_path and pointing it at an OWL bought a pass. The
        check now follows the expression to a real ".db" literal, and separately
        insists it does not also reach an ".owl".
        """
        suspicious = []
        for path, lineno, arg, source in _get_adapter_calls():
            segment = ast.get_source_segment(source, arg) or ""
            # Reaching an OWL disqualifies unconditionally, whatever the argument
            # is named. This conjunct is the part that used to be missing: the
            # name-shaped check alone accepted `db_path = RAW_DATA_DIR /
            # ("go" + ".owl")`, which _mentions_owl now follows and rejects.
            if _mentions_owl(arg, source):
                suspicious.append(f"{path}:{lineno} -> {segment}")
                continue
            if _reaches_suffix(arg, source, ".db"):
                continue
            # ontology_db_path() is the sanctioned indirection: pure path
            # arithmetic over the four DB names, which cannot yield an OWL.
            # Matched as a called name, not a substring — `evil_ontology_db_path()`
            # contains the text and used to be waved through on that alone.
            if _calls_exactly(arg, "ontology_db_path"):
                continue
            # A bare name that is a function parameter cannot be resolved to a
            # literal here. Accepting a db-shaped parameter name is a heuristic,
            # but it is only reached once the .owl check above has passed.
            if _is_db_shaped_parameter(arg, source):
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


class TestResolutionIsSerialised:

    """lru_cache does not lock across the wrapped call (Codex F7)."""

    def test_concurrent_first_use_is_serialised(self, monkeypatch):
        """
        Two threads missing the cache together must not build concurrently.

        Note what this does *not* claim: both threads still call
        _ensure_and_gate. The lock serialises them, so the second runs only
        after the first has finished and takes the cheap reuse fast-path. The
        guarantee is non-overlap, not a single call.

        Without the per-ontology lock both entered _ensure_and_gate and raced
        through .prev move-aside, decompression and `semsql make` on the same
        paths. The barrier below makes that race deterministic rather than
        occasional.
        """
        import threading

        barrier = threading.Barrier(2, timeout=10)
        concurrent = []
        active = []
        active_lock = threading.Lock()

        def slow_ensure(ontology, db_path):
            """Record whether another thread is inside at the same time."""
            with active_lock:
                active.append(1)
                concurrent.append(len(active))
            time.sleep(0.05)
            with active_lock:
                active.pop()
            return True

        monkeypatch.setattr(ou, "_ensure_and_gate", slow_ensure)
        monkeypatch.setattr("oaklib.get_adapter", lambda spec: object())
        ou.get_ontology_adapter.cache_clear()

        def worker():
            """Resolve from a thread, all starting together."""
            barrier.wait()
            ou.get_ontology_adapter("go")

        try:
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
        finally:
            ou.get_ontology_adapter.cache_clear()

        assert max(concurrent) == 1, f"ensure ran concurrently: {concurrent}"

    def test_locks_are_per_ontology(self):
        """A slow NCBITaxon build must not block an unrelated EC resolve."""
        assert ou._adapter_lock("go") is ou._adapter_lock("go")
        assert ou._adapter_lock("go") is not ou._adapter_lock("ec")


class TestGuardBypassesStayClosed:

    """Each of these walked past a previous version of the guard."""

    @pytest.mark.parametrize(
        "snippet",
        [
            # An OWL constant as the parameter's default.
            'def helper(db_path=GO_SOURCE):\n    return get_adapter(f"sqlite:{db_path}")\n',
            # A same-file caller passing one in positionally...
            'def helper(db_path):\n    return get_adapter(f"sqlite:{db_path}")\nhelper(GO_SOURCE)\n',
            # ...or by keyword.
            'def helper(db_path):\n    return get_adapter(f"sqlite:{db_path}")\nhelper(db_path=GO_SOURCE)\n',
            # A helper whose *name contains* the sanctioned indirection.
            'def evil_ontology_db_path():\n    return GO_SOURCE\nget_adapter(f"sqlite:{evil_ontology_db_path()}")\n',
        ],
    )
    def test_parameter_and_lookalike_bypasses_are_caught(self, snippet):
        """A db-shaped parameter name must not launder an OWL path."""
        call = _first_get_adapter(snippet)
        assert not _accepted_by_guard(call, snippet), f"guard let this through: {snippet!r}"

    @pytest.mark.parametrize(
        "snippet",
        [
            'def helper(db_path):\n    return get_adapter(f"sqlite:{db_path}")\nhelper(RAW / "go.db")\n',
            "get_adapter(f\"sqlite:{ontology_db_path('go')}\")\n",
            'db = RAW_DATA_DIR / "go.db"\nget_adapter(f"sqlite:{db}")\n',
        ],
    )
    def test_legitimate_spellings_are_not_flagged(self, snippet):
        """The guard must not cry wolf over the sanctioned .db forms."""
        call = _first_get_adapter(snippet)
        assert _accepted_by_guard(call, snippet), f"false positive: {snippet!r}"

    def test_textual_scanner_actually_detects_an_offender(self):
        """
        The unparsable-file scan must be shown to work, not merely to pass.

        Asserting "no offenders" over a tree that has none is vacuous — the
        assertion held even with the scanner's regex stubbed out to match
        nothing. This drives the same scan over content known to contain one.
        """
        assert _textual_offenders('get_adapter("sqlite:data/raw/go.owl")\nbroken(\n')
        assert _textual_offenders('get_adapter(f"sqlite:{GO_SOURCE}")\nbroken(\n')
        assert not _textual_offenders('get_adapter(f"sqlite:{db_path}")\nbroken(\n')

    def test_textual_scanner_cannot_follow_indirection(self):
        """
        Document what the fallback does *not* catch, rather than imply otherwise.

        The regex only sees the argument text, so a variable assigned an OWL
        elsewhere is invisible to it. That is inherent to scanning a file the
        parser rejected. It is an accepted, bounded gap — it applies solely to
        files in the unparsable allow-list, and `test_unparsable_files_are_known`
        stops that list from growing.
        """
        assert not _textual_offenders('x = GO_SOURCE\nget_adapter(f"sqlite:{x}")\nbroken(\n')


def _first_get_adapter(source):
    """Return the first get_adapter call node in a snippet."""
    return next(
        n for n in ast.walk(_parsed(source)) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "get_adapter"
    ).args[0]


def _accepted_by_guard(arg, source):
    """Replicate the two production assertions' combined verdict for one call."""
    if _mentions_owl(arg, source):
        return False
    return bool(
        _reaches_suffix(arg, source, ".db")
        or _calls_exactly(arg, "ontology_db_path")
        or _is_db_shaped_parameter(arg, source)
    )
