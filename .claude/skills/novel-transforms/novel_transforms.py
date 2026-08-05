#!/usr/bin/env python3
"""
Refresh ``docs/NOVEL_TRANSFORMS.md`` from the live issue tracker.

See ``.claude/skills/novel-transforms/SKILL.md`` for the full contract. In
brief: query all open issues on ``Knowledge-Graph-Hub/kg-microbe``, classify
each as (novel-source | salvage-from-PR | exploratory | dropped), and emit a
Markdown table sorted by issue number.

Curation is done by editing :data:`MANUAL_INCLUDE` and :data:`MANUAL_EXCLUDE`
at the top of this file — the doc is a pure function of ``(open issues) +
(overrides)``, so tuning either lever + re-running is the whole workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "NOVEL_TRANSFORMS.md"
GH_REPO = "Knowledge-Graph-Hub/kg-microbe"

# ---------------------------------------------------------------------------
# Curation levers. Edit these two sets to steer the classifier.
# ---------------------------------------------------------------------------

# Issue numbers to force-INCLUDE even if the regex classifier rejected them.
# Use when the issue is unambiguously about a new external source but the
# title/body doesn't hit the inclusion regex (e.g. very old issues with
# terse text). Add a one-line comment beside each entry.
MANUAL_INCLUDE: Set[int] = {
    159,  # "thermobase" — one-word title, no verb; unmistakably a new source
    519,  # HGNC salvage (PR #290); UniProt-in-title trips the existing-transform filter
}

# Issue numbers to force-DROP even if the classifier accepted them. Use for
# issues that trip the inclusion regex but really are enhancements to an
# existing transform, infrastructure, or meta / tracking issues.
MANUAL_EXCLUDE: Set[int] = {
    35,  # "microbe-drug interactions" — subsumed by existing CTD transform
    64,  # "UniProt reference proteomes + SwissProt" — existing uniprot_* covers this
    114,  # "ingest the EC hierarchy" — already in ontologies transform
    198,  # "ingest GTDB" — already ingested
    218,  # "disbiome transform … not in transform.py list" — activation, not new
    151,  # "Don't put generic code in this repo" — meta guidance
    373,  # cross-transform infrastructure, not a source
    455,  # "handle bacdive lists" — enhance existing bacdive
    458,  # "METPO predicated for Madin and bactotraits" — mapping infra
    486,  # relative-abundance refactor — model change, not new source
    506,  # metatraits mapping merge — mapping infra
    515,  # metatraits mapping docs — docs
    533,  # download / data-management ergonomics — infra
    543,  # DuckDB query tests — tests
    600,  # merge.yaml lpsn_api credential-gate — infra
    650,  # microbedecoder curation gap — curation, not a new source
    67,  # "sources of microbial culturing media" — exploratory meta, not a source
    69,  # "additional media properties, possibly obsolete" — same
    251,  # duplicate proteomes exclusion — enhancement to uniprot
    252,  # missing bactotraits columns — enhancement to bactotraits
    282,  # bacdive enzyme data without CHEBI — enhance existing bacdive
    283,  # bacdive fatty acid profiles — enhance existing bacdive
    235,  # two subclass edges for strain — bug/enhance
    335,  # DSMZ scraping question — usage question
    337,  # unaccounted_compounds in media — mapping curation
    344,  # NCBI taxonomy usage question
    363,  # mediadive API dependency — infra
    375,  # bacdive pathogenicity — extend existing bacdive
    380,  # madin pathways — extend existing madin_etal
    383,  # dump MediaDive collections — mediadive enhancement
    385,  # mediadive ingredient lookup during download — mediadive enhancement
    386,  # mediadive ingredient groups — mediadive enhancement
    415,  # bacdive.yaml ingest errors — bug in existing
    421,  # madin taxon CURIE — enhance existing madin_etal
    422,  # bacdive taxon-chemical relationships — extend existing bacdive
    473,  # bacdive API download integration — download layer
    480,  # METPO synonym mappings — mapping infra
    513,  # tox codespell cleanup — infra
    536,  # mediadive concentration edge attrs — mediadive enhancement
    6,  # taxon-taxon edges from mondo — extraction from existing mondo, not new source
}

# ---------------------------------------------------------------------------
# Per-source metadata. Cannot be reliably derived from title/body — this is
# curator judgement. Fields:
#   nodes    : rough node-count magnitude as ``10^N`` (string; use "?" if unknown)
#   edges    : rough edge-count magnitude, same convention
#   category : short kebab-case data-shape label from ``DATA_CATEGORIES`` below
# Missing entries render as ``?`` in the doc so a curator can see the gap.
# ---------------------------------------------------------------------------

# Kebab-case category taxonomy. Keep this list tight — every entry needs a
# clear one-line meaning so unrelated sources don't collide under the same
# tag. Add a new category by extending both the tuple and the doc that
# render_markdown prints so downstream readers understand it.
DATA_CATEGORIES: Tuple[str, ...] = (
    "phenotype",  # organism trait observations (growth, morphology, metabolism)
    "genome",  # gene / protein content, functional annotation
    "metabolism",  # pathways, reactions, end-products
    "identity",  # crosswalks, naming registries
    "media",  # growth-media composition
    "environmental",  # habitat, biogeography, distribution
    "ecology",  # inter-organism / host-microbe / microbe-drug interactions
    "fitness",  # gene-essentiality, knockout experiments
    "literature",  # publication associations
)

SOURCE_METADATA: Dict[int, Dict[str, str]] = {
    # Novel bucket
    9: {"nodes": "10^4", "edges": "10^6", "category": "fitness"},  # LBL knockouts
    27: {"nodes": "10^3", "edges": "10^4", "category": "phenotype"},  # Weissman
    33: {"nodes": "10^4", "edges": "10^5", "category": "ecology"},  # gutMEGA
    34: {"nodes": "10^6", "edges": "10^7", "category": "environmental"},  # biogeography
    36: {"nodes": "10^3", "edges": "10^4", "category": "ecology"},  # Web of Microbes
    37: {"nodes": "10^2", "edges": "10^3", "category": "environmental"},  # skin pathobionts
    38: {"nodes": "10^3", "edges": "10^4", "category": "environmental"},  # Microbe Directory
    39: {"nodes": "10^5", "edges": "10^6", "category": "environmental"},  # PREGO (dup of #182)
    41: {"nodes": "10^5", "edges": "10^6", "category": "metabolism"},  # METABOLIC
    42: {"nodes": "10^5", "edges": "10^5", "category": "genome"},  # FusionDB
    44: {"nodes": "10^6", "edges": "10^8", "category": "genome"},  # ProGenomes3
    58: {"nodes": "10^4", "edges": "10^5", "category": "environmental"},  # dbBact
    61: {"nodes": "10^3", "edges": "10^6", "category": "phenotype"},  # protraits
    66: {"nodes": "10^4", "edges": "10^5", "category": "identity"},  # ATCC strains
    132: {"nodes": "10^4", "edges": "10^4", "category": "identity"},  # Names4Life
    140: {"nodes": "10^4", "edges": "10^5", "category": "ecology"},  # BugSigDB
    141: {"nodes": "10^3", "edges": "10^4", "category": "phenotype"},  # bugbase
    154: {"nodes": "10^3", "edges": "10^4", "category": "genome"},  # ATCC genomes
    159: {"nodes": "10^2", "edges": "10^3", "category": "phenotype"},  # thermobase
    177: {"nodes": "10^5", "edges": "10^6", "category": "environmental"},  # microbeatlas
    182: {"nodes": "10^5", "edges": "10^6", "category": "environmental"},  # PREGO
    304: {"nodes": "10^5", "edges": "10^5", "category": "identity"},  # GOLD
    320: {"nodes": "10^3", "edges": "10^4", "category": "media"},  # togomedium
    329: {"nodes": "10^2", "edges": "10^3", "category": "media"},  # CRBIP
    369: {"nodes": "10^2", "edges": "10^3", "category": "media"},  # gut microbe media
    419: {"nodes": "10^3", "edges": "10^4", "category": "media"},  # MediaDB
    478: {"nodes": "10^3", "edges": "10^4", "category": "phenotype"},  # LASER (antibiotic resistance)
    537: {"nodes": "10^4", "edges": "10^5", "category": "phenotype"},  # bac2feature
    # Salvage bucket
    518: {"nodes": "10^8", "edges": "10^9", "category": "genome"},  # UniRef90
    519: {"nodes": "10^4", "edges": "10^5", "category": "identity"},  # HGNC
    520: {"nodes": "10^4", "edges": "10^5", "category": "phenotype"},  # IJSEM
    # Exploratory bucket
    321: {"nodes": "10^3", "edges": "10^3", "category": "identity"},  # periodic table of bacteria
    569: {"nodes": "10^5", "edges": "10^6", "category": "environmental"},  # nmdc.cn
}

# ---------------------------------------------------------------------------
# Inclusion signals (regex). Case-insensitive.
# ---------------------------------------------------------------------------

# Verbs that signal "we want to ingest something new".
INCLUSION_VERBS = re.compile(
    r"\b("
    r"ingest|"
    r"add\s+.*?transform|"
    r"add\s+.*?data\s*source|"
    r"add\s+.*?dataset|"
    r"add\s+.*?database|"
    r"explore\s+.*?data|"
    r"explore\s+.*?db|"
    r"integrate\s+.*?(api|dataset|source)"
    r")",
    re.IGNORECASE,
)

# Named external DBs / datasets. Match wins even if no verb is present
# (covers one-word titles like #159 "thermobase").
EXTERNAL_DB_NAMES = re.compile(
    r"\b("
    r"thermobase|nmdc(?:\.cn)?|patric|silva|greengenes|refseq|mibig|reactome|"
    r"eggnog|ijsem|hgnc|uniref|laser|bac2feature|mediadb|europmc|imgm|jgi|"
    r"earthmicrobiome|omnipath|bacmap|proksee|antismash|resfinder|"
    r"bugsigdb|bugbase|protraits|dbbact|fusiondb|progenomes\d*|weissman|"
    r"gutmega|microbeatlas|prego|names4life|atcc|togomedium|crbip|"
    r"microbe\s*directory|metabolic\s+(?:genomic|source)|"
    r"gene\s+knockout|fitness\s+experiments|periodic\s+table\s+of\s+bacteria|"
    r"pathobionts|gutmicrobiotadb|megares|microbiome\s+datahub|"
    r"skin\s+sites|gut\s+microbe\s+media|gold\s+ingest|"
    r"web\s+of\s+microbes"
    r")",
    re.IGNORECASE,
)

# Exclusion signals — titles whose primary subject is an existing transform.
# The classifier drops an issue if its TITLE (not body) mentions any of these
# names as a leading term (e.g. "ingest bacdive taxon-chemical …" → drop
# because bacdive is the primary subject). Body mentions are OK.
EXISTING_TRANSFORM_TITLE_TERMS = (
    "bacdive",
    "mediadive",
    "madin",
    "metatraits",
    "bactotraits",
    "lpsn",
    "microbedecoder",
    "rhea_mappings",
    "kegg",
    "gtdb",
    "bakta",
    "cog",
    "ctd",
    "disbiome",
    "wallen",
    "ontologies",
    "uniprot",
)

# Salvage pattern used since March 2026.
SALVAGE_PATTERN = re.compile(r"salvaged?\s+from\s+.*?PR\s*#?(\d+)", re.IGNORECASE)

# Exploratory verb.
EXPLORE_PATTERN = re.compile(r"^\s*explore\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """One open GitHub issue in the classifier's view."""

    number: int
    title: str
    body: str
    url: str
    bucket: str = "novel"  # novel | salvage | exploratory
    salvage_pr: Optional[int] = None
    exclude_reason: Optional[str] = None
    include_reasons: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# gh CLI wrapper
