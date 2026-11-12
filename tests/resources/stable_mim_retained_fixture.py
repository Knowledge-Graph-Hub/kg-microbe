"""
Build #1859 synthetic full-cohort products with the reviewed native MIM fixture.

Only new private fixture files are written. Original campaign records, reviews,
products and scientific decisions are never modified or treated as test approval.
"""

import csv
import importlib.util
import json
import shutil
import subprocess


def retained_fixture(fixture, mim_root, mim_head, snapshots, external, binding):
    """Retain native 51/20 history while independently withholding a synthetic BSA source."""
    import yaml
    from mediaingredientmech.export.companion_producer import PATHS

    git = shutil.which("git")
    if git is None:
        raise ValueError("Git is required by the retained native fixture")
    relative = "tests/test_retained_companion.py"
    for name in [relative, *PATHS]:
        raw = (mim_root / name).read_bytes()
        committed = subprocess.run(  # noqa: S603 - exact selected native commit, no shell
            [git, "show", mim_head + ":" + name], cwd=mim_root, check=True, capture_output=True
        ).stdout
        if raw != committed:
            raise ValueError("Retained native fixture source differs from selected commit: " + name)
        snapshots[name] = external.digest(mim_root / name)
    spec = importlib.util.spec_from_file_location("kg_native_retained_companion_fixture", mim_root / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.original.__wrapped__()
    review, sources, _ = module.current.__wrapped__(original)
    root = fixture.root
    # These are the five just-created synthetic source-fixture records, not a
    # current corpus. Replace them with the native fixture's complete inventory.
    for name in fixture.records:
        (root / name).unlink()
    for name, raw in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    fixture.records = {
        name: yaml.safe_load(raw)
        for name, raw in sources.items()
        if name.startswith("data/ingredients/") and name.endswith(".yaml")
    }
    (root / "companion-review.json").write_bytes(module.encoded(review))
    claims = json.loads(sources[module.CLAIMS])["claims"]
    other = next(c["owner_record"] for c in claims if c["kind"] == "mapping" and c["owner_record"] != module.BSA)
    owners = [module.BSA, other]
    with (root / "nodes.tsv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "name", "form"])
        for identifier, owner in zip(["SOURCE:BSA", "SOURCE:retained-control"], owners, strict=True):
            writer.writerow([identifier, fixture.records[owner]["preferred_term"], "explicit synthetic review only"])
    (root / "occurrences.tsv").write_text(
        "source_id\trecipe\tquantity\nSOURCE:BSA\tSYNTHETIC-BSA\tunknown\n"
        "SOURCE:retained-control\tSYNTHETIC-CONTROL\t1 g\n",
        encoding="utf-8",
    )
    fixture.review["source"].update(
        nodes_sha256=external.digest(root / "nodes.tsv"),
        occurrences_sha256=external.digest(root / "occurrences.tsv"),
    )
    fixture.review["record_inputs"] = {name: external.digest(root / name) for name in fixture.records}
    fixture.review["ledger_inputs"] = {
        str(name): external.digest(root / name) for name in (binding.REGISTRY_PATH, binding.LIFECYCLE_PATH)
    }
    fixture.review["external_review"] = {"path": module.BASE, "sha256": external.digest(root / module.BASE)}
    fixture.review["cases"] = [
        {
            "source_position": i,
            "owner_record": owner,
            "holds": ["Synthetic unresolved BSA source; retained companion cannot authorize identity"]
            if i == 1
            else [],
            "primary": None,
            "skeptic": None,
        }
        for i, owner in enumerate(owners, 1)
    ]
    fixture.seal(withheld={1})
