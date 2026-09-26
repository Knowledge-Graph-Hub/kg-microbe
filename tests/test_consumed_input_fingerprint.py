"""A completion marker must never certify bytes changed since producer consumption."""

import hashlib
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest

import kg_microbe.transform as dispatcher
from kg_microbe.transform_utils.transform import Transform
from kg_microbe.utils import transform_fingerprint as fingerprint

FIXTURE = Path(__file__).parent / "resources/consumed_input_fingerprint/lookup.tsv"


@pytest.fixture
def consumed(tmp_path):
    """Copy immutable source evidence and capture its original digest for the verifier."""
    lookup = tmp_path / "lookup.tsv"
    shutil.copyfile(FIXTURE, lookup)
    expected = hashlib.sha256(lookup.read_bytes()).hexdigest()

    def verify():
        """Refuse content changes or disappearance, regardless of file size or timestamps."""
        if not lookup.is_file() or hashlib.sha256(lookup.read_bytes()).hexdigest() != expected:
            raise ValueError("consumed lookup changed")

    return lookup, verify


def write_marker(tmp_path, consumed):
    """Run the actual atomic fingerprint writer with producer-time evidence validation."""
    lookup, verify = consumed
    return fingerprint.write_fingerprint(
        tmp_path / "output",
        tmp_path / "producer",
        tmp_path,
        (),
        finalization_inputs=(str(lookup),),
        verify_inputs=verify,
    )


def test_unchanged_consumed_input_is_bound_in_marker(tmp_path, consumed):
    """A successful marker still uses the existing complete consumed-input digest contract."""
    marker = write_marker(tmp_path, consumed)
    assert marker["finalization_inputs"] == ["lookup.tsv"]
    assert fingerprint.finalization_inputs_current(marker, tmp_path)
    assert fingerprint.read_fingerprint(tmp_path / "output") == marker


@pytest.mark.parametrize("change", ["replace", "delete"])
def test_changed_input_before_fingerprinting_publishes_nothing(tmp_path, consumed, change):
    """Do not rehash different current bytes and call them the bytes used by the producer."""
    lookup, _ = consumed
    if change == "replace":
        lookup.write_bytes(lookup.read_bytes().replace(b"NCBITaxon:1", b"NCBITaxon:2"))
    else:
        lookup.unlink()
    with pytest.raises(ValueError, match="consumed lookup changed"):
        write_marker(tmp_path, consumed)
    assert not (tmp_path / "output" / fingerprint.FINGERPRINT_FILE).exists()


def test_change_during_payload_construction_preserves_previous_marker(tmp_path, consumed, monkeypatch):
    """Recheck after hashing so even an internally consistent new payload cannot bless changed input."""
    lookup, _ = consumed
    write_marker(tmp_path, consumed)
    marker = tmp_path / "output" / fingerprint.FINGERPRINT_FILE
    previous = marker.read_bytes()
    original = fingerprint.code_fingerprint

    def changed_during_hash(*args, **kwargs):
        """Simulate the lookup's producer replacing it after the initial verification."""
        lookup.write_bytes(lookup.read_bytes().replace(b"NCBITaxon:1", b"NCBITaxon:2"))
        return original(*args, **kwargs)

    monkeypatch.setattr(fingerprint, "code_fingerprint", changed_during_hash)
    with pytest.raises(ValueError, match="consumed lookup changed"):
        write_marker(tmp_path, consumed)
    assert marker.read_bytes() == previous
    assert not list(marker.parent.glob("*.partial"))


def test_change_during_marker_write_cannot_publish(tmp_path, consumed, monkeypatch):
    """Validate inside the atomic-write transaction, after writing and before the final rename."""
    lookup, _ = consumed
    original = fingerprint.atomic_write

    @contextmanager
    def change_after_write(*args, **kwargs):
        """Wrap only the fixture's temporary marker stream, retaining actual atomic publication."""
        with original(*args, **kwargs) as stream:

            class ChangingStream:
                """Inject a concurrent lookup replacement immediately after the marker write."""

                def write(self, text):
                    """Write normally and mutate the independently produced lookup."""
                    result = stream.write(text)
                    lookup.write_bytes(lookup.read_bytes().replace(b"NCBITaxon:1", b"NCBITaxon:2"))
                    return result

            yield ChangingStream()

    monkeypatch.setattr(fingerprint, "atomic_write", change_after_write)
    with pytest.raises(ValueError, match="consumed lookup changed"):
        write_marker(tmp_path, consumed)
    assert not (tmp_path / "output" / fingerprint.FINGERPRINT_FILE).exists()
    assert not list((tmp_path / "output").glob("*.partial"))


def test_dispatcher_passes_producer_verifier(tmp_path, monkeypatch):
    """Normal command dispatch must actually enable the optional writer guard."""
    producer = Transform("fixture", tmp_path / "raw", tmp_path / "transformed")
    seen = []

    def verify():
        """Record that the producer's consumption verifier is invoked."""
        seen.append("verified")

    def write(**kwargs):
        """Stand in only for the writer, asserting the real dispatcher supplies its callback."""
        kwargs["verify_inputs"]()

    producer.verify_consumed_inputs = verify
    monkeypatch.setattr(dispatcher, "write_fingerprint", write)
    dispatcher._record_fingerprint(producer, "fixture")
    assert seen == ["verified"]


def test_dispatcher_failure_does_not_leave_success_marker(tmp_path, monkeypatch, capsys):
    """Best-effort bookkeeping may warn, but cannot leave a stale success certificate behind."""
    producer = Transform("fixture", tmp_path / "raw", tmp_path / "transformed")
    marker = producer.output_dir / fingerprint.FINGERPRINT_FILE
    marker.write_text("old marker", encoding="utf-8")

    def fail(**kwargs):
        """Simulate an input verification failure during completion bookkeeping."""
        raise ValueError("consumed lookup changed")

    monkeypatch.setattr(dispatcher, "write_fingerprint", fail)
    dispatcher._record_fingerprint(producer, "fixture")
    assert not marker.exists()
    assert "could not record fingerprint (consumed lookup changed)" in capsys.readouterr().out
