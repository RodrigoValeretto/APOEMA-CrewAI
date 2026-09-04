"""Tests for informativo validation rules and helpers (no DB required)."""
from api.constants import (
    ALLOWED_FILE_EXTENSIONS,
    KIND_ALLOWED_EXTENSIONS,
    DocumentKind,
    FileType,
)
from api.models import AnalysisRequest
from api.validators import slugify, validate_analysis_request


class TestSlugify:
    def test_ciencia_da_computacao(self):
        assert slugify("Ciência da Computação") == "ciencia_da_computacao"

    def test_accents_and_punctuation(self):
        assert (
            slugify("Administração Pública e de Empresas, Ciências Contábeis e Turismo")
            == "administracao_publica_e_de_empresas_ciencias_contabeis_e_turismo"
        )

    def test_empty_falls_back(self):
        assert slugify("!!!") == "informativo"


class TestValidateAnalysisRequestInformativo:
    def test_informativo_id_alone_is_valid(self):
        is_valid, _ = validate_analysis_request(informativo_id=1)
        assert is_valid is True

    def test_informativo_with_assessment_is_invalid(self):
        is_valid, msg = validate_analysis_request(
            assessment_file="/tmp/x.json", informativo_id=1
        )
        assert is_valid is False
        assert "cannot be combined" in msg

    def test_nothing_provided_is_invalid(self):
        is_valid, msg = validate_analysis_request()
        assert is_valid is False
        assert "informativo_id" in msg

    def test_regular_assessment_still_valid(self):
        is_valid, _ = validate_analysis_request(assessment_file_id=1)
        assert is_valid is True


class TestAnalysisRequestModel:
    def test_informativo_id_default_none(self):
        request = AnalysisRequest.model_construct()
        assert request.informativo_id is None

    def test_informativo_id_accepted(self):
        request = AnalysisRequest.model_construct(
            informativo_id=3, model="ollama", important_programs=["X"]
        )
        assert request.informativo_id == 3
        assert request.model == "ollama"


class TestAllowedExtensions:
    def test_xlsx_type_registered(self):
        assert FileType.XLSX.value == "xlsx"
        assert ALLOWED_FILE_EXTENSIONS["xlsx"] == [".xlsx"]

    def test_kind_extension_matrix(self):
        assert KIND_ALLOWED_EXTENSIONS[DocumentKind.FICHA.value] == [".pdf"]
        for kind in (DocumentKind.ANEXO.value, DocumentKind.ADENDO.value):
            assert KIND_ALLOWED_EXTENSIONS[kind] == [".pdf", ".xlsx"]
