"""
KG-Microbe path review.

Walk and validate multi-hop semantic paths in transform outputs against the raw
source data. Surfaces critical modeling bugs where the KG does not accurately
represent the underlying observations — cross-contamination, self-loops,
phantom intermediates, false-majority emission, missing paths, cardinality
outliers.

Calibrated against recent fixes:
  - mediadive cross-solution leakage (recipe-vs-raw archetype)
  - metatraits Tier-2 false-majority emission (false-majority archetype)
  - subclass-of acyclicity (subclass-cycles archetype)

Usage:
    poetry run python .claude/skills/kg-path-review/kg_path_review.py <subcommand> [options]

Subcommands:
    walk            Walk outgoing (or incoming) paths from a starting CURIE.
    archetype       Run a named built-in archetype check.

Run with --help on any subcommand for the full option set.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
TRANSFORMED_DIR = REPO_ROOT / "data" / "transformed"
RAW_DIR = REPO_ROOT / "data" / "raw"
MERGED_DIR = REPO_ROOT / "data" / "merged"

# Snapshot/backup directories that historically appeared under data/transformed/
# (e.g. ``merged_20260423_nometatraits``). Treating them as transforms causes
# cardinality to triple-count edges since the same subject ID appears in the
# real transform AND in each snapshot's edges.tsv. The discriminator is a
# leading prefix that's reserved for non-transform output.
NON_TRANSFORM_DIR_PREFIXES: Tuple[str, ...] = ("merged_", "merged-", ".")


def _list_transform_dirs() -> List[str]:
    """Return the names of ``data/transformed/<name>`` directories that look
    like real transform outputs (with an ``edges.tsv``), filtering out merge
    snapshots and dot-dirs that would inflate counts on aggregate archetypes."""
    return sorted(
        d.name
        for d in TRANSFORMED_DIR.iterdir()
        if (d / "edges.tsv").exists()
        and not d.name.startswith(NON_TRANSFORM_DIR_PREFIXES)
    )


def _save_review_artifact(content: str, scope: str, ext: str = "txt") -> Path:
    """Save review output to <skill_dir>/reviews/<YYYYMMDD_HHMMSS>_<scope>.<ext>."""
    out_dir = Path(__file__).parent / "reviews"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w.-]+", "_", scope).strip("_") or "review"
    path = out_dir / f"{ts}_{safe}.{ext}"
    path.write_text(content, encoding="utf-8")
    return path

# Edge column indices for the standard KGX edges.tsv emitted by kg-microbe.
SUBJECT_IDX = 0
PREDICATE_IDX = 1
OBJECT_IDX = 2
RELATION_IDX = 3

# Predicates where self-loops are semantically invalid.
NO_SELF_LOOP_PREDICATES = {
    "biolink:has_part",
    "biolink:produces",
    "biolink:consumes",
    "biolink:subclass_of",
    "biolink:located_in",
    "biolink:has_phenotype",
    "biolink:capable_of",
}

# Cardinality envelopes derived from production data + raw-data baselines.
# Values are (typical_max, anomaly_threshold). Anomalies above the threshold
# are very likely transform bugs.
CARDINALITY_ENVELOPES: Dict[Tuple[str, str], Tuple[int, int]] = {
    ("mediadive.solution:", "biolink:has_part"): (20, 50),
    ("mediadive.medium:", "biolink:has_part"): (8, 20),
    ("NCBITaxon:", "biolink:has_phenotype"): (500, 2000),
    ("NCBITaxon:", "biolink:located_in"): (30, 100),
    ("NCBITaxon:", "biolink:capable_of"): (300, 1500),
}


# ---------------------------------------------------------------------------
# Severity / report types
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    severity: str  # CRITICAL | WARNING | INFO
    archetype: str
    subject: str
    detail: str
    evidence: Optional[str] = None


@dataclass
class Report:
    archetype: str
    findings: List[Finding] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def summary(self) -> str:
        counts: Counter = Counter(f.severity for f in self.findings)
        lines = [f"=== {self.archetype} ==="]
        for k, v in self.stats.items():
            lines.append(f"  stat: {k} = {v}")
        lines.append(
            f"  findings: CRITICAL={counts['CRITICAL']} "
            f"WARNING={counts['WARNING']} INFO={counts['INFO']}"
        )
        return "\n".join(lines)

    def render(self, max_per_severity: int = 10) -> str:
        out = [self.summary()]
        for sev in ("CRITICAL", "WARNING", "INFO"):
            sev_findings = [f for f in self.findings if f.severity == sev]
            if not sev_findings:
                continue
            out.append(f"\n  [{sev}] ({len(sev_findings)} total, showing up to {max_per_severity}):")
            for f in sev_findings[:max_per_severity]:
                out.append(f"    {f.subject}: {f.detail}")
                if f.evidence:
                    out.append(f"      evidence: {f.evidence}")
        return "\n".join(out)


# ---------------------------------------------------------------------------
# Edge / node loaders
# ---------------------------------------------------------------------------


def edges_path(transform: str) -> Path:
    return TRANSFORMED_DIR / transform / "edges.tsv"


def nodes_path(transform: str) -> Path:
    return TRANSFORMED_DIR / transform / "nodes.tsv"


def iter_edges(transform: str, max_rows: Optional[int] = None) -> Iterable[List[str]]:
    """Stream rows from <transform>/edges.tsv (skipping header)."""
    path = edges_path(transform)
    if not path.exists():
        raise FileNotFoundError(f"edges.tsv not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        next(reader, None)  # header
        for i, row in enumerate(reader):
            if max_rows is not None and i >= max_rows:
                break
            if len(row) >= 4:
                yield row


def load_node_labels(transform: str) -> Dict[str, str]:
    """Load id → name map from <transform>/nodes.tsv. Best-effort."""
    path = nodes_path(transform)
    if not path.exists():
        return {}
    labels: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            nid = row.get("id") or row.get("ID")
            name = row.get("name", "")
            if nid:
                labels[nid] = name
    return labels


def build_adjacency(
    transform: str,
    reverse: bool = False,
    predicate_filter: Optional[Set[str]] = None,
) -> Dict[str, List[Tuple[str, str]]]:
    """
    Build {source: [(predicate, target), ...]}.

    With reverse=True the index is keyed on object instead of subject so the
    walker can answer "who points at me?".
    """
    adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for row in iter_edges(transform):
        subj, pred, obj = row[SUBJECT_IDX], row[PREDICATE_IDX], row[OBJECT_IDX]
        if predicate_filter and pred not in predicate_filter:
            continue
        if reverse:
            adj[obj].append((pred, subj))
        else:
            adj[subj].append((pred, obj))
    return adj


# ---------------------------------------------------------------------------
# walk subcommand
# ---------------------------------------------------------------------------


def cmd_walk(args: argparse.Namespace) -> int:
    pred_filter = set(args.predicate) if args.predicate else None
    adj = build_adjacency(args.transform, reverse=args.reverse, predicate_filter=pred_filter)
    labels = load_node_labels(args.transform) if args.with_labels else {}

    lines: List[str] = []

    def emit(s: str = "") -> None:
        lines.append(s)

    emit(f"# walk from {args.start} ({'in' if args.reverse else 'out'}-edges) "
         f"depth={args.depth} fanout={args.max_fanout}")
    if pred_filter:
        emit(f"# predicate filter: {sorted(pred_filter)}")
    emit()

    seen: Set[str] = set()

    def render(node: str, depth: int, prefix: str) -> None:
        label = labels.get(node, "")
        suffix = f"  # {label}" if label else ""
        emit(f"{prefix}{node}{suffix}")
        if depth >= args.depth or node in seen:
            return
        seen.add(node)
        out = adj.get(node, [])[: args.max_fanout]
        for i, (pred, target) in enumerate(out):
            connector = "└─" if i == len(out) - 1 else "├─"
            emit(f"{prefix}  {connector} -[{pred}]->")
            child_prefix = prefix + ("     " if i == len(out) - 1 else "  │  ")
            render(target, depth + 1, child_prefix)

    render(args.start, 0, "")
    rendered = "\n".join(lines)
    print(rendered)

    if not getattr(args, "no_save", False):
        scope = f"walk_{args.transform}_{args.start}"
        saved = _save_review_artifact(rendered, scope, ext="txt")
        print(f"# saved to {saved}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# Archetype: recipe-vs-raw (mediadive)
# ---------------------------------------------------------------------------


def load_mediadive_solutions_raw() -> Dict[str, Dict]:
    path = RAW_DIR / "mediadive" / "solutions.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run `poetry run kg download` to fetch raw mediadive data"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_hydrate_equivalents_fn():
    """Lazy import of ``get_hydrate_equivalents`` from the runtime reader.

    Returns the function (and triggers a one-time mappings load on first
    call), or ``None`` if kg_microbe is not importable from this Python
    environment. The skill stays usable even without the runtime reader
    installed; recipe-vs-raw just falls back to non-hydrate-aware
    cardinality comparison.
    """
    try:
        # Make the kg_microbe package importable when running the skill
        # script directly out of .claude/skills/.
        sys.path.insert(0, str(REPO_ROOT))
        from kg_microbe.utils.chemical_mapping_utils import get_hydrate_equivalents
        return get_hydrate_equivalents
    except Exception:  # noqa: BLE001
        return None


def _hydrate_dedupe_count(curies: Set[str], get_hydrate_equivalents) -> int:
    """Count distinct ingredients, collapsing hydrate-equivalent pairs.

    Two CHEBI CURIEs that the unified SSSOM links via
    ``skos:closeMatch + comment=recipe_equivalent_hydrate`` count as one
    logical ingredient (e.g. CaCl2 anhydrous + CaCl2-2H2O resolve to the
    same recipe slot). Without this collapse, a transform that emits
    both forms inflates the KG out-degree above the raw recipe size and
    trips the cross-contamination cardinality check on a legitimate
    bench-prep substitution.
    """
    if get_hydrate_equivalents is None:
        return len(curies)
    seen: Set[str] = set()
    distinct = 0
    for c in sorted(curies):
        if c in seen:
            continue
        distinct += 1
        seen.add(c)
        for eq in get_hydrate_equivalents(c):
            seen.add(eq)
    return distinct


def archetype_recipe_vs_raw(args: argparse.Namespace) -> Report:
    """
    For every mediadive.solution:N in edges.tsv, compare the KG `has_part`
    object set against the raw recipe in solutions.json[N].

    Hydrate-aware: KG ingredients linked by the unified SSSOM's
    ``skos:closeMatch + comment=recipe_equivalent_hydrate`` rows
    (anhydrous <-> hydrated salt pairs) collapse to a single logical
    slot before the cardinality check, so legitimate bench-prep
    substitutions don't false-positive as cross-contamination.

    Calibrated against the medium-92a cross-contamination bug fixed at
    kg_microbe/transform_utils/mediadive/mediadive.py:943-966.
    """
    report = Report(archetype="recipe-vs-raw (mediadive)")
    sols_raw = load_mediadive_solutions_raw()
    hydrate_fn = _load_hydrate_equivalents_fn()
    report.stats["hydrate_aware"] = 1 if hydrate_fn is not None else 0

    # Accumulate KG out-edges per solution.
    solution_kg: Dict[str, Set[str]] = defaultdict(set)
    self_loop_count = 0
    for row in iter_edges("mediadive"):
        subj, pred, obj = row[SUBJECT_IDX], row[PREDICATE_IDX], row[OBJECT_IDX]
        if not subj.startswith("mediadive.solution:") or pred != "biolink:has_part":
            continue
        if subj == obj:
            self_loop_count += 1
            report.add(
                Finding(
                    severity="WARNING",
                    archetype="recipe-vs-raw",
                    subject=subj,
                    detail="self-loop on has_part",
                    evidence=None,
                )
            )
            continue
        solution_kg[subj].add(obj)

    report.stats["solutions_in_kg"] = len(solution_kg)
    report.stats["self_loops"] = self_loop_count

    # Compare each KG solution against raw.
    raw_compound_ids_per_solution: Dict[str, Set[str]] = {}
    for sid, sol in sols_raw.items():
        recipe = sol.get("recipe") or []
        compound_keys: Set[str] = set()
        for item in recipe:
            cid = item.get("compound_id")
            sub_sid = item.get("solution_id")
            if cid is not None:
                compound_keys.add(f"compound_id:{cid}")
            if sub_sid is not None:
                compound_keys.add(f"mediadive.solution:{sub_sid}")
        raw_compound_ids_per_solution[sid] = compound_keys

    # Check each KG solution.
    contaminated = 0
    for solution_curie, kg_objects in solution_kg.items():
        sid = solution_curie.split(":", 1)[1]
        raw = raw_compound_ids_per_solution.get(sid)
        if raw is None:
            report.add(
                Finding(
                    severity="WARNING",
                    archetype="recipe-vs-raw",
                    subject=solution_curie,
                    detail="solution not present in raw solutions.json",
                )
            )
            continue
        # Distinguish raw sub-solution links from raw compound links.
        raw_sub_solutions = {x for x in raw if x.startswith("mediadive.solution:")}
        raw_compound_count = sum(1 for x in raw if x.startswith("compound_id:"))

        # KG objects come back as resolved CURIEs (CHEBI:..., mediadive.ingredient:...,
        # mediadive.solution:... for sub-solution refs). Match the sub-solution
        # links exactly; for compounds we cannot reverse-resolve compound_id from a
        # CHEBI without the standardize_compound_id state, so we use cardinality
        # as a proxy and explicit raw sub-solution CURIE membership for direct
        # contamination detection.
        kg_subsols = {o for o in kg_objects if o.startswith("mediadive.solution:")}
        kg_chebi_or_other = kg_objects - kg_subsols

        # CRITICAL: KG references a sub-solution that the raw recipe does not.
        phantom_subsols = kg_subsols - raw_sub_solutions
        for phantom in phantom_subsols:
            report.add(
                Finding(
                    severity="CRITICAL",
                    archetype="recipe-vs-raw",
                    subject=solution_curie,
                    detail=f"KG has phantom sub-solution {phantom} not in raw recipe",
                    evidence=f"raw_sub_solutions={sorted(raw_sub_solutions) or '∅'}",
                )
            )
            contaminated += 1

        # CRITICAL: KG ingredient count vastly exceeds raw recipe size.
        # (Strict equality is impossible without compound->CHEBI lookup, but a
        # KG count >2x the raw count is a strong cross-contamination signal.)
        # Collapse hydrate-equivalent pairs before counting so legitimate
        # bench-prep substitutions (e.g. raw recipe specifies CaCl2-2H2O,
        # KG resolves both anhydrous and hydrated forms to has_part edges)
        # don't fire the contamination warning.
        raw_total = raw_compound_count + len(raw_sub_solutions)
        kg_total = _hydrate_dedupe_count(kg_objects, hydrate_fn)
        if raw_total > 0 and kg_total > 2 * raw_total + 2:
            report.add(
                Finding(
                    severity="CRITICAL",
                    archetype="recipe-vs-raw",
                    subject=solution_curie,
                    detail=f"KG out-degree {kg_total} >> raw recipe size {raw_total}",
                    evidence=(
                        f"first_5_kg={sorted(kg_chebi_or_other)[:5]} "
                        f"raw_sub_solutions={sorted(raw_sub_solutions)}"
                    ),
                )
            )
            contaminated += 1

    report.stats["contaminated_solutions"] = contaminated
    return report


# ---------------------------------------------------------------------------
# Archetype: self-loops
# ---------------------------------------------------------------------------


def archetype_self_loops(args: argparse.Namespace) -> Report:
    report = Report(archetype="self-loops")
    pred_filter = set(args.predicate) if args.predicate else NO_SELF_LOOP_PREDICATES

    transforms = args.transform or _list_transform_dirs()
    total_self_loops = 0
    total_rows = 0
    for tr in transforms:
        try:
            for row in iter_edges(tr):
                total_rows += 1
                pred = row[PREDICATE_IDX]
                if pred not in pred_filter:
                    continue
                subj, obj = row[SUBJECT_IDX], row[OBJECT_IDX]
                if subj == obj:
                    total_self_loops += 1
                    report.add(
                        Finding(
                            severity="WARNING",
                            archetype="self-loops",
                            subject=subj,
                            detail=f"self-loop on {pred}",
                            evidence=f"transform={tr}",
                        )
                    )
        except FileNotFoundError:
            continue
    report.stats["edges_scanned"] = total_rows
    report.stats["self_loops_found"] = total_self_loops
    return report


# ---------------------------------------------------------------------------
# Archetype: cardinality
# ---------------------------------------------------------------------------


def archetype_cardinality(args: argparse.Namespace) -> Report:
    """Top-K out-degree per (subject_prefix, predicate)."""
    report = Report(archetype="cardinality")
    pred_filter = set(args.predicate) if args.predicate else None
    subj_prefix = args.subject_prefix

    counts: Counter = Counter()
    transforms = args.transform or _list_transform_dirs()
    for tr in transforms:
        try:
            for row in iter_edges(tr):
                subj, pred = row[SUBJECT_IDX], row[PREDICATE_IDX]
                if subj_prefix and not subj.startswith(subj_prefix):
                    continue
                if pred_filter and pred not in pred_filter:
                    continue
                counts[(subj, pred)] += 1
        except FileNotFoundError:
            continue

    top = counts.most_common(args.top)
    report.stats["unique_subjects"] = len({s for s, _ in counts.keys()})
    for (subj, pred), n in top:
        # Pick envelope by matching subject prefix.
        envelope = None
        for (sp, p), env in CARDINALITY_ENVELOPES.items():
            if subj.startswith(sp) and pred == p:
                envelope = env
                break
        if envelope and n > envelope[1]:
            severity = "CRITICAL"
            detail = f"out-degree={n} on {pred} (anomaly threshold {envelope[1]})"
        elif envelope and n > envelope[0]:
            severity = "WARNING"
            detail = f"out-degree={n} on {pred} (typical max {envelope[0]})"
        else:
            severity = "INFO"
            detail = f"out-degree={n} on {pred}"
        report.add(Finding(severity=severity, archetype="cardinality", subject=subj, detail=detail))
    return report


# ---------------------------------------------------------------------------
# Archetype: subclass-cycles
# ---------------------------------------------------------------------------


def archetype_subclass_cycles(args: argparse.Namespace) -> Report:
    report = Report(archetype="subclass-cycles")
    transforms = args.transform or ["ontologies"]
    for tr in transforms:
        try:
            adj = build_adjacency(tr, predicate_filter={"biolink:subclass_of"})
        except FileNotFoundError:
            continue
        # Collapse predicate; just need successor sets.
        succ: Dict[str, Set[str]] = {k: {t for _, t in v} for k, v in adj.items()}
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = defaultdict(lambda: WHITE)
        cycles_found = 0

        def dfs(node: str, stack: List[str]) -> None:
            nonlocal cycles_found
            if color[node] == GRAY:
                cycle_start = stack.index(node)
                cycle = stack[cycle_start:] + [node]
                cycles_found += 1
                report.add(
                    Finding(
                        severity="WARNING",
                        archetype="subclass-cycles",
                        subject=node,
                        detail="subclass_of cycle",
                        evidence=f"transform={tr} cycle={' -> '.join(cycle)}",
                    )
                )
                return
            if color[node] == BLACK:
                return
            color[node] = GRAY
            stack.append(node)
            for child in succ.get(node, ()):
                dfs(child, stack)
            stack.pop()
            color[node] = BLACK

        for n in list(succ.keys()):
            if color[n] == WHITE:
                dfs(n, [])
        report.stats[f"{tr}_nodes"] = len(succ)
        report.stats[f"{tr}_cycles"] = cycles_found
    return report


# ---------------------------------------------------------------------------
# Archetype: false-majority (metatraits)
# ---------------------------------------------------------------------------


# Canonical phenotype names where "positive" / "negative" / "variable" is part
# of the trait NAME, not a polarity flag. Having these as has_phenotype targets
# is correct — the organism IS gram-negative, IS catalase-positive, etc. — so
# the proxy must NOT treat the substring "negative" in these labels as a sign
# of false-majority leakage.
_CANONICAL_POLARITY_TRAIT_RE = re.compile(
    r"^(?:gram|oxidase|catalase|coagulase|urease|indole|nitrate|"
    r"methyl[- ]?red|voges[- ]?proskauer|citrate|h2s|lipase|gelatinase|"
    r"amylase|esculin|hemolytic|haemolytic|spore|motil(?:e|ity)|"
    r"acid[- ]?fast|aerob(?:ic|e)|anaerob(?:ic|e)|microaerophilic)"
    r"[\s-]+(?:positive|negative|variable)\b"
)

# Explicit negation phrases — these DO indicate the organism does *not* have
# the trait, so a positive `has_phenotype` / `capable_of` edge to them is a
# real false-majority symptom.
_NEGATION_PATTERNS = (
    re.compile(r"\babsent\b"),
    re.compile(r"\bno growth\b"),
    re.compile(r"\bdoes not\b"),
    re.compile(r"\bfails? to\b"),
    re.compile(r"\bnot able\b"),
    re.compile(r"\blacks?\b"),
    re.compile(r"\bunable to\b"),
)


def archetype_false_majority(args: argparse.Namespace) -> Report:
    """
    Heuristic detector for the Tier-2 false-majority bug — looks for organism →
    has_phenotype / capable_of edges whose object LABEL contains an explicit
    negation phrase ("absent", "no growth", "does not", "fails to", "lacks").
    A positive predicate pointing at such an object is a probable symptom of
    false-majority leakage.

    The proxy intentionally ignores canonical taxonomic descriptors of the
    form "X positive" / "X negative" / "X variable" (gram negative, catalase
    positive, oxidase variable, …) because those ARE the trait name — the
    organism legitimately HAS the property of being gram-negative, etc.

    True ground-truth check requires joining to metatraits' source-row
    majority counts in `bacdive_strains.json`; this archetype is a fast proxy
    that flags label-shaped negations only. Zero hits here does NOT prove the
    absence of false-majority bugs (e.g. an org incorrectly emitted as
    `has_phenotype catalase` when it tested catalase-negative would slip
    through because the object label is just "catalase"). For a stronger
    check, build the metatraits majority table and join.
    """
    report = Report(archetype="false-majority (metatraits proxy)")
    transforms = args.transform or ["metatraits"]
    transform = transforms[0] if isinstance(transforms, list) else transforms
    labels = load_node_labels(transform)

    flagged = 0
    scanned = 0
    skipped_canonical = 0
    for row in iter_edges(transform):
        scanned += 1
        subj, pred, obj = row[SUBJECT_IDX], row[PREDICATE_IDX], row[OBJECT_IDX]
        if pred not in {"biolink:has_phenotype", "biolink:capable_of"}:
            continue
        if not subj.startswith("NCBITaxon:"):
            continue
        obj_label = labels.get(obj, "").lower()
        if not obj_label:
            continue
        if _CANONICAL_POLARITY_TRAIT_RE.match(obj_label):
            skipped_canonical += 1
            continue
        if any(p.search(obj_label) for p in _NEGATION_PATTERNS):
            flagged += 1
            report.add(
                Finding(
                    severity="CRITICAL",
                    archetype="false-majority",
                    subject=subj,
                    detail=f"positive {pred} -> negation-phrase phenotype",
                    evidence=f"object={obj} label={labels.get(obj)!r}",
                )
            )
    report.stats["edges_scanned"] = scanned
    report.stats["flagged"] = flagged
    report.stats["skipped_canonical_polarity"] = skipped_canonical
    return report


# ---------------------------------------------------------------------------
# Archetype: family-mismatch
# ---------------------------------------------------------------------------

# Predicates whose subject is asserted to be a substrate, location, or part —
# i.e. a *thing*, not a quality / role / phenotype / unit. Catches the bug
# class where PATO 'increased depth' or PATO 'female' ended up as the
# subject of ``location_of`` (madin_etal/bacdive 2026-05-02 fixes).
_SUBSTRATE_SUBJECT_PREDICATES = frozenset({
    "biolink:location_of",
    "biolink:has_part",
})

# Ontology prefixes whose terms denote qualities / roles / units / phenotype
# classes — categorically wrong as the subject of a substrate-shaped predicate.
# Mirror of ``DISALLOWED_OBJECT_SOURCES`` in
# ``kg_microbe/utils/isolation_source_mapping_utils.py``; keep in sync.
_DISALLOWED_SUBSTRATE_SUBJECT_PREFIXES = frozenset({
    "PATO:",     # phenotypic quality (acidic, female, juvenile, depth, ...)
    "UO:",       # unit of measurement
    "METPO:",    # microbial phenotype class — phenotype, not substrate
})


def archetype_family_mismatch(args: argparse.Namespace) -> Report:
    """
    Flag edges whose subject is from a quality/role/unit ontology while the
    predicate semantics demand a substrate-like subject.

    Concretely catches the BacDive isolation-source family-mismatch bug
    (PATO:0000383 'female' as ``location_of`` of an organism) and the
    madin_etal compositional-habitat bug (PATO:0001596 'increased depth' as
    ``location_of`` of an organism). Both were real regressions in 2026-05-02
    that single-edge KGX/Biolink validation didn't catch — the categories
    were valid in isolation, only the *role* of the subject in the path was
    wrong.

    Catches different patterns from ``self-loops`` / ``cardinality``: this
    archetype is about the *kind* of subject vs the *meaning* of the
    predicate, not about cycles or fanout.
    """
    report = Report(archetype="family-mismatch")
    pred_filter = set(args.predicate) if args.predicate else _SUBSTRATE_SUBJECT_PREDICATES
    transforms = args.transform or _list_transform_dirs()

    flagged = 0
    scanned = 0
    by_prefix: Counter = Counter()
    for tr in transforms:
        try:
            for row in iter_edges(tr):
                scanned += 1
                subj, pred = row[SUBJECT_IDX], row[PREDICATE_IDX]
                if pred not in pred_filter:
                    continue
                if not any(subj.startswith(p) for p in _DISALLOWED_SUBSTRATE_SUBJECT_PREFIXES):
                    continue
                flagged += 1
                prefix = subj.split(":", 1)[0] + ":"
                by_prefix[(prefix, pred)] += 1
                if flagged <= 50:  # cap evidence list to keep reports readable
                    report.add(
                        Finding(
                            severity="CRITICAL",
                            archetype="family-mismatch",
                            subject=subj,
                            detail=f"{prefix} subject of {pred} (substrate-shaped predicate)",
                            evidence=f"transform={tr} object={row[OBJECT_IDX]}",
                        )
                    )
        except FileNotFoundError:
            continue

    report.stats["edges_scanned"] = scanned
    report.stats["flagged"] = flagged
    for (prefix, pred), n in by_prefix.most_common():
        report.stats[f"by_pair[{prefix}_{pred}]"] = n
    return report


# ---------------------------------------------------------------------------
# Archetype: orphan-edges
# ---------------------------------------------------------------------------


# Prefixes that the ``ontologies`` transform supplies node rows for, so
# orphan edges to these CURIEs in OTHER transforms are expected at the
# per-transform layer and resolve at merge time. Filter them out by default
# to keep the archetype's signal-to-noise high — pass ``--include-cross-transform``
# to see them anyway.
_CROSS_TRANSFORM_SUPPLIED_PREFIXES = frozenset({
    "CHEBI", "ENVO", "FOODON", "GO", "EC", "MICRO", "METPO", "MONDO", "HP",
    "NCBITaxon", "PATO", "PO", "PR", "CL", "RO", "TAXRANK", "UBERON", "RHEA",
    "GTDB", "GenBank", "BFO", "UPA",
    "mesh", "NCIT", "PRIDE", "PCO", "GENEPIO", "FAO", "BTO", "SNOMED",
    "pubchem.compound", "cas",
})


def archetype_orphan_edges(args: argparse.Namespace) -> Report:
    """
    For each transform, verify every edge endpoint has a node row in the
    same ``nodes.tsv``. Catches the bug where a transform emits an edge
    without emitting the node it references — fatal for KGX validators and
    Neo4j loaders if the merge-time supplier doesn't fill the gap.

    By default, orphans whose CURIE prefix is in
    :data:`_CROSS_TRANSFORM_SUPPLIED_PREFIXES` are silently counted but not
    reported as findings — those resolve at merge time when the
    ``ontologies`` transform supplies the node row. The
    ``cross_transform_orphan_subj`` / ``cross_transform_orphan_obj`` stats
    expose the count for visibility. Pass ``--include-cross-transform`` to
    flip that filter off and see all orphans.

    For a true merge-level orphan check (zero orphans across the full
    merged tar.gz) extract ``data/merged/merged-kg.tar.gz`` and diff
    edge endpoints against the merged ``nodes.tsv``.
    """
    report = Report(archetype="orphan-edges")
    transforms = args.transform or _list_transform_dirs()
    max_rows = args.max_rows if hasattr(args, "max_rows") else None
    include_cross = getattr(args, "include_cross_transform", False)

    for tr in transforms:
        nodes_p = nodes_path(tr)
        edges_p = edges_path(tr)
        if not (nodes_p.is_file() and edges_p.is_file()):
            continue
        nodes: Set[str] = set()
        with nodes_p.open("r", encoding="utf-8") as fh:
            next(fh, None)  # skip header
            for line in fh:
                first = line.split("\t", 1)[0]
                if first:
                    nodes.add(first)
        report.stats[f"{tr}_nodes"] = len(nodes)

        orphan_subj = 0
        orphan_obj = 0
        cross_subj = 0
        cross_obj = 0
        scanned = 0
        examples_subj: List[Tuple[str, str]] = []
        examples_obj: List[Tuple[str, str]] = []
        for row in iter_edges(tr, max_rows=max_rows):
            scanned += 1
            s, o = row[SUBJECT_IDX], row[OBJECT_IDX]
            if s and s not in nodes:
                s_prefix = s.split(":", 1)[0] if ":" in s else ""
                is_cross = s_prefix in _CROSS_TRANSFORM_SUPPLIED_PREFIXES
                if is_cross and not include_cross:
                    cross_subj += 1
                else:
                    orphan_subj += 1
                    if len(examples_subj) < 5:
                        examples_subj.append((s, row[PREDICATE_IDX]))
            if o and o not in nodes:
                o_prefix = o.split(":", 1)[0] if ":" in o else ""
                is_cross = o_prefix in _CROSS_TRANSFORM_SUPPLIED_PREFIXES
                if is_cross and not include_cross:
                    cross_obj += 1
                else:
                    orphan_obj += 1
                    if len(examples_obj) < 5:
                        examples_obj.append((o, row[PREDICATE_IDX]))
        report.stats[f"{tr}_edges_scanned"] = scanned
        report.stats[f"{tr}_orphan_subject"] = orphan_subj
        report.stats[f"{tr}_orphan_object"] = orphan_obj
        report.stats[f"{tr}_cross_transform_orphan_subj"] = cross_subj
        report.stats[f"{tr}_cross_transform_orphan_obj"] = cross_obj

        if orphan_subj or orphan_obj:
            for s, p in examples_subj:
                report.add(
                    Finding(
                        severity="CRITICAL",
                        archetype="orphan-edges",
                        subject=s,
                        detail=f"orphan subject of {p} (no node row in {tr}/nodes.tsv)",
                    )
                )
            for o, p in examples_obj:
                report.add(
                    Finding(
                        severity="CRITICAL",
                        archetype="orphan-edges",
                        subject=o,
                        detail=f"orphan object of {p} (no node row in {tr}/nodes.tsv)",
                    )
                )
    return report


# ---------------------------------------------------------------------------
# Build-staleness sanity check
# ---------------------------------------------------------------------------


def warn_if_stale_merge() -> None:
    """Warn (to stderr) if any transform output is newer than the merged
    tar.gz — a frequent source of "review the merged KG but actually you're
    looking at stale results" pitfalls in interactive use."""
    merged = MERGED_DIR / "merged-kg.tar.gz"
    if not merged.is_file():
        return
    merged_mtime = merged.stat().st_mtime
    fresher = []
    for tr in _list_transform_dirs():
        ep = edges_path(tr)
        if ep.is_file() and ep.stat().st_mtime > merged_mtime:
            fresher.append(tr)
    if fresher:
        print(
            f"⚠️  data/merged/merged-kg.tar.gz is older than transform output(s): "
            f"{', '.join(fresher)}. Re-merge with `kg merge -y merge.yaml` to "
            "reflect the fresh transforms in any merged-level checks.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Archetype dispatch
# ---------------------------------------------------------------------------


ARCHETYPES = {
    "recipe-vs-raw": archetype_recipe_vs_raw,
    "self-loops": archetype_self_loops,
    "cardinality": archetype_cardinality,
    "subclass-cycles": archetype_subclass_cycles,
    "false-majority": archetype_false_majority,
    "family-mismatch": archetype_family_mismatch,
    "orphan-edges": archetype_orphan_edges,
}


def cmd_archetype(args: argparse.Namespace) -> int:
    fn = ARCHETYPES.get(args.name)
    if not fn:
        print(f"Unknown archetype: {args.name}", file=sys.stderr)
        print(f"Available: {sorted(ARCHETYPES)}", file=sys.stderr)
        return 2
    warn_if_stale_merge()
    report = fn(args)
    rendered = report.render(max_per_severity=args.show)
    print(rendered)

    if not getattr(args, "no_save", False):
        transforms = "_".join(args.transform) if args.transform else "all"
        scope = f"archetype-{args.name}_{transforms}"
        saved = _save_review_artifact(rendered, scope, ext="txt")
        print(f"# saved to {saved}", file=sys.stderr)

    crit = sum(1 for f in report.findings if f.severity == "CRITICAL")
    return 1 if crit > 0 and args.fail_on_critical else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kg-path-review")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_walk = sub.add_parser("walk", help="Walk paths from a starting CURIE")
    p_walk.add_argument("--start", required=True, help="Starting CURIE")
    p_walk.add_argument("--transform", required=True, help="Transform name (data/transformed/<name>)")
    p_walk.add_argument("--depth", type=int, default=2)
    p_walk.add_argument("--max-fanout", type=int, default=10)
    p_walk.add_argument("--reverse", action="store_true", help="Walk incoming edges instead")
    p_walk.add_argument("--predicate", action="append", help="Restrict to these predicates")
    p_walk.add_argument("--with-labels", action="store_true", default=True)
    p_walk.add_argument("--no-save", action="store_true",
                        help="Skip writing a timestamped artifact under <skill>/reviews/")
    p_walk.set_defaults(func=cmd_walk)

    p_arc = sub.add_parser("archetype", help="Run a built-in archetype check")
    p_arc.add_argument("name", choices=sorted(ARCHETYPES))
    p_arc.add_argument("--transform", action="append",
                       help="Restrict to specific transform(s); default: all where applicable")
    p_arc.add_argument("--predicate", action="append", help="Predicate filter (archetype-specific)")
    p_arc.add_argument("--subject-prefix", help="Subject CURIE prefix filter (cardinality)")
    p_arc.add_argument("--top", type=int, default=20, help="Top-K for cardinality")
    p_arc.add_argument("--show", type=int, default=10, help="Max findings printed per severity")
    p_arc.add_argument("--fail-on-critical", action="store_true",
                       help="Exit non-zero if any CRITICAL finding")
    p_arc.add_argument("--no-save", action="store_true",
                       help="Skip writing a timestamped artifact under <skill>/reviews/")
    p_arc.add_argument("--max-rows", type=int, default=None,
                       help="Cap rows scanned per file (orphan-edges; default: all)")
    p_arc.add_argument("--include-cross-transform", action="store_true",
                       help="orphan-edges: include orphans whose CURIE prefix is "
                            "supplied by another transform at merge time")
    p_arc.set_defaults(func=cmd_archetype)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
