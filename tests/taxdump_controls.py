"""Explicit synthetic no-retirement input for unrelated source lifecycle tests."""

import gzip
import io
import tarfile
from pathlib import Path

NO_RETIREMENTS = Path(__file__).parent / "resources" / "taxdump_no_retirements"


def stage_no_retirements_taxdump(raw_dir):
    """
    Stage four actual archive members; never overwrite a selected native authority.

    Empty retirement tables are a synthetic test assumption, not evidence that
    any source taxid is currently live. The fixture supplies no biological
    classification for source IDs and is unsuitable for taxonomy resolution or
    retirement tests. Callers must opt in before producer/finalizer consumption.
    """
    path = Path(raw_dir) / "taxdump.tar.gz"
    with path.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(mode="w", fileobj=compressed) as archive:
                for name in ("nodes.dmp", "names.dmp", "merged.dmp", "delnodes.dmp"):
                    data = (NO_RETIREMENTS / name).read_bytes()
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
    return path
