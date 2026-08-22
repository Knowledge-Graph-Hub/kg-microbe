"""Shared hermetic-test configuration for kg-microbe."""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from typing import Any

import pytest

TEST_RESOURCES = Path(__file__).resolve().parent / "resources"


def pytest_configure() -> None:
    """Point data-dependent unit tests at committed immutable fixtures."""
    os.environ.setdefault("KG_MICROBE_METPO_JSON", str(TEST_RESOURCES / "metpo_minimal.json"))
    os.environ.setdefault("KG_MICROBE_METPO_TEMPLATE_DIR", str(TEST_RESOURCES / "metpo_templates"))
    os.environ.setdefault("KG_MICROBE_BIOLINK_MODEL", str(TEST_RESOURCES / "biolink-model-minimal.yaml"))
    os.environ.setdefault(
        "KG_MICROBE_BIOLINK_PREDICATE_MAP",
        str(TEST_RESOURCES / "predicate_mapping_minimal.yaml"),
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip explicitly marked live/local-service tests unless opted in."""
    run_integration = os.environ.get("KG_MICROBE_RUN_INTEGRATION", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if run_integration:
        return
    skip = pytest.mark.skip(reason="integration test; set KG_MICROBE_RUN_INTEGRATION=1 to run")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)


def _is_loopback(host: Any) -> bool:
    """Return whether a socket destination is local to the test process."""
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Reject external DNS/socket use in unit tests while allowing loopback servers."""
    if request.node.get_closest_marker("integration"):
        return

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any):
        if not _is_loopback(host):
            raise RuntimeError(f"external network disabled in unit tests: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise RuntimeError(f"external network disabled in unit tests: {host}")
        return real_connect(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
