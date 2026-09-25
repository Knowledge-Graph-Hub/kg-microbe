"""Generate clearly synthetic shared-CAS records with the actual pinned MIM exporter."""

import argparse
import copy
import gzip
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from mediaingredientmech.export.ingredient_bundle import export_bundle
from mediaingredientmech.export.reviewed_sssom import load_review
from mediaingredientmech.ingredient_bundle_contract import (
    annotation_id,
    canonical_json,
    content_sha256,
    occurrence_id,
    product_id,
    read_json,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--producer", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--resources", required=True, type=Path)
args = parser.parse_args()
producer = args.producer.resolve()
output = args.output.resolve()
resource = args.resources.resolve()
expected_commit = "73f14f4a930249836b4c3eee9bae635c731d6c5e"
actual_commit = subprocess.check_output(  # noqa: S603 - fixed git command; no shell or supplied arguments
    [shutil.which("git"), "rev-parse", "HEAD"], cwd=producer, text=True
).strip()
if actual_commit != expected_commit:
    raise ValueError("Use the documented pinned producer commit: " + expected_commit)
resource.mkdir(parents=True, exist_ok=True)
review_path = Path("reports/ingredient_bundle_20260924/review.json")
review = read_json((producer / review_path).read_bytes())
base = load_review(producer, Path(review["base_review"]))
names = {review["base_review"], review["claims_file"], *review["inputs"], *review["record_inputs"]}
sources = {n: (producer / n).read_bytes() for n in names}
document = read_json(sources[review["claims_file"]])
owner = "data/ingredients/mapped/Bovine_Serum_Albumin.yaml"
template = next(c for c in document["claims"] if c["kind"] == "product")
decision_template = next(d for d in review["decisions"] if d["claim_id"] == template["claim_id"])
proof_name = decision_template["review_evidence"]
proof = read_json(sources[proof_name])
fixture = canonical_json(
    {
        "synthetic_software_fixture": True,
        "products": ["TEST-1", "TEST-2"],
        "shared_cas": "9048-46-8",
        "assertions": (
            "Two distinct catalog specifications and two occurrences from one source. No real product evidence."
        ),
    }
)
sources["synthetic-products.json"] = fixture
review["inputs"]["synthetic-products.json"] = content_sha256(fixture)
evidence = [{"document_id": "urn:sha256:" + content_sha256(fixture), "locator": "/"}]
annotation_template = next(
    c["payload"]
    for c in document["claims"]
    if c["kind"] == "identifier" and c["payload"]["owner_id"] == "MIM:Bovine_Serum_Albumin"
)
occurrence_template = next(
    c["payload"]
    for c in document["claims"]
    if c["kind"] == "occurrence" and c["payload"]["source_id"] == "CultureBotHT:compounds-to-cas"
)
for catalog in ["TEST-1", "TEST-2"]:
    identifier = product_id("Example Supplier", catalog)
    preparation = catalog + ' | fraction "example"\tfiltered\nsynthetic preparation'
    product = copy.deepcopy(template["payload"])
    product.update(
        product_id=identifier,
        supplier="Example Supplier",
        catalog_number=catalog,
        label=catalog,
        preparation=preparation,
        source_id="example:synthetic-products",
        source_payload={"synthetic_software_fixture": True, "catalog": catalog},
        evidence=evidence,
    )
    annotation = copy.deepcopy(annotation_template)
    annotation.update(
        owner_id=identifier,
        source_id="example:synthetic-products",
        source_status="TEST_ASSERTION",
        source_version="test-v1",
        evidence=evidence,
    )
    annotation["annotation_id"] = annotation_id(annotation)
    occurrence = copy.deepcopy(occurrence_template)
    occurrence.update(
        source_id="example:synthetic-occurrences",
        source_occurrence_key="product:" + catalog,
        original_label="Synthetic BSA material",
        preparation=preparation,
        product_id=identifier,
        source_payload={"synthetic_software_fixture": True, "catalog": catalog, "preparation": preparation},
        quantity=None,
        alternatives=[],
        evidence=evidence,
    )
    occurrence["occurrence_id"] = occurrence_id(occurrence["source_id"], occurrence["source_occurrence_key"])
    for kind, payload, key in [
        ("product", product, identifier),
        ("identifier", annotation, annotation["annotation_id"]),
        ("occurrence", occurrence, occurrence["occurrence_id"]),
    ]:
        claim = {"claim_id": key, "kind": kind, "owner_record": owner, "payload": payload}
        decision = dict(
            decision_template,
            claim_id=key,
            evidence_key=key,
            row_sha256=content_sha256(canonical_json(claim)),
            review_reason=(
                "Synthetic software fixture only; preserve product/occurrence identity and shared CAS "
                "without a scientific assertion about real supplier products."
            ),
        )
        proof["entries"][key] = {k: decision[k] for k in ["row_sha256", "owner_record", "disposition", "review_reason"]}
        proof["entries"][key]["owner_record_sha256"] = review["record_inputs"][owner]
        document["claims"].append(claim)
        review["decisions"].append(decision)
sources[proof_name] = canonical_json(proof)
review["inputs"][proof_name] = content_sha256(sources[proof_name])
sources[review["claims_file"]] = canonical_json(document)
review["claims_sha256"] = content_sha256(sources[review["claims_file"]])
with tempfile.TemporaryDirectory(prefix="synthetic-ingredient-producer-") as tmp:
    root = Path(tmp)
    for source in base["input_snapshot"]:
        source = Path(source)
        destination = root / source.relative_to(producer)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for name, content in sources.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    p = root / review_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(canonical_json(review) + b"\n")
    receipt = export_bundle(root, review_path, output)
archive = resource / "synthetic-shared-cas-v1.tar.gz"
with archive.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for p in sorted(output.rglob("*")):
                if p.is_file():
                    info = tarfile.TarInfo(p.relative_to(output).as_posix())
                    info.size = p.stat().st_size
                    info.mode = 0o644
                    info.mtime = 0
                    with p.open("rb") as f:
                        tar.addfile(info, f)
origin = {
    "synthetic_software_fixture": True,
    "producer_commit": actual_commit,
    "producer_repository": "https://github.com/CultureBotAI/MediaIngredientMech",
    "bundle_manifest_sha256": receipt["manifest_sha256"],
    "archive_sha256": content_sha256(archive.read_bytes()),
    "archive_bytes": archive.stat().st_size,
    "counts": receipt,
    "generator_sha256": content_sha256(Path(__file__).read_bytes()),
}
(resource / "synthetic-shared-cas-origin.json").write_text(json.dumps(origin, indent=2, sort_keys=True) + "\n")
print(json.dumps(origin, indent=2))
