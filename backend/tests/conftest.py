"""Shared test fixtures: isolated storage rooted at tmp_path + test API key."""

import pytest
from fastapi.testclient import TestClient

import backend.services.storage as storage_module
from backend.config import get_settings
from backend.services.storage import FileSystemStorage


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_module, "get_storage",
                        lambda: FileSystemStorage(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        from backend.main import app

        yield TestClient(app)
    finally:
        get_settings.cache_clear()
