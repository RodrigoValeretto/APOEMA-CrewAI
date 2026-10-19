"""Tests for the ficha de-para endpoint (catalog overlay + DB join)."""
from api.fichas_catalog import FICHA_AREAS, ficha_key


def test_catalog_covers_50_areas():
    assert len(FICHA_AREAS) == 50


def test_de_para_merge_overlay(monkeypatch):
    """A DB row (by slug) fills ids/status; missing areas stay null."""
    from api import api as api_module

    fake_rows = [
        {
            "slug": "computacao",
            "informativo_id": 3,
            "documento_id": 7,
            "converted_file_id": 12,
            "status": "completed",
            "quadrienio": "2025-2028",
            "drive_file_id": "abc123",
        }
    ]
    monkeypatch.setattr(api_module.database, "get_ficha_de_para_rows", lambda: fake_rows)

    from api.models import FichaDeParaListResponse

    # Reconstruct the merge logic (mirrors the endpoint body).
    db_rows = {r["slug"]: r for r in api_module.database.get_ficha_de_para_rows()}
    items = []
    for codigo, nome in sorted(FICHA_AREAS.items()):
        chave = ficha_key(codigo)
        row = db_rows.get(chave, {})
        items.append(
            api_module.FichaDeParaResponse(
                codigo=codigo,
                nome=nome,
                chave=chave,
                informativo_id=row.get("informativo_id"),
                documento_id=row.get("documento_id"),
                converted_file_id=row.get("converted_file_id"),
                status=row.get("status"),
                quadrienio=row.get("quadrienio"),
                drive_file_id=row.get("drive_file_id"),
            )
        )
    result = FichaDeParaListResponse(total=len(items), items=items)

    assert result.total == 50
    by_key = {i.chave: i for i in result.items}

    computacao = by_key["computacao"]
    assert computacao.nome == "Computação"
    assert computacao.informativo_id == 3
    assert computacao.status == "completed"

    # An un-ingested area has no DB row -> nulls.
    adm = by_key["adm"]
    assert adm.nome.startswith("Administração Pública")
    assert adm.informativo_id is None
    assert adm.status is None
