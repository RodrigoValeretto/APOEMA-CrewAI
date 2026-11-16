"""Tests for save_analysis_result's JSONB round-trip (regression: dict adapt).

Before the fix, psycopg raised "cannot adapt type 'dict'" when a task result was
a JSON object. This pins that a JSON-object result stores parsed in
``result_json`` with ``result`` NULL, and round-trips back as a dict.
"""
import json

from api import database


class _Cursor:
    def __init__(self, row_factory=None):
        self.params = None
        self.row_factory = row_factory

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return (1,)


class _Conn:
    def __init__(self):
        self.cursor_obj = _Cursor()

    def cursor(self, row_factory=None):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        return None


def test_json_object_serialized_not_dict(monkeypatch):
    """The bound param must be a JSON STRING, never a raw dict (psycopg bug)."""
    conn = _Conn()
    monkeypatch.setattr(database, "get_connection", lambda: conn)
    monkeypatch.setattr(database, "datetime", type("D", (), {"now": lambda: "2026-01-01"}))

    database.save_analysis_result(1, "task_1_data_analysis", '{"area": "X", "peso": 30}')

    # The INSERT is the 2nd execute (DELETE first). Its params: (id, name, result, result_json, created_at)
    insert_params = conn.cursor_obj.params
    assert insert_params[2] is None  # result -> NULL
    assert isinstance(insert_params[3], str)  # result_json -> JSON string
    assert json.loads(insert_params[3]) == {"area": "X", "peso": 30}


def test_markdown_result_keeps_text(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(database, "get_connection", lambda: conn)
    monkeypatch.setattr(database, "datetime", type("D", (), {"now": lambda: "2026-01-01"}))

    database.save_analysis_result(1, "task_2_summarization", "# Relatório\n\ntexto")

    insert_params = conn.cursor_obj.params
    assert insert_params[2] == "# Relatório\n\ntexto"
    assert insert_params[3] is None
