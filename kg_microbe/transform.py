"""Transform module."""

import inspect
import traceback
from functools import cached_property
from importlib import import_module
from pathlib import Path
from typing import Any, List, Optional

from kg_microbe.transform_utils.constants import (
    BACDIVE,
    BACTOTRAITS,
    BAKTA,
    COG,
    GOLD,
    GTDB,
    KEGG,
    LPSN_API_SOURCE,
    LPSN_SOURCE,
    MADIN_ETAL,
    MEDIADIVE,
    METATRAITS,
    METATRAITS_GTDB,
    MICROBEDECODER,
    ONTOLOGIES,
    ONTOLOGIES_STUBS,
    PREGO,
    RHEAMAPPINGS,
)
from kg_microbe.utils.transform_fingerprint import write_fingerprint


class LazyTransform:
    """Resolve one transform class only when it is used."""

    def __init__(self, dotted_path: str) -> None:
        """Store the import path without importing its module."""
        self.dotted_path = dotted_path

    @cached_property
    def transform_class(self):
        """Import and return the registered transform class."""
        module_name, class_name = self.dotted_path.rsplit(".", 1)
        return getattr(import_module(module_name), class_name)

    def __call__(self, *args: Any, **kwargs: Any):
        """Construct the underlying transform class."""
        return self.transform_class(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """
        Expose class attributes, treating unavailable modules as absent metadata.

        Registry inspection uses normal ``getattr(proxy, name, default)``
        semantics. Converting an import failure to ``AttributeError`` lets that
        default work in a partial/offline environment, while ``__call__`` still
        raises the original import error when the transform is actually run.
        """
        try:
            transform_class = self.transform_class
        except ImportError as error:
            raise AttributeError(f"{self.dotted_path} is unavailable") from error
        return getattr(transform_class, name)


DATA_SOURCES = {
    # "DrugCentralTransform": DrugCentralTransform,
    # "OrphanetTransform": OrphanetTransform,
    # "OMIMTransform": OMIMTransform,
    # "ReactomeTransform": ReactomeTransform,
    # "GOCAMTransform": GOCAMTransform,
    # "TCRDTransform": TCRDTransform,
    # "ProteinAtlasTransform": ProteinAtlasTransform,
    # "STRINGTransform": STRINGTransform,
    ONTOLOGIES: LazyTransform("kg_microbe.transform_utils.ontologies.ontologies_transform.OntologiesTransform"),
    # Run ontologies_stubs after ontologies so the SemSQL DBs are present and
    # so the stub-node TSVs land in data/transformed/ontologies_stubs/ before
    # the merge step picks them up.
    ONTOLOGIES_STUBS: LazyTransform(
        "kg_microbe.transform_utils.ontologies_stubs.ontologies_stubs_transform.OntologiesStubsTransform"
    ),
    BACDIVE: LazyTransform("kg_microbe.transform_utils.bacdive.bacdive.BacDiveTransform"),
    BAKTA: LazyTransform("kg_microbe.transform_utils.bakta.bakta.BaktaTransform"),
    COG: LazyTransform("kg_microbe.transform_utils.cog.cog.COGTransform"),
    GTDB: LazyTransform("kg_microbe.transform_utils.gtdb.gtdb.GTDBTransform"),
    KEGG: LazyTransform("kg_microbe.transform_utils.kegg.kegg.KEGGTransform"),
    LPSN_SOURCE: LazyTransform("kg_microbe.transform_utils.lpsn.lpsn.LPSNTransform"),
    LPSN_API_SOURCE: LazyTransform("kg_microbe.transform_utils.lpsn_api.lpsn_api.LPSNAPITransform"),
    MEDIADIVE: LazyTransform("kg_microbe.transform_utils.mediadive.mediadive.MediaDiveTransform"),
    MADIN_ETAL: LazyTransform("kg_microbe.transform_utils.madin_etal.madin_etal.MadinEtAlTransform"),
    METATRAITS: LazyTransform("kg_microbe.transform_utils.metatraits.metatraits.MetaTraitsTransform"),
    METATRAITS_GTDB: LazyTransform(
        "kg_microbe.transform_utils.metatraits_gtdb.metatraits_gtdb.MetaTraitsGTDBTransform"
    ),
    RHEAMAPPINGS: LazyTransform("kg_microbe.transform_utils.rhea_mappings.rhea_mappings.RheaMappingsTransform"),
    BACTOTRAITS: LazyTransform("kg_microbe.transform_utils.bactotraits.bactotraits.BactoTraitsTransform"),
    # Run gold after ontologies: it reads ncbitaxon_nodes.tsv to apply the
    # NCBITaxon trim, so GOLD cannot reintroduce excluded branches. Set
    # GOLD_APPLY_TAXON_TRIM=false to ingest unfiltered.
    GOLD: LazyTransform("kg_microbe.transform_utils.gold.gold.GOLDTransform"),
    MICROBEDECODER: LazyTransform("kg_microbe.transform_utils.microbedecoder.microbedecoder.MicrobeDecoderTransform"),
    PREGO: LazyTransform("kg_microbe.transform_utils.prego.prego.PregoTransform"),
    # UNIPROT_HUMAN: UniprotHumanTransform,
    # CTD: CTDTransform,
    # DISBIOME: DisbiomeTransform,
    # WALLEN_ETAL: WallenEtAlTransform,
    # UNIPROT_FUNCTIONAL_MICROBES: UniprotFunctionalMicrobesTransform,
}


class TransformBatchError(RuntimeError):
    """
    One or more sources in a batch failed; raised after the others ran.

    Carries ``failed`` (source -> exception) and ``skipped`` (source -> the
    upstream sources it declares in ``TRANSFORM_INPUTS`` that failed first),
    and renders both, so the exit is non-zero and the summary is unmissable.
    """

    def __init__(self, failed: dict, skipped: dict):
        """Render the per-source outcome into the message."""
        self.failed = failed
        self.skipped = skipped
        lines = [f"{len(failed)} transform(s) failed" + (f", {len(skipped)} skipped" if skipped else "")]
        for source, exc in failed.items():
            lines.append(f"  failed:  {source}: {type(exc).__name__}: {exc}")
        for source, upstream in skipped.items():
            lines.append(f"  skipped: {source}: upstream {', '.join(upstream)} did not complete")
        super().__init__("\n".join(lines))


def _ontology_map() -> dict:
    """Return ONTOLOGIES_MAP, imported lazily so ``kg --help`` stays light."""
    from kg_microbe.transform_utils.ontologies.ontologies_transform import ONTOLOGIES_MAP

    return ONTOLOGIES_MAP


def _missing_declared_inputs(sources: List[str], repo_root: Path) -> List[str]:
    """
    Return ``"source: path"`` for every declared curation input that is absent.

    Checked before any source runs (#685): a missing prerequisite should fail
    in seconds, not after the hours of upstream work that precede it in the
    batch. Only ``DATA_INPUTS`` can be checked this way -- raw downloads are
    not declared per transform.
    """
    missing = []
    for source in sources:
        cls = DATA_SOURCES.get(source)
        for rel in getattr(cls, "DATA_INPUTS", ()) if cls is not None else ():
            if not (repo_root / rel).exists():
                missing.append(f"{source}: {rel}")
    return missing


def _run_one(source: str, input_dir: Optional[Path], output_dir: Optional[Path], show_status: bool) -> None:
    """Run one registered source, or one ontology by name, and report what it wrote."""
    if source in DATA_SOURCES:
        t = DATA_SOURCES[source](input_dir, output_dir)
        t.run(show_status=show_status)
        written = _describe_output(t, source)
        # After the outputs, so a run that dies partway leaves no marker
        # claiming its output matches the current inputs. Central here rather
        # than in each transform: every source gets it, and none can forget.
        _record_fingerprint(t, source)
        print(f"[transform] {source}: done — {written}", flush=True)
        return

    # A single ontology (#690). OntologiesTransform.run(data_file) has always
    # scoped to one file; the CLI branch meant to reach it tested a source
    # name against ONTOLOGIES_MAP, whose keys never overlapped DATA_SOURCES.
    t = DATA_SOURCES[ONTOLOGIES](input_dir, output_dir)
    t.run(_ontology_map()[source], show_status=show_status)
    written = _describe_output(t, source, file_prefix=f"{source}_")
    # Deliberately no fingerprint: the marker covers the whole ontologies
    # directory, and one refreshed ontology does not make the other thirteen
    # current. The existing marker stays, and reads STALE if the code moved.
    print(f"[transform] {source}: done — {written} (single ontology; ontologies fingerprint not updated)", flush=True)


def transform(
    input_dir: Optional[Path],
    output_dir: Optional[Path],
    sources: List[str] = None,
    show_status: bool = True,
) -> None:
    """
    Transform based on resource and class declared in DATA_SOURCES.

    Call scripts in kg_microbe/transform/[source name]/ to
    transform each source into a graph format that
    KGX can ingest directly, in either TSV or JSON format:
    https://github.com/biolink/kgx/blob/master/data-preparation.md

    :param input_dir: A string pointing to the directory to import data from.
    :param output_dir: A string pointing to the directory to output data to.
    :param sources: A list of sources to transform. A registered source name,
        or one ontology name from ``ONTOLOGIES_MAP`` (``ec``, ``chebi``, ...)
        to refresh that ontology alone (#690).
    :raises ValueError: If a requested source is not registered in DATA_SOURCES.
    :raises FileNotFoundError: If a selected source declares a curation input
        that is not on disk; nothing runs (#685).
    :raises TransformBatchError: After the batch, if any source failed. A
        failure is isolated to its source: later sources still run unless
        they declare the failed one in ``TRANSFORM_INPUTS``, in which case they
        are skipped rather than built on stale upstream output (#685).
        ``BaseException`` (``FatalOntologyError``, Ctrl-C) still aborts at once.
    """
    if not sources:
        # run all sources
        sources = list(DATA_SOURCES.keys())

    # Refuse an unknown source instead of skipping it. The old loop guarded with
    # `if source in DATA_SOURCES:` and had no else, so a typo produced exit 0 and
    # no output — indistinguishable from a successful run, and from a transform
    # that died early (#813).
    unknown = [s for s in sources if s not in DATA_SOURCES]
    ontology_names: List[str] = []
    if unknown:
        ontology_names = sorted(_ontology_map())
        unknown = [s for s in unknown if s not in ontology_names]
    if unknown:
        raise ValueError(
            f"Unknown transform source(s): {', '.join(sorted(unknown))}. "
            f"Registered sources: {', '.join(sorted(DATA_SOURCES))}; "
            f"single ontologies: {', '.join(ontology_names)}"
        )

    missing = _missing_declared_inputs(sources, Path(__file__).resolve().parent.parent)
    if missing:
        raise FileNotFoundError("Declared curation input(s) missing; nothing was run: " + "; ".join(missing))

    failed: dict = {}
    skipped: dict = {}
    # Names a later source may declare in TRANSFORM_INPUTS that did not
    # complete. A single ontology failing counts as `ontologies` failing:
    # gold and prego declare the directory, not the ontology inside it.
    unavailable: set = set()
    for source in sources:
        upstream = [u for u in getattr(DATA_SOURCES.get(source), "TRANSFORM_INPUTS", ()) if u in unavailable]
        if upstream:
            skipped[source] = upstream
            unavailable.add(source)
            print(f"[transform] {source}: skipped — upstream {', '.join(upstream)} did not complete", flush=True)
            continue
        # print, not logging.info: the CLI does not configure a handler that
        # shows INFO, so the old log line was invisible and a run that produced
        # nothing looked identical to one that worked.
        print(f"[transform] {source}: starting", flush=True)
        try:
            _run_one(source, input_dir, output_dir, show_status)
        except Exception as exc:  # noqa: BLE001 - isolate one source; BaseException still aborts the batch
            failed[source] = exc
            unavailable.add(source)
            if source not in DATA_SOURCES:
                unavailable.add(ONTOLOGIES)
            print(f"[transform] {source}: FAILED — {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()

    if failed:
        raise TransformBatchError(failed, skipped)


def _record_fingerprint(transform_obj, source: str) -> None:
    """
    Record what produced this output, for content-based freshness checks.

    Timestamps do not survive routine git operations — `git checkout` rewrites
    an mtime with no content change (#797), and a squash merge advances commit
    time for content that already existed (#836). Both produced false "stale"
    verdicts on output that was byte-for-byte current.

    Best-effort: a transform that ran successfully must not be reported as
    failed because bookkeeping could not be written. A missing marker degrades
    to the timestamp comparison, which is what every consumer did before.

    :param transform_obj: The transform that just ran.
    :param source: Registered source name.
    """
    try:
        code_dir = Path(inspect.getsourcefile(type(transform_obj))).parent
        write_fingerprint(
            output_dir=transform_obj.output_dir,
            code_dir=code_dir,
            repo_root=Path(__file__).resolve().parent.parent,
            data_inputs=getattr(type(transform_obj), "DATA_INPUTS", ()),
            transform_inputs=getattr(type(transform_obj), "TRANSFORM_INPUTS", ()),
        )
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not fail the run
        print(f"[transform] {source}: could not record fingerprint ({exc})", flush=True)


def _describe_output(transform_obj, source: str, file_prefix: str = "") -> str:
    """
    Summarise what a transform actually wrote, for the completion line.

    Reports row counts rather than "done", because the failure this guards
    against is a run that completes without producing anything (#813).

    :param transform_obj: The Transform instance that just ran.
    :param source: Source name, used when the instance exposes no output dir.
    :param file_prefix: Count only ``<prefix>nodes.tsv`` / ``<prefix>edges.tsv``;
        a single-ontology run must not report the whole ontologies directory.
    :return: Human-readable summary of the files written.
    """
    out_dir = getattr(transform_obj, "output_dir", None)
    if out_dir is None:
        return f"no output_dir attribute on {source} transform"
    # Every `*nodes.tsv` / `*edges.tsv`, not the two literal names: the
    # ontologies transform writes `<ontology>_nodes.tsv` per ontology and the
    # stub transform does the same, so the literal check reported a successful
    # 415 MB, 28-file run as "wrote no nodes.tsv/edges.tsv" -- the inverse of
    # what the guard is for (#949).
    parts = []
    for kind in ("nodes", "edges"):
        files = sorted(Path(out_dir).glob(f"{file_prefix or '*'}{kind}.tsv"))
        if not files:
            continue
        counted = []
        for path in files:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    counted.append((path.name, max(sum(1 for _ in handle) - 1, 0)))
            except OSError as exc:  # pragma: no cover - unreadable output is rare
                parts.append(f"{path.name} unreadable ({exc})")
        if len(counted) == 1:
            name, rows = counted[0]
            parts.append(f"{name}: {rows:,} rows")
        elif counted:
            total = sum(rows for _, rows in counted)
            parts.append(f"{len(counted)} {kind} files: {total:,} rows")
    return "; ".join(parts) if parts else f"wrote no *nodes.tsv/*edges.tsv in {out_dir}"
