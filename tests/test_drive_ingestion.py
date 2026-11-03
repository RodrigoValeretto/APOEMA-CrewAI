"""Tests for the Google Drive ficha ingestion (api/drive_ingestion.py).

Covers the two halves the feature adds beyond the (already-tested) catalog
parsing: the Drive folder enumeration/download, and the idempotent ingestion
orchestration (dedupe by drive_file_id, re-enqueue only failed docs, per-file
isolation). Also exercises the real `GET /api/fichas` endpoint.
"""
import sys
import types

from api import drive_ingestion
from api.drive_ingestion import _ENTRY_RE, ingest_drive_folder, list_drive_folder

FOLDER = "1AI8fJoE9PU366xdGA0Af0kmiS3PdGsVb"


# ── Drive folder enumeration ────────────────────────────────────────────────


class TestEntryRegex:
    def test_extracts_file_id_and_name(self):
        html = """
        <div id="entry-1AbCdEfGhIjKlMnOpQrStUv" class="flip-entry">
          <div class="flip-entry-title">COMPUTACAO_FICHA_2025_2028.pdf</div>
        </div>
        <div id="entry-Z9yXwVuTsRqPoNmLkJiHgFe" class="flip-entry">
          <div class="flip-entry-title">BIOTEC_ANEXO_FICHA_2025_2028.pdf</div>
        </div>
        """
        matches = list(_ENTRY_RE.finditer(html))
        assert [m.group(1) for m in matches] == [
            "1AbCdEfGhIjKlMnOpQrStUv",
            "Z9yXwVuTsRqPoNmLkJiHgFe",
        ]
        assert [m.group(2) for m in matches] == [
            "COMPUTACAO_FICHA_2025_2028.pdf",
            "BIOTEC_ANEXO_FICHA_2025_2028.pdf",
        ]

    def test_ignores_short_ids(self):
        html = (
            '<div id="entry-short" class="flip-entry">'
            '<div class="flip-entry-title">x.pdf</div></div>'
        )
        assert list(_ENTRY_RE.finditer(html)) == []


class TestListDriveFolder:
    def test_returns_file_id_name_pairs(self, monkeypatch):
        html = (
            "<html><body>"
            '<div id="entry-AAAAAAAAAAAAAAAAAAAA" class="flip-entry">'
            '<div class="flip-entry-title">A_FICHA_2025_2028.pdf</div>'
            "</div></body></html>"
        )
        captured = {}

        class _Resp:
            text = html

            def raise_for_status(self):
                pass

        monkeypatch.setattr(
            drive_ingestion.requests,
            "get",
            lambda url, timeout: captured.update(url=url) or _Resp(),
        )

        result = list_drive_folder(FOLDER)
        assert result == [{"file_id": "AAAAAAAAAAAAAAAAAAAA", "name": "A_FICHA_2025_2028.pdf"}]
        assert f"embeddedfolderview?id={FOLDER}" in captured["url"]

    def test_http_error_propagates(self, monkeypatch):
        class _Resp:
            def raise_for_status(self):
                raise RuntimeError("403")

        monkeypatch.setattr(
            drive_ingestion.requests, "get", lambda url, timeout: _Resp()
        )
        try:
            list_drive_folder(FOLDER)
            assert False, "expected raise"
        except RuntimeError:
            pass


# ── Ingestion orchestration ─────────────────────────────────────────────────


class _FakeDatabase:
    """Records the calls ingest_drive_folder makes against the DB layer."""

    def __init__(self, docs_by_file_id=None, informativos_by_slug=None):
        self.docs_by_file_id = docs_by_file_id or {}
        self.informativos_by_slug = informativos_by_slug or {}
        self.created_informativos = []
        self.created_documents = []
        self.next_informativo_id = 1
        self.next_document_id = 1

    def get_informativo_document_by_drive_file_id(self, file_id):
        return self.docs_by_file_id.get(file_id)

    def get_informativo_by_slug(self, slug):
        return self.informativos_by_slug.get(slug)

    def create_informativo(self, nome, slug, quadrienio):
        iid = self.next_informativo_id
        self.next_informativo_id += 1
        self.created_informativos.append(
            {"nome": nome, "slug": slug, "quadrienio": quadrienio}
        )
        self.informativos_by_slug[slug] = {"id": iid}
        return iid

    def create_informativo_document(
        self, informativo_id, kind, original_file_id, drive_file_id=None
    ):
        did = self.next_document_id
        self.next_document_id += 1
        self.created_documents.append(
            {
                "informativo_id": informativo_id,
                "kind": kind,
                "original_file_id": original_file_id,
                "drive_file_id": drive_file_id,
            }
        )
        return did


