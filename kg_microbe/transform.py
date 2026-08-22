"""Transform module."""

import inspect
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
    :param sources: A list of sources to transform.
    :raises ValueError: If a requested source is not registered in DATA_SOURCES.
    """
    if not sources:
        # run all sources
        sources = list(DATA_SOURCES.keys())

    # Refuse an unknown source instead of skipping it. The old loop guarded with
    # `if source in DATA_SOURCES:` and had no else, so a typo produced exit 0 and
    # no output — indistinguishable from a successful run, and from a transform
    # that died early (#813).
    unknown = [s for s in sources if s not in DATA_SOURCES]
    if unknown:
        raise ValueError(
            f"Unknown transform source(s): {', '.join(sorted(unknown))}. "
            f"Registered sources: {', '.join(sorted(DATA_SOURCES))}"
        )

    for source in sources:
        # print, not logging.info: the CLI does not configure a handler that
        # shows INFO, so the old log line was invisible and a run that produced
        # nothing looked identical to one that worked.
        print(f"[transform] {source}: starting", flush=True)
        t = DATA_SOURCES[source](input_dir, output_dir)
        if source == ONTOLOGIES:
            from kg_microbe.transform_utils.ontologies.ontologies_transform import ONTOLOGIES_MAP

        if source == ONTOLOGIES and source in ONTOLOGIES_MAP:
            t.run(ONTOLOGIES_MAP[source])
        else:
            t.run(show_status=show_status)

        written = _describe_output(t, source)
        # After the outputs, so a run that dies partway leaves no marker
        # claiming its output matches the current inputs. Central here rather
        # than in each transform: every source gets it, and none can forget.
        _record_fingerprint(t, source)
        print(f"[transform] {source}: done — {written}", flush=True)


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
        )
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not fail the run
        print(f"[transform] {source}: could not record fingerprint ({exc})", flush=True)


def _describe_output(transform_obj, source: str) -> str:
    """
    Summarise what a transform actually wrote, for the completion line.

    Reports row counts rather than "done", because the failure this guards
    against is a run that completes without producing anything (#813).

    :param transform_obj: The Transform instance that just ran.
    :param source: Source name, used when the instance exposes no output dir.
    :return: Human-readable summary of the files written.
    """
    out_dir = getattr(transform_obj, "output_dir", None)
    if out_dir is None:
        return f"no output_dir attribute on {source} transform"
    parts = []
    for name in ("nodes.tsv", "edges.tsv"):
        path = Path(out_dir) / name
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                rows = max(sum(1 for _ in handle) - 1, 0)
        except OSError as exc:  # pragma: no cover - unreadable output is rare
            parts.append(f"{name} unreadable ({exc})")
            continue
        parts.append(f"{name}: {rows:,} rows")
    return "; ".join(parts) if parts else f"wrote no nodes.tsv/edges.tsv in {out_dir}"
