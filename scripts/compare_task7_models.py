#!/usr/bin/env python3
"""Compare phi4-mini vs qwen2.5:3b on the task-7 style prompt (2026-09-09).

Builds a realistic task-7 prompt from the real CSV + a real vision description
and asks each model for the JSON analysis, to see which one answers instead of
refusing/hallucinating.
"""
import json
import urllib.request

OLLAMA = "http://ollama:11434/api/generate"
CSV = open("/app/input/formacao-docentes.csv", encoding="utf-8").read()[:3000]
DESC = (
    'O gráfico é intitulado "Formação dos Docentes (Permanentes e Colaboradores)" e parece ser '
    "uma representação de um boxplot que mostra as distribuições de datas de formação para docentes "
    "em diferentes instituições. Título: Formação dos Docentes (Permanentes e Colaboradores). "
    "Tipo: Boxplot. Eixos: X = Ano (rótulos de 1990 a 2020); Y = Formação dos Docentes. "
    "Legenda: cores diferentes por instituição. Mensagem principal: há dispersão ampla das datas de "
    "formação e a mediana se desloca ao longo dos anos."
)

PROMPT = (
    "Você é um analista de visualizações de dados.\n\n"
    "INSUMOS JÁ CARREGADOS NESTA MENSAGEM (não é necessário acessar nada externo):\n\n"
    "### DADOS TABULARES\n" + CSV + "\n\n"
    "### LEVANTAMENTO VISUAL DO GRÁFICO\n" + DESC + "\n\n"
    "Cumpra a tarefa: analise a visualização e os dados e responda APENAS com um JSON puro "
    "no formato {\"analise_tecnica\": {\"titulo_original\": ..., \"tipo_visualizacao\": ..., "
    "\"eixos\": {...}, \"analise_dados\": {\"tendencia_principal\": ..., \"descricao_comportamento\": ...}, "
    "\"metadados_csv\": {\"colunas_identificadas\": [...], \"quantidade_registros\": ...}}}.\n"
    "Responda com a análise REAL. Nunca recuse a tarefa, nunca diga que não pode acessar dados e "
    "nunca produza exemplos hipotéticos."
)


def call(model):
    payload = json.dumps({
        "model": model, "prompt": PROMPT, "stream": False,
        "options": {"num_ctx": 16384, "temperature": 0.4},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1200) as r:
        d = json.loads(r.read())
    return d.get("response", "")


for model in ("phi4-mini:3.8b", "qwen2.5:3b"):
    try:
        resp = call(model)
        refused = any(k in resp.lower() for k in ("não posso", "nao posso", "hipotétic", "hipotetic", "desculpe"))
        print(f"=== {model} | len={len(resp)} | recusa/hipotético={refused} ===")
        print(resp[:400].replace("\n", " "))
    except Exception as e:
        print(f"=== {model} ERRO: {type(e).__name__}: {str(e)[:150]}")
    print()
