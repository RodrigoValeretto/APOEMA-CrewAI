"""Tests for plot_metrics — deterministic descriptive stats for plot CSVs."""

from plot_metrics import _to_float, compute_csv_stats


class _StubFile:
    """Minimal stand-in for crewai_files.TextFile — compute_csv_stats only
    calls .read_text(), so a stub isolates the logic from content-type detection
    (which crashes on StringIO / binary input)."""

    def __init__(self, text):
        self._text = text

    def read_text(self):
        return self._text


class _BoomFile:
    def read_text(self):
        raise OSError("unreadable")


# ─── Scalar parsing ────────────────────────────────────────────────


def test_to_float_plain_and_comma_decimal():
    assert _to_float("25") == 25.0
    assert _to_float("25,4") == 25.4
    assert _to_float(" 31 ") == 31.0


def test_to_float_percent_and_currency():
    assert _to_float("69,4%") == 69.4
    assert _to_float("R$ 1.234,56") == 1234.56


def test_to_float_thousands_separators():
    assert _to_float("1.234,5") == 1234.5  # both → last (comma) is decimal
    assert _to_float("1.234.567") == 1234567.0  # multiple dots → thousands


def test_to_float_ambiguous_fails_closed():
    assert _to_float("") is None
    assert _to_float("N/A") is None
    assert _to_float("-") is None


# ─── Column stats ──────────────────────────────────────────────────


def test_compute_csv_stats_numeric_and_categorical():
    csv_text = (
        "Sigla,PERMANENTE,Total\n"
        "UFBA,25,36\n"
        "UFPA,23,29\n"
        "UNB,31,32\n"
    )
    block = compute_csv_stats(_StubFile(csv_text))
    assert "Total de registros (linhas de dados): 3" in block
    assert "PERMANENTE" in block
    assert "min=23" in block
    assert "max=31" in block
    assert "media=26.333" in block
    assert "Sigla" in block  # categorical column reported, not dropped


def test_compute_csv_stats_pt_br_decimals():
    # pt-BR CSVs with comma decimals use ';' as the delimiter (a comma
    # delimiter cannot carry unquoted comma decimals — the fields would split).
    csv_text = "curso;media_nota\nA;8,5\nB;7,2\nC;9,1\n"
    block = compute_csv_stats(_StubFile(csv_text))
    assert "media_nota" in block
    assert "max=9.1" in block


def test_compute_csv_stats_empty_or_missing():
    assert compute_csv_stats(None) == ""
    assert compute_csv_stats(_StubFile("")) == ""


def test_compute_csv_stats_all_text_no_numbers():
    csv_text = "nome,sobrenome\na,b\nc,d\n"
    block = compute_csv_stats(_StubFile(csv_text))
    # No numeric columns → no "Colunas numéricas" section, but still reports
    # the row count and categorical columns.
    assert "Total de registros (linhas de dados): 2" in block
    assert "Colunas numéricas" not in block
    assert "nome" in block


def test_compute_csv_stats_never_raises():
    # An unreadable file must degrade to "" rather than raise.
    assert compute_csv_stats(_BoomFile()) == ""