def _install_fakes(monkeypatch, db, entries, sent):
    """Wire list_drive_folder/download/_save_downloaded_pdf and the lazy
    ``conversion_tasks`` import to fakes; returns the fake db."""
    monkeypatch.setattr(drive_ingestion, "database", db)

    def _fake_list(folder_id):
        return entries

    monkeypatch.setattr(drive_ingestion, "list_drive_folder", _fake_list)
    monkeypatch.setattr(
        drive_ingestion, "download_drive_file", lambda file_id: b"PDFBYTES"
    )

    # download is exercised separately; save registers an analysis_file.
    def _fake_save(name, content):
        db.created_files = getattr(db, "created_files", [])
        db.created_files.append(name)
        return 900 + len(db.created_files)

    monkeypatch.setattr(drive_ingestion, "_save_downloaded_pdf", _fake_save)

    # Avoid importing the real conversion_tasks (pulls dramatiq broker).
    fake_ct = types.ModuleType("conversion_tasks")
    fake_ct.convert_informativo_document = types.SimpleNamespace(
        send=lambda **kw: sent.append(kw)
    )
    monkeypatch.setitem(sys.modules, "conversion_tasks", fake_ct)
    return db


class TestIngestDriveFolder:
    def test_new_file_registers_and_enqueues(self, monkeypatch):
        db = _FakeDatabase()
        sent = []
        entries = [{"file_id": "f1", "name": "COMPUTACAO_FICHA_2025_2028.pdf"}]
        _install_fakes(monkeypatch, db, entries, sent)

        stats = ingest_drive_folder(FOLDER)

        assert stats == {
            "total": 1,
            "downloaded": 1,
            "new_documents": 1,
            "reenqueued": 0,
            "skipped": 0,
            "errors": 0,
        }
        assert db.created_informativos == [
            {"nome": "Computação", "slug": "computacao", "quadrienio": "2025-2028"}
        ]
        assert len(db.created_documents) == 1
        doc = db.created_documents[0]
        assert doc["kind"] == "ficha"
        assert doc["drive_file_id"] == "f1"
        assert doc["informativo_id"] == 1
        assert sent == [{"document_id": 1}]

    def test_completed_doc_is_skipped_idempotently(self, monkeypatch):
        db = _FakeDatabase(
            docs_by_file_id={"f1": {"id": 5, "status": "completed"}}
        )
        sent = []
        entries = [{"file_id": "f1", "name": "COMPUTACAO_FICHA_2025_2028.pdf"}]
        _install_fakes(monkeypatch, db, entries, sent)

        stats = ingest_drive_folder(FOLDER)

        assert stats["skipped"] == 1
        assert stats["downloaded"] == 0
        assert stats["new_documents"] == 0
        assert db.created_documents == []
        assert sent == []

    def test_pending_doc_is_skipped_not_reenqueued(self, monkeypatch):
        """A pending doc is already queued (durable message); re-enqueueing on
        every startup would duplicate messages and bloat the queue."""
        db = _FakeDatabase(
            docs_by_file_id={"f1": {"id": 7, "status": "pending"}}
        )
        sent = []
        entries = [{"file_id": "f1", "name": "COMPUTACAO_FICHA_2025_2028.pdf"}]
        _install_fakes(monkeypatch, db, entries, sent)

        stats = ingest_drive_folder(FOLDER)

        assert stats["skipped"] == 1
        assert stats["reenqueued"] == 0
        assert stats["downloaded"] == 0
        assert stats["new_documents"] == 0
        assert sent == []

    def test_failed_doc_is_reenqueued(self, monkeypatch):
        db = _FakeDatabase(
            docs_by_file_id={"f1": {"id": 8, "status": "failed"}}
        )
        sent = []
        entries = [{"file_id": "f1", "name": "COMPUTACAO_FICHA_2025_2028.pdf"}]
        _install_fakes(monkeypatch, db, entries, sent)

        stats = ingest_drive_folder(FOLDER)

        assert stats["reenqueued"] == 1
        assert sent == [{"document_id": 8}]

    def test_unrecognized_filename_is_skipped(self, monkeypatch):
        db = _FakeDatabase()
        sent = []
        entries = [{"file_id": "f1", "name": "NOT_A_FICHA.pdf"}]
        _install_fakes(monkeypatch, db, entries, sent)

        stats = ingest_drive_folder(FOLDER)

        assert stats["skipped"] == 1
        assert stats["downloaded"] == 0
        assert db.created_documents == []
        assert sent == []

    def test_unknown_area_code_is_skipped(self, monkeypatch):
        db = _FakeDatabase()
        sent = []
        entries = [{"file_id": "f1", "name": "DOES_NOT_EXIST_FICHA_2025_2028.pdf"}]
        _install_fakes(monkeypatch, db, entries, sent)

        stats = ingest_drive_folder(FOLDER)

        assert stats["skipped"] == 1
        assert db.created_informativos == []
        assert sent == []

    def test_anexo_belongs_to_parent_area(self, monkeypatch):
        db = _FakeDatabase()
        sent = []
        entries = [{"file_id": "f1", "name": "BIOTEC_ANEXO_FICHA_2025_2028.pdf"}]
        _install_fakes(monkeypatch, db, entries, sent)

        stats = ingest_drive_folder(FOLDER)

        assert stats["new_documents"] == 1
        assert db.created_informativos[0]["slug"] == "biotec"
        assert db.created_documents[0]["kind"] == "anexo"

    def test_bad_file_does_not_abort_the_run(self, monkeypatch):
        """Per-file isolation: a download failure counts an error, the next
        file is still processed."""
        db = _FakeDatabase()
        sent = []
        entries = [
            {"file_id": "bad", "name": "COMPUTACAO_FICHA_2025_2028.pdf"},
            {"file_id": "good", "name": "DIREITO_FICHA_2025_2028.pdf"},
        ]

        def _fake_list(folder_id):
            return entries

        def _fake_download(file_id):
            if file_id == "bad":
                raise RuntimeError("drive down")
            return b"PDFBYTES"

        monkeypatch.setattr(drive_ingestion, "database", db)
        monkeypatch.setattr(drive_ingestion, "list_drive_folder", _fake_list)
        monkeypatch.setattr(drive_ingestion, "download_drive_file", _fake_download)
        monkeypatch.setattr(
            drive_ingestion, "_save_downloaded_pdf", lambda name, c: 900
        )
        fake_ct = types.ModuleType("conversion_tasks")
        fake_ct.convert_informativo_document = types.SimpleNamespace(
            send=lambda **kw: sent.append(kw)
        )
        monkeypatch.setitem(sys.modules, "conversion_tasks", fake_ct)

        stats = ingest_drive_folder(FOLDER)

        # The bad file's download failed: it counts an error, no document is
        # registered for it, and the good file is still processed afterwards
        # (per-file isolation). NB: the informativo is created BEFORE the
        # download (drive_ingestion.py:143-150), so the failed area still gets
        # an informativo row — harmless, and reused idempotently on the next run.
        assert stats["errors"] == 1
        assert stats["new_documents"] == 1
        assert [d["kind"] for d in db.created_documents] == ["ficha"]
        assert db.created_documents[0]["drive_file_id"] == "good"
        assert db.created_informativos[-1]["slug"] == "direito"

    def test_reuses_existing_informativo_by_slug(self, monkeypatch):
        db = _FakeDatabase(
            informativos_by_slug={"computacao": {"id": 42}}
        )
        sent = []
        entries = [{"file_id": "f1", "name": "COMPUTACAO_FICHA_2025_2028.pdf"}]
        _install_fakes(monkeypatch, db, entries, sent)

        stats = ingest_drive_folder(FOLDER)

        assert stats["new_documents"] == 1
        assert db.created_informativos == []
        assert db.created_documents[0]["informativo_id"] == 42


