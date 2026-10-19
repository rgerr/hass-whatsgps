"""Gedeelde testinstellingen."""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

# De repository bevat custom_components/; maak die importeerbaar.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.platform == "win32":
    # De Windows-eventloop opent een eigen socketpaar, dat de socketblokkade van de
    # testomgeving weigert nog voor er testcode draait. Op Linux (CI) speelt dit niet.
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None
    pytest_socket.socket_allow_hosts = lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Generator[None]:
    """Laad custom_components/ uit deze repository."""
    yield
