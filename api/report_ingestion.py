"""APOEMA report ingestion.

Consumes a published APOEMA report by its id (the md5 in the report view URL
``https://sistemas.prpg.usp.br/apoema-pg/view/<id>``) and turns every chart of
that report into analysis inputs:

- ``GET {API_BASE}/api/v1/charts?md5=<id>`` lists the charts (``url_n``/``id``
  per chart, plus a ``hasfile`` flag).
- ``GET {API_BASE}/api/v1/info-report?md5=<id>`` describes the report: the
  ``progs`` field carries the program list, quadrennium years and the CAPES area
  name (``...:2021,2022,2023,2024@Area Name``).
- ``GET {VIEW_BASE}/chart/<id>+<chart_id>`` is the chart PNG (the ``+`` separator
  is literal in the path).
- ``GET {API_BASE}/api/v1/chartcsv?filename=<url-encoded png url>`` returns the
  chart's underlying data as JSON rows.

This module only talks to APOEMA and parses its responses; the FastAPI layer
downloads the assets, registers them and enqueues one ``png_csv`` analysis per
chart.
"""
import csv
import io
import logging
import re
from typing import Any, Dict, List
from urllib.parse import quote

import requests

from .exceptions import URLFetchError

logger = logging.getLogger(__name__)

VIEW_BASE = "https://sistemas.prpg.usp.br"
API_BASE = "https://sistemas.prpg.usp.br:9396"

_CHARTS_URL = API_BASE + "/api/v1/charts?md5={report_id}"
_INFO_URL = API_BASE + "/api/v1/info-report?md5={report_id}"
_CHART_PNG_URL = VIEW_BASE + "/chart/{report_id}+{chart_id}"
_CHART_CSV_URL = API_BASE + "/api/v1/chartcsv?filename={filename}"

_REPORT_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")
_CHART_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

_REQUEST_TIMEOUT = 30


def validate_report_id(report_id: str) -> bool:
    """True when the report id is a safe hex token (defense against injection)."""
    return bool(_REPORT_ID_RE.fullmatch(report_id))


def validate_chart_id(chart_id: str) -> bool:
    """True when a chart id is a safe path token (defense against injection)."""
    return bool(_CHART_ID_RE.fullmatch(chart_id))


def chart_png_url(report_id: str, chart_id: str) -> str:
    """Absolute URL of a chart's PNG (the ``+`` separator is literal in the path)."""
    return _CHART_PNG_URL.format(report_id=report_id, chart_id=chart_id)


def chart_csv_url(png_url: str) -> str:
    """``chartcsv`` URL whose ``filename`` param is the fully-encoded PNG URL."""
    return _CHART_CSV_URL.format(filename=quote(png_url, safe=""))


def _get_json(url: str) -> Dict[str, Any]:
    """GET a JSON endpoint and return the parsed object, raising on failure."""
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise URLFetchError(f"Failed to fetch {url}: {e}") from e


def fetch_charts(report_id: str) -> List[Dict[str, Any]]:
    """Return the raw chart entries (``{url_n, id, hasfile, ...}``) of a report."""
    payload = _get_json(_CHARTS_URL.format(report_id=report_id))
    return payload.get("charts") or []


def fetch_report_info(report_id: str) -> Dict[str, Any]:
    """Return the ``info-report`` payload (``{status, progs}``)."""
    return _get_json(_INFO_URL.format(report_id=report_id))


def report_area_name(info: Dict[str, Any]) -> str:
    """Extract the CAPES area name from an ``info-report`` payload.

    The ``progs`` field ends with ``@<area name>`` (e.g. ``...@Zootecnia -
    Recursos Pesqueiros``). Returns ``""`` when absent.
    """
    progs = info.get("progs") or ""
    if "@" in progs:
        return progs.rsplit("@", 1)[-1].strip()
    return ""


def fetch_chart_csv(png_url: str) -> Dict[str, Any]:
    """Return the ``chartcsv`` payload (``{status, data, headers}``) for a chart."""
    return _get_json(chart_csv_url(png_url))


def chart_csv_text(payload: Dict[str, Any]) -> str:
    """Serialize a ``chartcsv`` payload to CSV text.

    Uses the chart's declared ``headers`` (human ``text`` over the raw key) for
    the header row and the raw ``value`` keys to index each data row. Returns
    ``""`` when the chart has no data rows.
    """
    data = payload.get("data") or []
    if not data:
        return ""

    headers = payload.get("headers") or []
    columns = [h.get("value") for h in headers if h.get("value")] or list(data[0].keys())

    header_names = [
        h.get("text") or h.get("value") or col for h, col in zip(headers, columns)
    ]
    while len(header_names) < len(columns):
        header_names.append(columns[len(header_names)])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header_names)
    for row in data:
        writer.writerow([row.get(col, "") for col in columns])
    return buf.getvalue()
