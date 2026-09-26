"""Tests never use remote or paid services, whatever the developer's .env holds."""

import pytest

from wireforge import config


@pytest.fixture(autouse=True)
def _local_browser_only(monkeypatch):
    # With ANAKIN_API_KEY set, BrowserSession would connect to Anakin's remote browser:
    # it cannot reach the tests' 127.0.0.1 server, and every test would spend credits.
    monkeypatch.setattr(config, "ANAKIN_API_KEY", "")
