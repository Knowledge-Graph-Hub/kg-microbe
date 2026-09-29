"""Validate finite historical crosswalk witnesses without doing new taxonomy inference."""

import base64
import hashlib
import json
import re

from kg_microbe.transform_utils import constants as C

_LPSN_PROVIDER = f"infores:{C.LPSN_SOURCE}"
_BACDIVE_PROVIDER = f"infores:{C.BACDIVE}"
_GOLD_PROVIDER = f"infores:{C.GOLD}"
# No constants.py equivalent exists for this ontology provider or the historical
# upstream GOLD category. These literals describe pinned source evidence; the
# transformed node category is always checked against C.NCBI_CATEGORY below.
_NCBITAXON_PROVIDER = "infores:ncbitaxon"
_RAW_GOLD_INDIVIDUAL_CATEGORY = "biolink:IndividualOrganism"


def _need(condition, message):
    if not condition:
        raise ValueError(f"MicrobeDecoder crosswalk witness: {message}")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


class WitnessObjects:
    """Resolve only content-addressed composites, rejecting missing references and cycles."""

    def __init__(self, objects):
        """Bind the compact historical evidence object pool."""
        _need(isinstance(objects, dict), "missing object pool")
        self.objects, self.cache, self.pending = objects, {}, set()

    def expand(self, value):
        """Expand and hash-check each referenced object once; retain shared values."""
        if isinstance(value, dict) and "$ref" in value:
            _need(set(value) == {"$ref"}, "mixed reference object")
            key = value["$ref"]
            _need(isinstance(key, str) and re.fullmatch(r"[0-9a-f]{64}", key), "invalid object reference")
            _need(key not in self.pending and key in self.objects, "missing/cyclic object reference")
            if key not in self.cache:
                self.pending.add(key)
                raw = self.objects[key]
                _need(isinstance(raw, (dict, list)), "noncomposite pooled object")
                result = self.expand(raw)
                _need(hashlib.sha256(_canonical(result).encode()).hexdigest() == key, "object content hash differs")
                self.cache[key] = result
                self.pending.remove(key)
            return self.cache[key]
        if isinstance(value, dict):
            return {key: self.expand(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self.expand(child) for child in value]
        return value


def _node(node, provider):
    _need(isinstance(node, dict), "missing native declaration")
    _need(isinstance(node.get(C.NAME_COLUMN), str) and node[C.NAME_COLUMN].strip(), "unlabelled native declaration")
    _need(node.get(C.CATEGORY_COLUMN) == C.NCBI_CATEGORY, "non-taxon native declaration")
    _need(str(node.get(C.DEPRECATED_COLUMN, "")).strip().lower() in {"", "false"}, "inactive native declaration")
    allowed = {provider, "ncbitaxon_removed_subset.json"} if provider == _NCBITAXON_PROVIDER else {provider}
    _need(bool(set(str(node.get(C.PROVIDED_BY_COLUMN, "")).split("|")) & allowed), "native provider differs")


def _edge(
    edge,
    subject,
    target,
    provider,
    *,
    predicate=C.SUBCLASS_PREDICATE,
    relation=C.RDFS_SUBCLASS_OF,
    level=C.KNOWLEDGE_ASSERTION,
):
    expected = {
        C.SUBJECT_COLUMN: subject,
        C.OBJECT_COLUMN: target,
        C.PREDICATE_COLUMN: predicate,
        C.RELATION_COLUMN: relation,
        C.PRIMARY_KNOWLEDGE_SOURCE_COLUMN: provider,
        C.KNOWLEDGE_LEVEL_COLUMN: level,
        C.AGENT_TYPE_COLUMN: C.AUTOMATED_AGENT if level == C.PREDICTION else C.MANUAL_AGENT,
    }
    _need(
        isinstance(edge, dict) and all(edge.get(key) == value for key, value in expected.items()),
        "native edge claim/provenance differs",
    )


class HistoricalTaxonomy:
    """Validate exact rank and retired-taxid lines in the reviewed authority snapshot."""

    def __init__(self, evidence):
        """Require pinned authorities and taxdump member identities for nonempty policies."""
        authorities = evidence.get("authorities", {})
        required = {
            "raw",
            "lpsn_gss",
            "lpsn_nodes",
            "lpsn_edges",
            "ncbi_nodes",
            "ncbi_edges",
            "taxdump",
            "bacdive_raw",
            "bacdive_nodes",
            "bacdive_edges",
            "gold_raw_nodes",
            "gold_raw_edges",
            "gold_nodes",
            "gold_edges",
            "gold_folds",
            "candidate_edges",
        }
        _need(required <= set(authorities), "missing pinned independent authority files")
        _need(authorities["raw"]["sha256"] == evidence["source_sha256"], "raw authority snapshot differs")
        hashes = evidence.get("taxdump_member_hashes")
        _need(
            isinstance(hashes, dict)
            and all(
                isinstance(hashes.get(member), str) and re.fullmatch(r"[0-9a-f]{64}", hashes[member])
                for member in ("nodes.dmp", "merged.dmp")
            ),
            "missing pinned taxdump members",
        )
        self.ranks = evidence.get("taxonomy_rank_witnesses")
        self.aliases = evidence.get("retired_taxid_witnesses")
        _need(isinstance(self.ranks, dict) and isinstance(self.aliases, dict), "missing raw taxonomy witnesses")

    @staticmethod
    def _line(witness, member):
        _need(
            isinstance(witness, dict)
            and witness.get("authority_id") == "taxdump"
            and witness.get("member") == member
            and type(witness.get("line_ordinal")) is int
            and witness["line_ordinal"] > 0,
            "invalid raw taxonomy locator",
        )
        try:
            raw = base64.b64decode(witness.get("raw_line_base64", ""), validate=True)
            fields = [field.strip() for field in raw.decode("ascii").split("|")]
        except (ValueError, TypeError, UnicodeError) as error:
            raise ValueError("MicrobeDecoder crosswalk witness: invalid taxonomy line") from error
        _need(
            raw.endswith(b"\n") and len(fields) >= 3 and re.fullmatch(r"[1-9][0-9]*", fields[0]),
            "malformed raw taxonomy line",
        )
        return fields

    def rank(self, identifier, expected):
        """Require the precise genus/phylum designation from the saved raw row."""
        witness = self.ranks.get(identifier)
        fields = self._line(witness, "nodes.dmp")
        _need(
            "NCBITaxon:" + fields[0] == identifier and fields[2] == expected and witness.get("rank") == expected,
            "raw taxonomy rank differs",
        )

    def alias(self, original, replacement):
        """Require the precise retired-ID replacement from the saved raw row."""
        witness = self.aliases.get(original)
        fields = self._line(witness, "merged.dmp")
        _need(
            "NCBITaxon:" + fields[0] == original
            and "NCBITaxon:" + fields[1] == replacement
            and witness.get("replacement") == replacement,
            "raw retired-ID replacement differs",
        )


def validate_native(native, taxonomy):
    """Require a complete active lineage with pinned raw rank and retired-ID witnesses."""
    _need(isinstance(native, dict), "missing native lineage")
    nodes, edges, aliases = native.get("nodes"), native.get("edges"), native.get("aliases")
    _need(
        isinstance(nodes, list) and nodes and isinstance(edges, list) and isinstance(aliases, list),
        "malformed native lineage",
    )
    ids = []
    for node in nodes:
        _node(node, _NCBITAXON_PROVIDER)
        identifier = node.get(C.ID_COLUMN)
        _need(
            isinstance(identifier, str) and re.fullmatch(r"NCBITaxon:[1-9][0-9]*", identifier),
            "invalid native taxon ID",
        )
        ids.append(identifier)
    _need(
        len(ids) == len(set(ids)) and ids[0] == native.get("resolved") and ids[-1] == "NCBITaxon:1",
        "cyclic/incomplete native lineage",
    )
    _need(len(edges) == len(ids) - 1, "missing native path edge")
    for edge, subject, target in zip(edges, ids[:-1], ids[1:], strict=True):
        _edge(edge, subject, target, _NCBITAXON_PROVIDER)
    current, seen = native.get("input"), set()
    for alias in aliases:
        _need(
            isinstance(alias, dict) and alias.get("original") == current and current not in seen,
            "broken retired-ID chain",
        )
        seen.add(current)
        taxonomy.alias(current, alias.get("replacement"))
        current = alias.get("replacement")
        _need(current not in seen, "cyclic retired-ID replacement")
    _need(current == native.get("resolved"), "retired-ID chain does not resolve")
    _need(
        native.get("genus") in ids and native.get("phylum") in ids and native["genus"] != native["phylum"],
        "missing/distinct native ranks",
    )
    taxonomy.rank(native["genus"], "genus")
    taxonomy.rank(native["phylum"], "phylum")
    _need(ids.index(native["genus"]) < ids.index(native["phylum"]), "native genus must descend from phylum")


def validate_witness(witness, rule, taxonomy):
    """Check two independent historical supports and only the reviewed cross-rank conflict."""
    _need(witness.get("policy") == "two_authority_cross_genus_and_phylum_v1", "unreviewed admission policy")
    _need(witness.get("raw_record_sha256") == rule.raw_record_sha256, "witness full-record hash differs")
    _need(witness.get("source_ordinal") == int(rule.source_record.rsplit("=", 1)[1]), "witness ordinal differs")
    context, target, gold = witness.get("context"), witness.get("target"), witness.get("gold")
    _need(isinstance(context, dict) and context.get("accepted_subject") == rule.subject, "missing accepted context")
    chain = context.get("gss_chain")
    _need(
        isinstance(chain, list) and chain and all(isinstance(row, dict) for row in chain), "missing LPSN accepted chain"
    )
    current, seen = rule.raw_lpsn_id, set()
    for position, row in enumerate(chain):
        _need(row.get("record_no") == current and current not in seen, "broken/cyclic LPSN accepted chain")
        seen.add(current)
        correct = "correct name" in [part.strip() for part in str(row.get("status", "")).split(";")]
        _need(correct == (position == len(chain) - 1), "LPSN chain lacks unique correct-name terminal")
        current = str(row.get("record_lnk", "")).strip()
    _need("lpsn:" + chain[-1]["record_no"] == rule.subject, "LPSN terminal differs")
    expected = context.get("lpsn_expectation")
    _need(isinstance(expected, dict), "missing independent LPSN taxonomy")
    validate_native(expected.get("native"), taxonomy)
    native = expected["native"]
    lnodes, parents = expected.get("lpsn_nodes"), expected.get("parent_edges")
    _need(isinstance(lnodes, list) and lnodes and isinstance(parents, list), "missing LPSN declarations/path")
    declarations = {}
    for node in lnodes:
        _node(node, _LPSN_PROVIDER)
        identifier = node.get(C.ID_COLUMN)
        _need(
            isinstance(identifier, str) and re.fullmatch(r"lpsn:[1-9][0-9]*", identifier),
            "invalid LPSN declaration ID",
        )
        _need(identifier not in declarations or declarations[identifier] == node, "conflicting LPSN declarations")
        declarations[identifier] = node
    _need(
        lnodes[0].get(C.ID_COLUMN) == rule.subject and lnodes[-1].get(C.ID_COLUMN) == expected.get("via"),
        "LPSN declaration identity differs",
    )
    current, seen, path_ids = rule.subject, set(), [rule.subject]
    for edge in parents:
        _need(isinstance(edge, dict) and current not in seen, "cyclic LPSN authority path")
        seen.add(current)
        _edge(edge, current, edge.get(C.OBJECT_COLUMN), _LPSN_PROVIDER)
        current = edge[C.OBJECT_COLUMN]
        _need(current not in seen, "cyclic LPSN authority path")
        path_ids.append(current)
    _need(current == expected.get("via"), "LPSN path endpoint differs")
    _need(set(declarations) == set(path_ids), "missing or unexpected LPSN path declarations")
    _edge(
        expected.get("crosswalk"),
        current,
        native["input"],
        _LPSN_PROVIDER,
        predicate=C.CLOSE_MATCH_PREDICATE,
        relation=C.CLOSE_MATCH_RELATION,
        level=C.PREDICTION,
    )
    _need(current == rule.subject or native["resolved"] == native["genus"], "ancestor crosswalk is not a genus")
    support = context.get("bacdive_support")
    _need(isinstance(support, dict) and isinstance(support.get("record"), dict), "missing independent BacDive support")
    record = support["record"]
    general, tax = record.get("General"), record.get("Name and taxonomic classification")
    _need(
        isinstance(general, dict) and isinstance(tax, dict) and tax.get("type strain") == "yes",
        "BacDive is not explicit type strain",
    )
    lpsn = tax.get("LPSN")
    name_authority = witness.get("bacdive_name_authority")
    _need(
        isinstance(lpsn, dict)
        and isinstance(name_authority, dict)
        and name_authority.get("authority_id") == "lpsn_gss"
        and name_authority.get("raw_bacdive_lpsn_species") == lpsn.get("species"),
        "raw BacDive LPSN species differs",
    )
    name_records, name_chains = name_authority.get("all_exact_name_record_nos"), name_authority.get("accepted_chains")
    _need(
        isinstance(name_records, list)
        and name_records
        and len(name_records) == len(set(name_records))
        and isinstance(name_chains, list)
        and len(name_records) == len(name_chains),
        "missing exact-name authority chains",
    )
    for name_record, name_chain in zip(name_records, name_chains, strict=True):
        _need(
            isinstance(name_chain, list) and name_chain and all(isinstance(row, dict) for row in name_chain),
            "malformed exact-name chain",
        )
        raw_name = " ".join(
            str(name_chain[0].get(key, "")).strip()
            for key in ("genus_name", "sp_epithet", "subsp_epithet")
            if str(name_chain[0].get(key, "")).strip()
        )
        _need(raw_name == lpsn["species"], "exact-name chain starts at another species")
        current, visited = name_record, set()
        for index, row in enumerate(name_chain):
            _need(row.get("record_no") == current and current not in visited, "broken exact-name accepted chain")
            visited.add(current)
            correct = "correct name" in [part.strip() for part in str(row.get("status", "")).split(";")]
            _need(correct == (index == len(name_chain) - 1), "exact-name chain lacks correct-name terminal")
            current = str(row.get("record_lnk", "")).strip()
        _need("lpsn:" + name_chain[-1]["record_no"] == rule.subject, "exact-name authority resolves elsewhere")
    strain = "kgmicrobe.strain:bacdive_" + str(general.get("BacDive-ID", ""))
    _node(support.get("strain_node"), _BACDIVE_PROVIDER)
    _need(support["strain_node"].get(C.ID_COLUMN) == strain, "BacDive strain declaration differs")
    links, ncbi = support.get("lpsn_edges"), support.get("ncbi_edges")
    _need(
        isinstance(links, list) and links and isinstance(ncbi, list) and ncbi, "missing BacDive cross-authority links"
    )
    for edge in links:
        _edge(edge, strain, rule.subject, _BACDIVE_PROVIDER, level=C.OBSERVATION)
    explicit = general.get("NCBI tax id")
    explicit = explicit if isinstance(explicit, list) else [explicit]
    _need(all(isinstance(item, dict) for item in explicit), "missing raw BacDive explicit taxid")
    selected = [item for item in explicit if item.get("Matching level") in {"species", "strain"}]
    _need(
        selected and all(type(item.get("NCBI tax id")) is int and item["NCBI tax id"] > 0 for item in selected),
        "invalid explicit BacDive species/strain taxid",
    )
    taxa = support.get("native_explicit_taxa")
    _need(isinstance(taxa, list) and len(taxa) == len(selected), "missing explicit BacDive lineage")
    for item, authority in zip(selected, taxa, strict=True):
        validate_native(authority, taxonomy)
        _need(authority["input"] == "NCBITaxon:" + str(item["NCBI tax id"]), "BacDive native taxid differs from raw")
        _need(
            (authority["genus"], authority["phylum"]) == (native["genus"], native["phylum"]),
            "independent authorities disagree",
        )
    alias_lookup = {alias["original"]: authority["resolved"] for authority in taxa for alias in authority["aliases"]}
    for edge in ncbi:
        _edge(edge, strain, edge.get(C.OBJECT_COLUMN), _BACDIVE_PROVIDER, level=C.OBSERVATION)
        _need(
            alias_lookup.get(edge[C.OBJECT_COLUMN], edge[C.OBJECT_COLUMN])
            in {authority["resolved"] for authority in taxa},
            "BacDive link unsupported by raw taxid",
        )
    validate_native(target, taxonomy)

    def normalize(value):
        """Compare explicit authority labels without case or whitespace artifacts."""
        return " ".join(value.split()).casefold()

    source_names = {normalize(lnodes[0][C.NAME_COLUMN])}
    source_names.update(
        normalize(
            " ".join(str(row.get(key, "")) for key in ("genus_name", "sp_epithet", "subsp_epithet") if row.get(key))
        )
        for row in chain
    )
    target_names = {normalize(target["nodes"][0][C.NAME_COLUMN])}
    target_names.update(normalize(name) for name in target["nodes"][0].get(C.SYNONYM_COLUMN, "").split("|") if name)
    _need(not source_names & target_names, "explicit native name/synonym agreement is not quarantinable")
    _need(
        target["genus"] != native["genus"] and target["phylum"] != native["phylum"],
        "not a cross-genus and cross-phylum conflict",
    )
    if rule.source_column == "NCBI_Taxonomy_ID":
        _need(gold is None and target["input"] == rule.object, "NCBI witness binds another field/target")
    else:
        _need(isinstance(gold, dict), "missing GOLD original-claim chain")
        raw_node, raw_edge = gold.get("raw_node"), gold.get("raw_edge")
        _need(
            isinstance(raw_node, dict)
            and raw_node.get(C.ID_COLUMN) == rule.object
            and raw_node.get(C.CATEGORY_COLUMN) == _RAW_GOLD_INDIVIDUAL_CATEGORY
            and raw_node.get(C.PROVIDED_BY_COLUMN) == _GOLD_PROVIDER
            and bool(str(raw_node.get(C.NAME_COLUMN, "")).strip()),
            "invalid raw GOLD declaration",
        )
        _need(
            isinstance(raw_edge, dict)
            and raw_edge.get(C.SUBJECT_COLUMN) == rule.object
            and raw_edge.get(C.OBJECT_COLUMN) == target["input"]
            and raw_edge.get(C.PREDICATE_COLUMN) == C.IN_TAXON_PREDICATE
            and raw_edge.get(C.RELATION_COLUMN) == "gold:organism_v2.ncbi_taxonomy_id"
            and raw_edge.get(C.PRIMARY_KNOWLEDGE_SOURCE_COLUMN, raw_edge.get("knowledge_source")) == _GOLD_PROVIDER,
            "invalid explicit GOLD taxid chain",
        )
        equivalents = {target["resolved"], target["input"], *[alias["original"] for alias in target["aliases"]]}
        _need(raw_node.get(C.XREF_COLUMN) in equivalents, "raw GOLD xref disagrees")
        if gold.get("fold_target"):
            _need(gold["fold_target"] in equivalents and gold.get("native_edges") == [], "GOLD fold disagrees")
        else:
            _node(gold.get("native_node"), _GOLD_PROVIDER)
            _need(gold["native_node"].get(C.ID_COLUMN) == rule.object, "GOLD native ID differs")
            edges = gold.get("native_edges")
            _need(
                isinstance(edges, list) and len(edges) == 1 and edges[0].get(C.OBJECT_COLUMN) in equivalents,
                "GOLD native taxonomy differs",
            )
            _edge(edges[0], rule.object, edges[0][C.OBJECT_COLUMN], _GOLD_PROVIDER)
    original = witness.get("original_emitted_edge")
    _need(
        isinstance(original, dict)
        and (original.get(C.ORIGINAL_OBJECT_COLUMN) or original.get(C.OBJECT_COLUMN)) == rule.object
        and original.get(C.SOURCE_RECORD_COLUMN) == rule.source_record,
        "missing original emitted claim",
    )
    _need(
        original.get(C.OBJECT_COLUMN)
        in {rule.object, target["input"], target["resolved"], *[alias["original"] for alias in target["aliases"]]},
        "original canonical target disagrees with explicit source taxonomy",
    )
    _edge(
        original,
        rule.subject,
        original.get(C.OBJECT_COLUMN),
        C.MICROBEDECODER_KNOWLEDGE_SOURCE,
        predicate=rule.predicate,
        relation=rule.relation,
    )
