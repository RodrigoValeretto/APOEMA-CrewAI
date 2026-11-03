"""Regression: informativo_key resolution must normalize before validation.

The endpoint resolves ``informativo_key`` -> ``informativo_id`` but, before the
fix, left ``informativo_key`` set — so a valid key-only request then failed the
"mutually exclusive" check with 400. This pins the corrected behavior.
"""
from fastapi.testclient import TestClient

from api import api as api_module


def _patch_create_flow(monkeypatch):
    """Mock the DB + enqueue so a POST /api/analysis with a valid key succeeds."""
    monkeypatch.setattr(
        api_module.database,
        "get_informativo_by_slug",
        lambda slug: {"id": 27, "nome": "Computação", "slug": slug, "quadrienio": "2025-2028"},
    )
    monkeypatch.setattr(
        api_module.database,
        "get_informativo",
        lambda informativo_id: {"id": informativo_id, "nome": "Computação"},
    )
    monkeypatch.setattr(
        api_module.database,
        "get_completed_documents_by_kinds",
        lambda informativo_id, kinds: (
            [{"converted_file_path": "/app/uploads/converted/ficha.json",
              "converted_file_id": 100}]
            if kinds == ["ficha"]
            else []
        ),
    )
    monkeypatch.setattr(api_module.database, "create_analysis", lambda **kw: 1)
    monkeypatch.setattr(api_module.database, "create_analysis_file_mapping", lambda **kw: None)
    monkeypatch.setattr(
        api_module.enqueue_analysis_for_sequential_processing,
        "send",
        lambda **kwargs: None,
    )


def test_informativo_key_resolves_and_creates(monkeypatch):
    """A request with only `informativo_key` must NOT trip the mutually-exclusive
    check after the key is resolved to an id."""
    _patch_create_flow(monkeypatch)
    client = TestClient(api_module.app)

    resp = client.post(
        "/api/analysis",
        json={"informativo_key": "computacao", "model": "ollama"},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == 1
    # The resolved id is what gets stored; the key is normalized away.
    assert body["informativo_id"] == 27


def test_informativo_key_unknown_still_400(monkeypatch):
    """An unknown key keeps failing with INVALID_INPUT (no regression)."""
    monkeypatch.setattr(
        api_module.database, "get_informativo_by_slug", lambda slug: None
    )
    client = TestClient(api_module.app)

    resp = client.post(
        "/api/analysis",
        json={"informativo_key": "nao_existe", "model": "ollama"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"] == "INVALID_INPUT"
    assert "Unknown ficha key" in resp.json()["message"]
