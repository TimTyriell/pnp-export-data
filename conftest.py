import pytest

import config


@pytest.fixture(autouse=True)
def _offline_wiki_url(monkeypatch):
    """Tests build WikiClient() without a .env; keep it off the placeholder guard."""
    monkeypatch.setattr(config, "WIKI_API_URL", "https://example.invalid/api.php")
