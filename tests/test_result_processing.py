"""Tests for result_processing.split_result_json."""
from api.result_processing import split_result_json


class TestSplitResultJson:
    def test_json_object_moves_to_result_json(self):
        text, obj = split_result_json('{"area": "Computação", "peso": 30}')
        assert text is None
        assert obj == {"area": "Computação", "peso": 30}

    def test_fenced_json_object(self):
        text, obj = split_result_json("```json\n{\"a\": 1}\n```")
        assert text is None
        assert obj == {"a": 1}

    def test_bare_fence_json_object(self):
        text, obj = split_result_json("```\n{\"a\": 1}\n```")
        assert text is None
        assert obj == {"a": 1}

    def test_markdown_stays_raw(self):
        raw = "# Relatório\n\nTexto livre."
        text, obj = split_result_json(raw)
        assert text == raw
        assert obj is None

    def test_json_array_stays_raw(self):
        raw = '[1, 2, 3]'
        text, obj = split_result_json(raw)
        assert text == raw
        assert obj is None

    def test_json_scalar_stays_raw(self):
        raw = '"apenas uma string"'
        text, obj = split_result_json(raw)
        assert text == raw
        assert obj is None

    def test_unparseable_stays_raw(self):
        raw = '{"invalido": '
        text, obj = split_result_json(raw)
        assert text == raw
        assert obj is None

    def test_none_returns_none(self):
        text, obj = split_result_json(None)
        assert text is None
        assert obj is None

    def test_whitespace_only_stays_raw(self):
        raw = "   \n  "
        text, obj = split_result_json(raw)
        assert text == raw
        assert obj is None
