"""Deterministic descriptive statistics for arbitrary CSV plot data.

Purpose: give the LLM the EXACT descriptive numbers (count / min / max / mean /
median / std-dev) for every unambiguously-numeric column of the plot CSV, so it
never has to compute them itself. Arithmetic is precisely where small local
models hallucinate (observed live: qwen2.5:7b reported media=21.8% when the true
mean was 82.9%, and max=31% for a 96.9% value).

Anti-bias design constraint: this module ONLY computes domain-agnostic
descriptive statistics on columns that are unambiguously numeric. It NEVER
derives semantic metrics — ratios, percentages-of-total, growth rates,
period-over-period variation — because those require knowing what a column
*means*, and a limited implementation there WOULD bias the result. That
interpretation stays with the model. Ambiguous / non-numeric columns are
reported as such (never silently dropped), so nothing is hidden from the model.

The caller injects the returned text block into task 7's prompt; the model is
told to USE these values for `metricas_estimadas` and to compute only what the
block does not provide (semantic derivations).
"""

from __future__ import annotations

import csv
import io
import statistics
from typing import List, Optional, Tuple


def _to_float(value: str) -> Optional[float]:
    """Parse a scalar to float, tolerating pt-BR decimal comma and currency.

    Returns None when the value is not unambiguously numeric. Conservative on
    purpose: ambiguous strings (e.g. a lone thousands separator) fail closed so
    we never feed the model a wrong number.
    """
    v = value.strip()
    if not v:
        return None
    # Strip currency symbols, spaces and a trailing % sign (the number stays).
    for ch in ("R$", "$", "\u00a0", " "):
        v = v.replace(ch, "")
    if v.endswith("%"):
        v = v[:-1]
    if v in ("", "-", "+", "--", "++"):
        return None

    # Both separators present → the LAST one is the decimal separator.
    if "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".")
    elif v.count(",") == 1 and "." not in v:
        # pt-BR decimal comma is the convention in this data domain.
        v = v.replace(",", ".")
    elif v.count(",") > 1 and "." not in v:
        # Multiple commas → thousands separators, no decimal part.
        v = v.replace(",", "")
    elif v.count(".") > 1 and "," not in v:
        v = v.replace(".", "")

    try:
        return float(v)
    except ValueError:
        return None


def _is_numeric_column(values: List[str]) -> bool:
    """A column is numeric when a clear majority of non-empty cells parse."""
    non_empty = [v for v in values if v.strip()]
    if not non_empty:
        return False
    parsed = sum(1 for v in non_empty if _to_float(v) is not None)
    return parsed >= 2 and parsed / len(non_empty) >= 0.66


def _describe(values: List[str]) -> Tuple[List[float], str]:
    """Return (parsed floats, human summary) for a numeric column."""
    nums: List[float] = []
    for v in values:
        if not v.strip():
            continue
        f = _to_float(v)
        if f is not None:
            nums.append(f)
    missing = sum(1 for v in values if not v.strip())
    n = len(nums)
    if n == 0:
        return [], "sem valores numéricos"
    mean = statistics.fmean(nums)
    median = statistics.median(nums)
    std = statistics.pstdev(nums) if n > 1 else 0.0
    parts = [
        f"n={n}",
        f"min={min(nums):g}",
        f"max={max(nums):g}",
        f"media={mean:.3f}",
        f"mediana={median:g}",
        f"desvio_padrao={std:.3f}",
    ]
    if missing:
        parts.append(f"vazios={missing}")
    return nums, ", ".join(parts)


def compute_csv_stats(file_obj) -> str:
    """Compute deterministic descriptive stats for a plot CSV (TextFile or None).

    Returns a PT-BR markdown/text block to inject into task 7's prompt, or an
    empty string when the file is absent/unreadable or has nothing to compute.
    Never raises — a stats failure must not fail the analysis (the model can
    still read the raw CSV injected via the {plot_data} placeholder).
    """
    if file_obj is None:
        return ""
    try:
        text = file_obj.read_text()
    except Exception:
        return ""

    if not text.strip():
        return ""

    # Sniff the dialect (delimiter + header); fall back to comma, no header.
    try:
        sample = text[:8192]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        dialect = csv.excel
        has_header = False

    try:
        rows = list(csv.reader(io.StringIO(text), dialect))
    except Exception:
        return ""

    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""

    # Column-major view. If there is a header, it names the columns; otherwise
    # columns are positional (C1, C2, ...).
    if has_header:
        header = rows[0]
        body = rows[1:]
        names = [h.strip() if h.strip() else f"col{i+1}" for i, h in enumerate(header)]
    else:
        body = rows
        ncols = max(len(r) for r in body) if body else 0
        names = [f"col{i+1}" for i in range(ncols)]

    nrows = len(body)
    ncols = max((len(r) for r in body), default=0)

    numeric_lines: List[str] = []
    categorical: List[str] = []
    for ci in range(ncols):
        col_values = [r[ci].strip() if ci < len(r) else "" for r in body]
        if _is_numeric_column(col_values):
            _, summary = _describe(col_values)
            numeric_lines.append(f"- **{names[ci]}** (numérica): {summary}")
        else:
            uniq = sorted({v for v in col_values if v})
            preview = ", ".join(uniq[:8])
            more = f" +{len(uniq) - 8} outros" if len(uniq) > 8 else ""
            categorical.append(
                f"- **{names[ci]}** (categórica/texto): {len(uniq)} valores distintos"
                + (f" ({preview}{more})" if uniq else "")
            )

    if not numeric_lines and not categorical:
        return ""

    block = [
        "",
        "MÉTRICAS CALCULADAS (determinísticas — já calculadas a partir do CSV, "
        "use estes valores exatos, NÃO recalcule):",
        f"- Total de registros (linhas de dados): {nrows}",
    ]
    if numeric_lines:
        block.append("Colunas numéricas (estatísticas descritivas exatas):")
        block.extend(numeric_lines)
    if categorical:
        block.append("Colunas não numéricas (trate como rótulos/categorias):")
        block.extend(categorical)
    block.append(
        "Use estes valores para `metricas_estimadas` (minimo, maximo, media, "
        "desvio_padrao). Calcule apenas o que este bloco NÃO fornece — por "
        "exemplo percentuais derivados (X / total × 100), variação entre "
        "períodos nomeados ou razões — sempre a partir destes números, nunca "
        "de estimativas visuais."
    )
    return "\n".join(block)
