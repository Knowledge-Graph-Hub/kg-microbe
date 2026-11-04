"""Stage bounded exact native NCBI context for the existing GOLD source fixtures."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

RESOURCES = Path(__file__).parent / "resources"
CONTEXTS = RESOURCES / "gold_taxonomy/selected_taxdump_contexts.json"
CONTEXTS_SHA256 = "7413019862a82444e1e7e3473050f013d254604033f74650d30e23424a573ed8"


def stage_native_gold_taxdump(raw_dir, cohort):
    """Copy native member bytes before consumption; never synthesize a taxon or receipt."""
    content = CONTEXTS.read_bytes()
    assert hashlib.sha256(content).hexdigest() == CONTEXTS_SHA256
    evidence = json.loads(content)
    selected = evidence["cohorts"][cohort]
    for name, expected in selected["selected_fixture_files"].items():
        assert hashlib.sha256((RESOURCES / name).read_bytes()).hexdigest() == expected
    # Preserve both existing native source archive pins and literal merge lines.
    for name, key, fixture in (
        ("selected_aliases", "taxdump_merged_dmp", "gold_selected_taxon_aliases/native_evidence.json"),
        ("fold_restoration", "native_taxdump_remaps", "gold_taxonomy/fold_native_contexts.json"),
    ):
        native = json.loads((RESOURCES / fixture).read_text())
        assert native["inputs"]["taxdump"]["sha256"] == evidence["source_archive"]["sha256"]
        assert [item["literal"] for item in evidence["cohorts"][name]["members"]["merged.dmp"]] == [
            item["literal"] for item in native[key]
        ]
    path = Path(raw_dir) / "taxdump.tar.gz"
    assert not path.exists()
    with tarfile.open(path, "w:gz") as archive:
        for name, records in selected["members"].items():
            data = "".join(item["literal"] for item in records).encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        scope = (evidence["scope"] + "\n").encode()
        member = tarfile.TarInfo("fixture_scope.txt")
        member.size = len(scope)
        archive.addfile(member, io.BytesIO(scope))
    return path
