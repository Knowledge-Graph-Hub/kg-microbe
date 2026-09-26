"""Bind one merge to unchanged admitted files without copying graph-scale inputs (#1100)."""

import hashlib
import json
import os
import stat
from pathlib import Path

from kg_microbe.utils.source_finalization import SourceFinalizationRequired


def _stamp(value):
    """Exclude access time while retaining inode, replacement, content-write and size evidence."""
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


class SourceAdmission:
    """Retain exact checked byte identities plus conservative filesystem change observations."""

    def __init__(self):
        """Start an empty, request-local admission set; never write an input file."""
        self.identities = {}
        self.stamps = {}
        self.bindings = {}
        self.absent = set()
        self.trees = {}
        self.payloads = {}
        self.resolutions = []

    def capture_resolution(self, resolver, *args):
        """Bind precedence-sensitive input resolution, not just the originally chosen lexical path."""
        selected = resolver(*args)
        self.resolutions.append((resolver, args, selected))
        return selected

    def bind_path(self, path):
        """Keep a lexical input locator tied to its original resolved target, including symlinks."""
        lexical = Path(path).absolute()
        resolved = lexical.resolve()
        previous = self.bindings.setdefault(lexical, resolved)
        if previous != resolved:
            raise SourceFinalizationRequired(f"Merge admission input locator changed: {lexical}")
        return resolved

    @staticmethod
    def _read(path, *, retain=False):
        """Hash the same open file used for metadata parsing and reject changes during its read."""
        try:
            initial = path.stat()
            if not stat.S_ISREG(initial.st_mode):
                raise SourceFinalizationRequired(f"Merge admission input is not a regular file: {path}")
            before = _stamp(initial)
            digest, size, chunks = hashlib.sha256(), 0, []
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or _stamp(opened) != before:
                    raise SourceFinalizationRequired(f"Merge admission file changed while opening: {path}")
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
                    if retain:
                        chunks.append(block)
                if _stamp(os.fstat(stream.fileno())) != before:
                    raise SourceFinalizationRequired(f"Merge admission file changed while reading: {path}")
            if _stamp(path.stat()) != before or size != before[3]:
                raise SourceFinalizationRequired(f"Merge admission file changed while reading: {path}")
        except OSError as error:
            raise SourceFinalizationRequired(f"Merge admission file missing or unreadable: {path}") from error
        return {"bytes": size, "sha256": digest.hexdigest()}, before, b"".join(chunks) if retain else None

    def capture(self, path, *, retain=False, optional=False):
        """Observe bytes before the caller validates them, caching graph hashes but not whole graphs."""
        path = self.bind_path(path)
        if optional and not path.exists():
            self.absent.add(path)
            return None
        if path not in self.identities:
            identity, stamp, payload = self._read(path, retain=retain)
            self.identities[path], self.stamps[path] = identity, stamp
            if retain:
                self.payloads[path] = payload
        elif retain and path not in self.payloads:
            identity, stamp, payload = self._read(path, retain=True)
            if identity != self.identities[path] or stamp != self.stamps[path]:
                raise SourceFinalizationRequired(f"Merge admission file changed: {path}")
            self.payloads[path] = payload
        return self.payloads[path] if retain else self.identities[path]

    def read_json(self, path):
        """Parse exactly the metadata bytes whose hash is retained in the admission set."""
        return json.loads(self.capture(path, retain=True))

    def capture_tree(self, path):
        """Bind Python package membership too, so newly added producer helpers cannot evade checks."""
        path = self.bind_path(path)
        members = tuple(sorted(path.rglob("*.py")))
        previous = self.trees.setdefault(path, members)
        if previous != members:
            raise SourceFinalizationRequired(f"Merge admission producer package changed: {path}")
        for member in members:
            self.capture(member)

    def verify(self, *, metadata_only=False):
        """Reject drift from original admission; this is not a substitute-current-record freshness check."""
        for resolver, args, selected in self.resolutions:
            if resolver(*args) != selected:
                raise SourceFinalizationRequired(f"Merge admitted input resolution changed: {args[0]}")
        for lexical, resolved in self.bindings.items():
            if lexical.resolve() != resolved:
                raise SourceFinalizationRequired(f"Merge admitted input locator changed: {lexical}")
        for path in self.absent:
            if path.exists():
                raise SourceFinalizationRequired(f"Merge admitted absent input appeared: {path}")
        for path, members in self.trees.items():
            if tuple(sorted(path.rglob("*.py"))) != members:
                raise SourceFinalizationRequired(f"Merge admitted producer package changed: {path}")
        for path, expected in self.identities.items():
            try:
                if _stamp(path.stat()) != self.stamps[path]:
                    raise SourceFinalizationRequired(f"Merge admitted file changed: {path}")
            except OSError as error:
                raise SourceFinalizationRequired(f"Merge admitted file missing or unreadable: {path}") from error
            if not metadata_only:
                actual, stamp, _ = self._read(path)
                if actual != expected or stamp != self.stamps[path]:
                    raise SourceFinalizationRequired(f"Merge admitted file changed: {path}")
        if not metadata_only:
            # Recheck earlier files after hashing later graph-scale inputs.
            # This narrows the observation window without pretending to hold
            # an exclusive writer lock through the filesystem publication.
            self.verify(metadata_only=True)