# ---------------------------------------------------------------------------


def _run_gh_json(limit: int) -> List[dict]:
    """Query the tracker for every open issue, return the JSON list."""
    if shutil.which("gh") is None:
        raise SystemExit(
            "[novel-transforms] `gh` CLI not on PATH. Install it and run `gh auth login` before invoking this skill."
        )
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        GH_REPO,
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        "number,title,body,url",
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"[novel-transforms] `gh issue list` failed: {exc.stderr.strip()}\n"
            f"Verify you're authenticated to GitHub with `gh auth status`."
        ) from exc
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _title_hits_existing_transform(title: str) -> Optional[str]:
    """Return the first existing-transform name that dominates the title, if any."""
    lower = title.lower()
    # Split on non-word so "bacdive.yaml" and "madin_etal" both tokenize.
    tokens = re.findall(r"[a-z_]+", lower)
    for term in EXISTING_TRANSFORM_TITLE_TERMS:
        if term in tokens:
            return term
    return None


def classify(raw_issues: Iterable[dict]) -> Tuple[List[Issue], List[Issue]]:
    """
    Split raw issue dicts into (kept, dropped).

    Kept issues carry a populated ``bucket``, ``salvage_pr``, and
    ``include_reasons``. Dropped issues carry an ``exclude_reason`` for the
    ``--verbose`` audit trail.
    """
    kept: List[Issue] = []
    dropped: List[Issue] = []
    for raw in raw_issues:
        iss = Issue(
            number=raw["number"],
            title=raw["title"] or "",
            body=raw["body"] or "",
            url=raw["url"],
        )

        # Manual overrides win over everything.
        if iss.number in MANUAL_EXCLUDE:
            iss.exclude_reason = "MANUAL_EXCLUDE"
            dropped.append(iss)
            continue
        if iss.number in MANUAL_INCLUDE:
            iss.include_reasons.append("MANUAL_INCLUDE")
        else:
            # Automatic classifier: need at least one inclusion signal.
            haystack = f"{iss.title}\n{iss.body}"
            hit_verb = bool(INCLUSION_VERBS.search(haystack))
            hit_name = bool(EXTERNAL_DB_NAMES.search(haystack))
            if not (hit_verb or hit_name):
                iss.exclude_reason = "no inclusion signal (no verb, no named DB)"
                dropped.append(iss)
                continue
            if hit_verb:
                iss.include_reasons.append("verb")
            if hit_name:
                iss.include_reasons.append("named-DB")

            # Then reject if the TITLE is dominated by an existing transform.
            existing = _title_hits_existing_transform(iss.title)
            if existing is not None:
                iss.exclude_reason = f"title dominated by existing transform '{existing}'"
                dropped.append(iss)
                continue

        # Bucket assignment (order matters: salvage beats exploratory).
        salvage_match = SALVAGE_PATTERN.search(iss.title) or SALVAGE_PATTERN.search(iss.body)
        if salvage_match:
            iss.bucket = "salvage"
            iss.salvage_pr = int(salvage_match.group(1))
        elif EXPLORE_PATTERN.search(iss.title):
            iss.bucket = "exploratory"
        else:
            iss.bucket = "novel"

        kept.append(iss)

    kept.sort(key=lambda i: i.number)
    dropped.sort(key=lambda i: i.number)
    return kept, dropped


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _guess_source_name(iss: Issue) -> str:
    """Extract a human-readable source name from the title, best-effort."""
    title = iss.title.strip()
    # If a named DB regex matches, use it as the canonical name (Title-Cased).
    m = EXTERNAL_DB_NAMES.search(title)
    if m:
        return m.group(1)
    # Otherwise strip common leading verbs and quote the rest.
    stripped = re.sub(
        r"^\s*(ingest|add|integrate|explore|fix)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return stripped.split(" from ")[0].split(" for ")[0].strip() or title


def _fmt_scale(power_str: str) -> str:
    """Render ``10^N`` as ``10ⁿ`` using Unicode superscripts for compactness."""
    if not power_str or power_str == "?":
        return "?"
    if not power_str.startswith("10^"):
        return power_str
    superscripts = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
    return "10" + power_str[3:].translate(superscripts)


def _render_bucket(bucket_name: str, issues: List[Issue]) -> str:
    """
    Render one bucket's table (or a 'none' placeholder).

    Columns: #, Source, Category, ~Nodes, ~Edges, Title, Link. Category and
    scale come from :data:`SOURCE_METADATA`; missing entries render as ``?``
    so a curator sees the gap.
    """
    if not issues:
        return "_None open._\n"
    lines = [
        "| # | Source | Category | ~Nodes | ~Edges | One-line | Link |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for iss in issues:
        source = _guess_source_name(iss)
        summary = iss.title.strip().replace("|", "\\|")
        if len(summary) > 80:
            summary = summary[:77] + "…"
        salvage_note = ""
        if iss.bucket == "salvage" and iss.salvage_pr is not None:
            salvage_note = f" _(salvage from PR #{iss.salvage_pr})_"
        meta = SOURCE_METADATA.get(iss.number, {})
        category = meta.get("category", "?")
        nodes = _fmt_scale(meta.get("nodes", "?"))
        edges = _fmt_scale(meta.get("edges", "?"))
        lines.append(
            f"| #{iss.number} | **{source}** | {category} | {nodes} | {edges} | "
            f"{summary}{salvage_note} | [link]({iss.url}) |"
        )
    return "\n".join(lines) + "\n"


def render_markdown(kept: List[Issue], dropped: List[Issue], verbose: bool) -> str:
    """Return the full ``NOVEL_TRANSFORMS.md`` contents."""
    novel = [i for i in kept if i.bucket == "novel"]
    salvage = [i for i in kept if i.bucket == "salvage"]
    exploratory = [i for i in kept if i.bucket == "exploratory"]

    total = len(kept)
    header = (
        "# Novel data source backlog\n\n"
        "<!-- generated by .claude/skills/novel-transforms — do not hand-edit; "
        "edit MANUAL_INCLUDE / MANUAL_EXCLUDE in novel_transforms.py and rerun -->\n\n"
        "Open GitHub issues on `Knowledge-Graph-Hub/kg-microbe` that ask for "
        "the ingest of a **new external data source** — a novel KG-Microbe "
        "transform, distinct from enhancements to a transform that already "
        "exists under `kg_microbe/transform_utils/`.\n\n"
        f"**Currently open:** {total} "
        f"({len(novel)} novel · {len(salvage)} salvage · {len(exploratory)} exploratory)\n\n"
        "How to update this file: run "
        "`poetry run python .claude/skills/novel-transforms/novel_transforms.py`. "
        "The skill queries the live tracker, classifies each open issue, and "
        "rewrites this doc. Tuning is done by editing the "
        "`MANUAL_INCLUDE` / `MANUAL_EXCLUDE` sets at the top of that script; "
        "see `.claude/skills/novel-transforms/SKILL.md` for the full contract.\n\n"
    )

    # Category legend — kept short; every entry in DATA_CATEGORIES should have
    # a one-line meaning here so a reader can decode the table without opening
    # the script.
    category_legend = (
        "**Category legend:** "
        "`phenotype` = organism trait observations · "
        "`genome` = gene/protein content, functional annotation · "
        "`metabolism` = pathways / reactions / end-products · "
        "`identity` = crosswalks, naming registries · "
        "`media` = growth-media composition · "
        "`environmental` = habitat / biogeography / distribution · "
        "`ecology` = inter-organism / host-microbe / microbe-drug interactions · "
        "`fitness` = gene-essentiality / knockout experiments · "
        "`literature` = publication associations.\n\n"
        "**Scale columns** (`~Nodes` / `~Edges`) are curator estimates in "
        "powers of ten — magnitude, not exact count. `?` means the entry "
        "hasn't been sized yet; add a row to `SOURCE_METADATA` in "
        "`novel_transforms.py` to fill it in.\n\n"
    )

    sections = [
        category_legend,
        "## Novel external sources\n\n"
        "New databases, APIs, or datasets that KG-Microbe does not cover yet. "
        "The default bucket — each entry corresponds to a transform directory "
        "that does not exist today.\n\n" + _render_bucket("novel", novel) + "\n",
    ]

    if salvage:
        sections.append(
            "## Salvage from stale PRs\n\n"
            "Issues whose title marks them as recoveries of work-in-progress "
            "PRs that never merged. Same output as the Novel bucket — a new "
            "transform — but with a starting point in git history.\n\n" + _render_bucket("salvage", salvage) + "\n"
        )

    if exploratory:
        sections.append(
            "## Exploratory\n\n"
            "Research-first: someone flagged an external resource worth "
            "understanding before deciding whether to ingest.\n\n" + _render_bucket("exploratory", exploratory) + "\n"
        )

    sections.append(
        "## Not in this list\n\n"
        "- Enhancements to existing transforms (extend `bacdive` to ingest "
        "new columns, refactor `metatraits`, etc.).\n"
        "- Cleanup, infrastructure, security, tooling.\n"
        "- Duplicate / superseded issues that have already been closed with a "
        "cross-reference.\n\n"
        "If an issue you expected to see is missing, either it doesn't hit "
        "the classifier (add it to `MANUAL_INCLUDE`) or it was excluded on "
        "purpose (see `MANUAL_EXCLUDE`). Run with `--verbose` to see the "
        "exclusion trail for every open issue.\n"
    )

    if verbose:
        sections.append("\n---\n\n## Verbose audit — dropped issues\n\n")
        if not dropped:
            sections.append("_All open issues were kept._\n")
        else:
            lines = ["| # | Title | Dropped because |", "|---|---|---|"]
            for iss in dropped:
                title = iss.title.strip().replace("|", "\\|")
                if len(title) > 80:
                    title = title[:77] + "…"
                lines.append(f"| #{iss.number} | {title} | {iss.exclude_reason} |")
            sections.append("\n".join(lines) + "\n")

    return header + "\n".join(sections)


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def render_json(kept: List[Issue], dropped: List[Issue]) -> str:
    """Machine-readable dump for other skills / pipelines."""

    def _asdict(iss: Issue) -> Dict:
        meta = SOURCE_METADATA.get(iss.number, {})
        return {
            "number": iss.number,
            "title": iss.title,
            "url": iss.url,
            "bucket": iss.bucket,
            "salvage_pr": iss.salvage_pr,
            "source_name": _guess_source_name(iss),
            "category": meta.get("category"),
            "nodes_magnitude": meta.get("nodes"),
            "edges_magnitude": meta.get("edges"),
        }

    payload = {
        "repo": GH_REPO,
        "kept": [_asdict(i) for i in kept],
        "dropped": [{"number": i.number, "title": i.title, "reason": i.exclude_reason} for i in dropped],
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse CLI, run classifier, emit output."""
    parser = argparse.ArgumentParser(description="Refresh docs/NOVEL_TRANSFORMS.md from the live issue tracker.")
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Write to stdout instead of overwriting the tracked doc.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON instead of Markdown (implies --print).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include a table of DROPPED issues with the exclusion reason.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Override output path (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Cap on the gh query (default: 1000, effectively 'all open').",
    )
    args = parser.parse_args()

    raw = _run_gh_json(args.limit)
    kept, dropped = classify(raw)

    if args.as_json:
        sys.stdout.write(render_json(kept, dropped) + "\n")
        return 0

    md = render_markdown(kept, dropped, verbose=args.verbose)

    if args.print_only:
        sys.stdout.write(md)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")
    novel_count = sum(1 for i in kept if i.bucket == "novel")
    salvage_count = sum(1 for i in kept if i.bucket == "salvage")
    explore_count = sum(1 for i in kept if i.bucket == "exploratory")
    print(
        f"[novel-transforms] wrote {args.output.relative_to(REPO_ROOT)}: "
        f"{len(kept)} kept "
        f"({novel_count} novel, {salvage_count} salvage, {explore_count} exploratory), "
        f"{len(dropped)} dropped"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
