# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures: fake model dirs, a mock-backed pool, and a TestClient."""

import pytest
from fastapi.testclient import TestClient

from infermesh.core.backend import ModelSpec
from infermesh.core.factory import BackendFactory
from infermesh.core.pool import ModelPool
from infermesh.core.settings import Settings
from infermesh.server import create_app


@pytest.fixture(autouse=True)
def _isolate_community_db(tmp_path, monkeypatch):
    """Redirect the shared-library SQLite DB to a per-test temp path so benchmark
    auto-publish and community tests never write to the real ~/.infermesh."""
    monkeypatch.setenv("INFERMESH_COMMUNITY_DB", str(tmp_path / "community.db"))


@pytest.fixture
def fake_model_dir(tmp_path):
    """Three empty fixture model directories under a temp root."""
    for name in ("alpha", "beta", "gamma"):
        (tmp_path / name).mkdir()
    return tmp_path


@pytest.fixture
def mock_pool():
    """A pool with one discovered mock model ('echo-1'), nothing loaded yet."""
    pool = ModelPool(BackendFactory(default_backend="mock"))
    pool.discover_models([
        ModelSpec(model_id="echo-1", source="/tmp/echo-1", backend="mock",
                  extra={"mock_mem_mb": 128}),
    ])
    return pool


@pytest.fixture
def client(mock_pool):
    """FastAPI TestClient over the mock-backed gateway (auth off)."""
    return TestClient(create_app(mock_pool, Settings()))
