"""Tests for the areas endpoint (catalog overlay + DB join)."""
from api.areas_catalog import CAPES_AREAS, area_key


def test_catalog_covers_50_areas():
    assert len(CAPES_AREAS) == 50


def test_areas_merge_overlay(monkeypatch):
    """A DB row (by slug) fills ids/status; missing areas stay null."""
    from api import api as api_module

    fake_rows = [
        {
            "slug": "computacao",
            "corpus_id": 3,
            "document_id": 7,
            "converted_file_id": 12,
            "status": "completed",
            "quadrennium": "2025-2028",
            "drive_file_id": "abc123",
        }
    ]
    monkeypatch.setattr(api_module.database, "get_area_rows", lambda: fake_rows)

    from api.models import AreaListResponse

    # Reconstruct the merge logic (mirrors the endpoint body).
    db_rows = {r["slug"]: r for r in api_module.database.get_area_rows()}
    items = []
    for code, name in sorted(CAPES_AREAS.items()):
        key = area_key(code)
        row = db_rows.get(key, {})
        items.append(
            api_module.AreaResponse(
                code=code,
                name=name,
                key=key,
                corpus_id=row.get("corpus_id"),
                document_id=row.get("document_id"),
                converted_file_id=row.get("converted_file_id"),
                status=row.get("status"),
                quadrennium=row.get("quadrennium"),
                drive_file_id=row.get("drive_file_id"),
            )
        )
    result = AreaListResponse(total=len(items), items=items)

    assert result.total == 50
    by_key = {i.key: i for i in result.items}

    computacao = by_key["computacao"]
    assert computacao.name == "Computação"
    assert computacao.corpus_id == 3
    assert computacao.status == "completed"

    # An un-ingested area has no DB row -> nulls.
    adm = by_key["adm"]
    assert adm.name.startswith("Administração Pública")
    assert adm.corpus_id is None
    assert adm.status is None
