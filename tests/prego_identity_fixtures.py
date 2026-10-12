"""Stage exact native identity excerpts without bypassing PREGO's read contract."""

import io
import shutil
import tarfile
from pathlib import Path

IDENTITY_FIXTURES = Path(__file__).parent / "resources" / "prego" / "identity"


def stage_prego_identity_inputs(raw_dir):
    """Supply the real ten-decision native cohort for offline producer tests."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name in ("envo.json", "foodon.json"):
        shutil.copyfile(IDENTITY_FIXTURES / name, raw_dir / name)


def prepare_prego_empty_archive_inputs(transform):
    """Read a genuinely empty association payload through the actual producer's guarded iterator."""
    directory = transform.input_base_dir / "prego"
    directory.mkdir(exist_ok=True)
    archive = directory / "annotated_genomes_isolates.tar.gz"
    if not archive.exists():
        with tarfile.open(archive, "w:gz") as target:
            member = tarfile.TarInfo("database_pairs.tsv")
            member.size = 1
            target.addfile(member, io.BytesIO(b"\n"))
    transform._payload_cache = {}
    transform._payload_metadata = {}
    assert list(transform._iter_payload(archive)) == [], "This inert fixture must contain no source observations"
    transform.verify_native_inputs()
