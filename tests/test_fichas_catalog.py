"""Tests for the CAPES area catalog (filename -> code -> key -> official name)."""
from api.areas_catalog import (
    CAPES_AREAS,
    area_key,
    area_name,
    parse_area_filename,
    parse_quadrennium,
)


class TestParseAreaFilename:
    def test_form(self):
        assert parse_area_filename("COMPUTACAO_FICHA_2025_2028.pdf") == (
            "COMPUTACAO",
            "form",
        )

    def test_attachment_belongs_to_parent_area(self):
        assert parse_area_filename("BIOTEC_ANEXO_FICHA_2025_2028.pdf") == (
            "BIOTEC",
            "attachment",
        )

    def test_numbered_area_keeps_numeral(self):
        assert parse_area_filename("CB_II_FICHA_2025_2028.pdf") == ("CB_II", "form")

    def test_non_pdf_ignored(self):
        assert parse_area_filename("COMPUTACAO_FICHA_2025_2028.xlsx") is None

    def test_unknown_pattern_ignored(self):
        assert parse_area_filename("NOT_A_FICHA.pdf") is None


class TestAreaKey:
    def test_plain_code(self):
        assert area_key("COMPUTACAO") == "computacao"

    def test_numbered_code(self):
        assert area_key("CB_I") == "cb_i"
        assert area_key("ENG_IV") == "eng_iv"

    def test_underscored_code(self):
        assert area_key("ANTROPOLOGIA_ARQUEOLOGIA") == "antropologia_arqueologia"


class TestAreaName:
    def test_all_50_areas_present(self):
        assert len(CAPES_AREAS) == 50

    def test_known_codes(self):
        assert area_name("COMPUTACAO") == "Computação"
        adm = area_name("ADM")
        assert adm is not None and adm.startswith("Administração Pública")
        assert area_name("ZOOTECNIA") == "Zootecnia / Recursos Pesqueiros"

    def test_unknown_code(self):
        assert area_name("DOES_NOT_EXIST") is None


class TestParseQuadrennium:
    def test_2025_2028(self):
        assert parse_quadrennium("COMPUTACAO_FICHA_2025_2028.pdf") == "2025-2028"

    def test_2025_2029(self):
        assert parse_quadrennium("ZOOTECNIA_FICHA_2025_2029.pdf") == "2025-2029"
