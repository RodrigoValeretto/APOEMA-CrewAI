"""Post-processing of task results: split raw text from structured JSON.

A task whose output is a JSON object is stored as the parsed object in
``analysis_results.result_json`` (JSONB) with ``result`` set to NULL; any other
output keeps its raw text in ``result`` with ``result_json`` NULL.
"""
import json
from typing import Optional, Tuple

_FENCE = "```"


def split_result_json(result: Optional[str]) -> Tuple[Optional[str], Optional[dict]]:
    """Split a raw task result into ``(result_text, result_json)``.

    When ``result`` is a JSON **object** — optionally wrapped in a single
    fenced code block (`` ```json ... ``` `` or bare `` ``` ``) — the parsed
    dict is returned as the second element and the first is ``None`` (so the
    caller stores ``result`` as NULL). Any other content (markdown, a JSON
    array/scalar, or unparseable text) is returned verbatim as the first
    element with ``None`` for the JSON side.

    Args:
        result: Raw task output string (may be None).

    Returns:
        ``(result_text, result_json)`` where exactly one side is non-None
        (both None when ``result`` is None).
    """
    if result is None:
        return None, None

    text = result.strip()
    if not text:
        return result, None

    # Strip a single surrounding fenced code block, if present.
    if text.startswith(_FENCE):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith(_FENCE):
            lines = lines[1:]
        if lines and lines[-1].strip() == _FENCE:
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return result, None

    # Only a JSON object (dict) is treated as the structured result; arrays and
    # scalars stay as raw text (task outputs in APOEMA are always objects).
    if isinstance(obj, dict):
        return None, obj
    return result, None
