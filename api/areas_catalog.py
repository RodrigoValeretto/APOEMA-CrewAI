"""Static de-para catalog: CAPES area filename code -> official area name.

Auditable mapping used by the Drive ingestion to populate ``corpora.name``
and by the areas endpoint. The filename prefix (e.g. ``COMPUTACAO``, ``CB_I``)
is the code; ``area_key`` (its slug) is the textual key accepted in requests
(``corpus_key``) and stored as ``corpora.slug``.

Source: CAPES "Tabela de Áreas de Avaliação" (gov.br), quadriênio 2025-2028.
"""

import re
from typing import Optional

from api.validators import slugify

# code (filename prefix, uppercase) -> official CAPES area name
CAPES_AREAS = {
    "ADM": "Administração Pública e de Empresas, Ciências Contábeis e Turismo",
    "ANTROPOLOGIA_ARQUEOLOGIA": "Antropologia / Arqueologia",
    "ARTES": "Artes",
    "ASTRON_FISICA": "Astronomia / Física",
    "AUD": "Arquitetura, Urbanismo e Design",
    "BIODIVERSIDADE": "Biodiversidade",
    "BIOTEC": "Biotecnologia",
    "C_AGRARIAS": "Ciências Agrárias I",
    "C_ALIMENTOS": "Ciência de Alimentos",
    "C_AMBIENTAIS": "Ciências Ambientais",
    "CB_I": "Ciências Biológicas I",
    "CB_II": "Ciências Biológicas II",
    "CB_III": "Ciências Biológicas III",
    "CHEB": "Ciências e Humanidades para a Educação Básica",
    "CIENCIA_POLITICA_RI": "Ciência Política e Relações Internacionais",
    "CIENCIA_RELIGIAO_TEOLOGIA": "Ciências da Religião e Teologia",
    "COMPUTACAO": "Computação",
    "COMUNICACAO": "Comunicação, Informação e Museologia",
    "DIREITO": "Direito",
    "ECONOMIA": "Economia",
    "ED_FISICA": "Educação Física, Fisioterapia, Fonoaudiologia e Terapia Ocupacional",
    "EDUCACAO": "Educação",
    "ENFERMAGEM": "Enfermagem",
    "ENG_I": "Engenharias I",
    "ENG_II": "Engenharias II",
    "ENG_III": "Engenharias III",
    "ENG_IV": "Engenharias IV",
    "ENSINO": "Ensino",
    "FARMACIA": "Farmácia",
    "FILOSOFIA": "Filosofia",
    "GEOCIENCIAS": "Geociências",
    "GEOGRAFIA": "Geografia",
    "HISTORIA": "História",
    "INTER": "Interdisciplinar",
    "LINGUISTICA_LITERATURA": "Linguística e Literatura",
    "MAPE": "Matemática / Probabilidade e Estatística",
    "MATERIAIS": "Materiais",
    "MED_I": "Medicina I",
    "MED_II": "Medicina II",
    "MED_III": "Medicina III",
    "MED_VET": "Medicina Veterinária",
    "NUTRICAO": "Nutrição",
    "ODONTO": "Odontologia",
    "PLURD": "Planejamento Urbano e Regional / Demografia",
    "PSICOLOGIA": "Psicologia",
    "QUIMICA": "Química",
    "SAUDE_COLETIVA": "Saúde Coletiva",
    "SERV_SOCIAL": "Serviço Social",
    "SOCIOLOGIA": "Sociologia",
    "ZOOTECNIA": "Zootecnia / Recursos Pesqueiros",
}

_FORM_MARKER = "_FICHA_"
_ATTACHMENT_MARKER = "_ANEXO_FICHA_"
_QUADRENNIUM_RE = re.compile(r"20\d{2}_20\d{2}")


def area_key(code: str) -> str:
    """Textual key for an area code (slugified filename prefix)."""
    return slugify(code)


def area_name(code: str) -> Optional[str]:
    """Official CAPES area name for a filename code, or None if unknown."""
    return CAPES_AREAS.get(code)


def area_code_from_name(name: str) -> Optional[str]:
    """Reverse lookup: official CAPES area name -> area code.

    Matches on the slugified name so punctuation variants still resolve to the
    same code (APOEMA's ``info-report`` uses ``-`` where the catalog uses ``/``,
    e.g. ``"Zootecnia - Recursos Pesqueiros"`` vs ``"Zootecnia / Recursos
    Pesqueiros"`` — both slugify to ``zootecnia_recursos_pesqueiros``).
    """
    target = slugify(name)
    for code, official in CAPES_AREAS.items():
        if slugify(official) == target:
            return code
    return None


def parse_area_filename(name: str):
    """Parse a drive filename into (area_code, kind) or None if unrecognized.

    ``kind`` is ``"form"`` (``*_FICHA_*``) or ``"attachment"``
    (``*_ANEXO_FICHA_*``). Attachments belong to the parent area
    (``BIOTEC_ANEXO_FICHA_*`` -> ``BIOTEC``).
    """
    if not name or not name.lower().endswith(".pdf"):
        return None
    stem = name[:-4]  # strip ".pdf"
    if _ATTACHMENT_MARKER in stem:
        area_code = stem.split(_ATTACHMENT_MARKER, 1)[0]
        kind = "attachment"
    elif _FORM_MARKER in stem:
        area_code = stem.split(_FORM_MARKER, 1)[0]
        kind = "form"
    else:
        return None
    return area_code, kind


def parse_quadrennium(name: str):
    """Extract the quadriênio label from a filename (e.g. '2025-2028')."""
    m = _QUADRENNIUM_RE.search(name)
    return m.group(0).replace("_", "-") if m else None