# ── Real de-para endpoint ───────────────────────────────────────────────────


class TestFichasDeParaEndpoint:
    def test_returns_all_50_catalogued_areas(self, monkeypatch):
        from fastapi.testclient import TestClient

        from api import api as api_module

        # No ingested rows yet: every area should appear with null ids/status.
        monkeypatch.setattr(
            api_module.database, "get_ficha_de_para_rows", lambda: []
        )
        # No lifespan context -> zombie watchdog / drive auto-ingest do not run.
        client = TestClient(api_module.app)

        resp = client.get("/api/fichas")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 50
        assert len(body["items"]) == 50
        first = body["items"][0]
        assert first["informativo_id"] is None
        assert first["status"] is None

    def test_overlays_ingested_state(self, monkeypatch):
        from fastapi.testclient import TestClient

        from api import api as api_module

        monkeypatch.setattr(
            api_module.database,
            "get_ficha_de_para_rows",
            lambda: [
                {
                    "slug": "computacao",
                    "informativo_id": 3,
                    "documento_id": 7,
                    "converted_file_id": 12,
                    "status": "completed",
                    "quadrienio": "2025-2028",
                    "drive_file_id": "abc123",
                }
            ],
        )
        client = TestClient(api_module.app)

        resp = client.get("/api/fichas")
        assert resp.status_code == 200
        by_key = {i["chave"]: i for i in resp.json()["items"]}

        assert by_key["computacao"]["informativo_id"] == 3
        assert by_key["computacao"]["status"] == "completed"
        assert by_key["computacao"]["drive_file_id"] == "abc123"
        # Un-ingested area stays null.
        assert by_key["adm"]["informativo_id"] is None


class TestClaimAcceptsFailed:
    """The conversion claim must re-accept a 'failed' doc so the ingestion's
    re-enqueue can actually retry it (before the fix, a re-enqueued failed doc
    hit "Not claimed" and stayed failed forever)."""

    def _claim_sql(self, monkeypatch):
        from api import database

        captured = {}

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params
                self.rowcount = 0

        class _Conn:
            def cursor(self):
                return _Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def commit(self):
                pass

        monkeypatch.setattr(database, "get_connection", lambda: _Conn())
        database.claim_informativo_document(123)
        return captured

    def test_claim_accepts_failed_status(self, monkeypatch):
        captured = self._claim_sql(monkeypatch)
        assert "status = 'failed'" in captured["sql"]

    def test_claim_still_accepts_pending(self, monkeypatch):
        captured = self._claim_sql(monkeypatch)
        assert "status = 'pending'" in captured["sql"]
