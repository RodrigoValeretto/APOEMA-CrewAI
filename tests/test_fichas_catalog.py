"""Tests for the CAPES ficha catalog (filename -> code -> key -> official name)."""
from api.fichas_catalog import (
    FICHA_AREAS,
    area_name,
    ficha_key,
    parse_ficha_filename,
    parse_quadrienio,
)


class TestParseFichaFilename:
    def test_ficha(self):
        assert parse_ficha_filename("COMPUTACAO_FICHA_2025_2028.pdf") == (
            "COMPUTACAO",
            "ficha",
        )

    def test_anexo_belongs_to_parent_area(self):
        assert parse_ficha_filename("BIOTEC_ANEXO_FICHA_2025_2028.pdf") == (
            "BIOTEC",
            "anexo",
        )

    def test_numbered_area_keeps_numeral(self):
        assert parse_ficha_filename("CB_II_FICHA_2025_2028.pdf") == ("CB_II", "ficha")

    def test_non_pdf_ignored(self):
        assert parse_ficha_filename("COMPUTACAO_FICHA_2025_2028.xlsx") is None

    def test_unknown_pattern_ignored(self):
        assert parse_ficha_filename("NOT_A_FICHA.pdf") is None


class TestFichaKey:
    def test_plain_code(self):
        assert ficha_key("COMPUTACAO") == "computacao"

    def test_numbered_code(self):
        assert ficha_key("CB_I") == "cb_i"
        assert ficha_key("ENG_IV") == "eng_iv"

    def test_underscored_code(self):
        assert ficha_key("ANTROPOLOGIA_ARQUEOLOGIA") == "antropologia_arqueologia"


class TestAreaName:
    def test_all_50_areas_present(self):
        assert len(FICHA_AREAS) == 50

    def test_known_codes(self):
        assert area_name("COMPUTACAO") == "Computação"
        adm = area_name("ADM")
        assert adm is not None and adm.startswith("Administração Pública")
        assert area_name("ZOOTECNIA") == "Zootecnia / Recursos Pesqueiros"

    def test_unknown_code(self):
        assert area_name("DOES_NOT_EXIST") is None


class TestParseQuadrienio:
    def test_2025_2028(self):
        assert parse_quadrienio("COMPUTACAO_FICHA_2025_2028.pdf") == "2025-2028"

    def test_2025_2029(self):
        assert parse_quadrienio("ZOOTECNIA_FICHA_2025_2029.pdf") == "2025-2029"
