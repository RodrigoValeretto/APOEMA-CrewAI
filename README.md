# 🎓 APOEMA - Sistema de Análise de Avaliação CAPES com Multi-Agentes IA

**APOEMA** (Autonomous Program Observation for Educational Metrics Analysis) é um sistema inteligente baseado em agentes IA que analisa fichas de avaliação CAPES e relatórios de programas de pós-graduação brasileiros, extraindo critérios de avaliação, estruturando dados e validando conformidade com padrões regulatórios.

## 📋 O que é o APOEMA?

APOEMA é um framework multi-agente que utiliza inteligência artificial (LLM) para:

1. **📖 Ler e interpretar** fichas de avaliação da CAPES (em formato JSON transcrito)
2. **🗂️ Estruturar dados** de forma hierárquica (Quesitos → Itens → Indicadores)
3. **📊 Analisar relatórios** contendo visualizações de dados (gráficos, tabelas, plots)
4. **✅ Validar conformidade** de visualizações com critérios de avaliação
5. **📈 Gerar relatórios** estruturados com insights e recomendações

## 🎯 Problema que Resolve

Programas de pós-graduação brasileiros precisam se alinhar com critérios complexos da CAPES para obter boas avaliações. Esses critérios são frequentemente:
- ❌ Documentados em formatos textuais complexos
- ❌ Com hierarquias intricadas e inter-dependências
- ❌ Difíceis de cruzar com dados do programa

**APOEMA resolve isso automatizando** a leitura de critérios, estruturação de dados e validação de alinhamento.

## 🏗️ Arquitetura do Sistema

### 5 Agentes IA Especializados

**Agentes Base (todos os fluxos):**
- **Data Reader**: Extrai e estrutura critérios CAPES
- **Summarizer**: Sumariza os critérios em formato legível

**Agentes para Análise de Relatórios PDF:**
- **Report Analyzer**: Analisa múltiplos gráficos de relatórios PDF

**Agentes para Análise PNG+CSV (Novo):**
- **Plot Data Analyst**: Análise técnica integrada de PNG + CSV → JSON estruturado
- **Plot Insights Generator**: Transforma análise técnica em insights estratégicos

**Agente Compartilhado:**
- **Utility Assessor**: Avalia importância/relevância para a área (em ambos os fluxos)

### Fluxos de Processamento

#### Fluxo 1: Análise de Critérios CAPES (Obrigatório)
```
Entrada: assessment_data.json
  ↓
[TASK 1] Data Reader: Analisa estrutura de critérios
  ↓ Output: JSON com quesitos/pesos/indicadores
[TASK 2] Summarizer: Sumariza critérios em markdown
  ↓ Output: {prefix}_output.md
```

#### Fluxo 2A: Análise de Relatório PDF (Opcional)
```
Entrada: PDF do Relatório
  ↓
[TASK 3] Report Analyzer: Extrai visualizações
[TASK 4] Report Analyzer: Analisa gráficos
[TASK 5] Report Analyzer: Mapeia critérios CAPES
[TASK 6] Utility Assessor: Avalia utilidade dos gráficos
  ↓ Outputs: conformance_report_*.md, utility_assessment_*.md
```

#### Fluxo 2B: Análise PNG+CSV (Novo - Alternativa ao PDF)
```
Entrada: PNG plot + CSV data
  ↓
[TASK 7] Plot Data Analyst: Análise técnica integrada
  ↓ Output: JSON estruturado com métricas técnicas
[TASK 8] Plot Insights Generator: Gera insights e narrativa
  ↓ Output: {prefix}_plot_insights.md
[TASK 9] Utility Assessor: Avalia importância para a área
  ↓ Output: {prefix}_plot_importance.md
```

#### Fluxo 3: Conversão de Fichas CAPES (PDF/XLSX → JSON) via Informativo
As fichas de avaliação da CAPES (PDF) e anexos/adendos (XLSX) são convertidos para um
JSON enriquecido em background e agrupados por **informativo** (corpus da área, ex.
"Ciência da Computação"). Uma análise pode ser disparada direto pelo `informativo_id`:
a ficha convertida vira o `assessment_file` e anexos/adendos entram como fontes de
Knowledge (retrieval automático) — ver seção de endpoints abaixo.
```
Upload PDF/XLSX → POST /api/informativos/{id}/documentos (kind=ficha|anexo|adendo)
  ↓ fila dedicada 'conversion' (converter_worker, docling)
JSON enriquecido (uploads/converted/doc_{id}.json) registrado em analysis_files
  ↓
POST /api/analysis {"informativo_id": N} → ficha = assessment + anexos = Knowledge
```

## 🚀 Como Usar

### Pré-requisitos

```bash
# Python 3.10+ (recomendado 3.13+)
python --version

# Instalar uv (gerenciador de dependências rápido)
pip install uv
# ou: curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 1️⃣ Instalação

**Clonar o repositório:**
```bash
git clone <repository-url>
cd crewai-test
```

**Instalar dependências com uv:**
```bash
# uv cria automaticamente o ambiente virtual .venv e instala tudo
make install
```

**Ou (alternativo com pip - mais lento):**
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate      # Windows

pip install -r requirements.txt
```

### 2️⃣ Configurar API Keys

**Obter chave da API Google Gemini:**
1. Ir para [Google AI Studio](https://aistudio.google.com/apikey)
2. Criar um projeto ou usar um existente
3. Gerar uma chave de API gratuita
4. Exportar a chave:

```bash
# Linux/Mac
export GEMINI_API_KEY="sua-chave-aqui"

# Windows (PowerShell)
$env:GEMINI_API_KEY="sua-chave-aqui"

# Windows (CMD)
set GEMINI_API_KEY=sua-chave-aqui
```

### 3️⃣ Executar o Sistema

#### Opção A: Análise de Critérios CAPES Apenas

Analisa a ficha de avaliação para uma grande área de estudo CAPES e extrai insights sobre os critérios (Tarefas 1-2):

```bash
# Usando Makefile (recomendado)
make run assessment-file=cc_assessment_data.json

# Ou com uv diretamente
uv run python main.py --assessment-file cc_assessment_data.json

# Ou com o ambiente virtual ativado
source .venv/bin/activate  # Linux/Mac
python main.py --assessment-file cc_assessment_data.json
```

**Saída esperada:**
```
Analisando cc_assessment_data.json...
✓ Data Reader processando critérios CAPES...
✓ Summarizer sumarizando dados...
Execução concluída!
```

**Arquivo gerado:**
- `output/output_YYYYMMDDHHMMSS.md` - Análise estruturada dos critérios de avaliação

#### Opção B: Análise Completa com Relatório PDF do APOEMA

Realiza análise de critérios + validação dos gráficos do relatório contra os padrões de avaliação (Tarefas 1-6):

```bash
# Usando Makefile (recomendado)
make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf

# Ou com uv diretamente
uv run python main.py --assessment-file cc_assessment_data.json --pdf-file cc_report.pdf

# Ou com o ambiente virtual ativado
source .venv/bin/activate  # Linux/Mac
python main.py --assessment-file cc_assessment_data.json --pdf-file cc_report.pdf
```

#### Opção C: Análise de Gráfico PNG com Dados CSV (Novo!)

Realiza análise de critérios + análise técnica de um gráfico PNG com dados CSV correspondentes (Tarefas 1-2, 7-9):

```bash
# Usando Makefile (recomendado)
make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv

# Ou com uv diretamente
uv run python main.py --assessment-file cc_assessment_data.json --png-file plot.png --csv-file data.csv

# Ou com o ambiente virtual ativado
source .venv/bin/activate  # Linux/Mac
python main.py --assessment-file cc_assessment_data.json --png-file plot.png --csv-file data.csv
```

**Exemplos práticos:**
```bash
# Análise de critérios para Computação
make run assessment-file=cc_assessment_data.json

# Análise com arquivo customizado
make run assessment-file=./data/custom_assessment.json

# Validação com relatório PDF do APOEMA
make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf

# Análise de gráfico PNG com dados CSV
make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv

# Com prefixo customizado
make run assessment-file=cc_assessment_data.json prefix=computacao_2025

# Análise completa PDF com todos os parâmetros
make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf prefix=analise_computacao

# Análise completa PNG+CSV com todos os parâmetros
make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv prefix=analise_plot
```

**Saída esperada:**
```
✓ Arquivo PDF carregado: cc_report.pdf
✓ Tarefas de análise de relatório adicionadas ao pipeline
Analisando cc_assessment_data.json...
✓ Data Reader processando critérios CAPES...
✓ Summarizer sumarizando dados...
✓ Report Analyzer extraindo visualizações...
✓ Report Analyzer analisando gráficos...
✓ Report Analyzer mapeando para critérios...
Execução concluída!
```

**Arquivos gerados:**
- `output/output_YYYYMMDDHHMMSS.md` - Análise dos critérios
- `output/conformance_report_YYYYMMDDHHMMSS.md` - Relatório de conformidade com validações dos gráficos

## 📁 Estrutura do Projeto

```
crewai-test/
│
├── 📄 README.md                    # Este arquivo
├── 📄 QUICKSTART.md                # Guia rápido de início
├── 📄 REPORT_ANALYZER_GUIDE.md     # Guia detalhado do Report Analyzer
├── 📄 pyproject.toml               # Configuração do projeto (PEP 621)
├── 📄 uv.lock                      # Lockfile de dependências
├── 📄 main.py                      # Script principal
├── 📄 prompt_loader.py             # Carregador de prompts
├── 📄 assessment_data.json         # Dados de avaliação CAPES (entrada)
│
├── 📁 prompts/                          # Templates de prompts para agentes
│   ├── agents/
│   │   ├── data_reader.yaml               # Config do agente extrator de dados
│   │   ├── summarizer.yaml                # Config do agente sumarizador
│   │   ├── report_analyzer.yaml           # Config do agente analisador de relatórios
│   │   ├── plot_data_analyst.yaml         # Config do agente analisador PNG+CSV
│   │   ├── plot_insights_generator.yaml   # Config do agente gerador de insights
│   │   └── utility_assessor.yaml          # Config do agente avaliador de utilidade
│   │
│   └── tasks/
│       ├── task1_analyze.yaml             # Tarefa: Analisar critérios CAPES
│       ├── task2_summarize.yaml           # Tarefa: Sumarizar critérios
│       ├── task3_extract_plots.yaml       # Tarefa: Extrair visualizações
│       ├── task4_analyze_plots.yaml       # Tarefa: Analisar gráficos
│       ├── task5_criteria_mapping.yaml    # Tarefa: Mapear critérios
│       ├── task6_utility_assessment.yaml  # Tarefa: Avaliar utilidade
│       ├── task7_plot_data_analysis.yaml  # Tarefa: Analisar PNG+CSV
│       ├── task8_plot_insights.yaml       # Tarefa: Gerar insights
│       └── task9_plot_utility_importance.yaml # Tarefa: Importância do plot
│
├── 📁 output/                      # Resultados gerados
│   └── output_*.md                 # Relatórios em Markdown
│
├── 📁 .venv/                       # Ambiente virtual (gitignored)
└── 📄 .gitignore                   # Arquivos ignorados pelo git
```

## 🔧 Tarefas Disponíveis

### Task 1: Análise de Critérios CAPES
**Agente:** Data Reader  
**O que faz:** Lê a ficha de avaliação CAPES e estrutura todos os critérios, pesos e indicadores  
**Entrada:** `assessment_data.json`  
**Saída:** JSON estruturado com quesitos/itens/indicadores

### Task 2: Sumarização
**Agente:** Summarizer  
**O que faz:** Sumariza os critérios em formato legível para stakeholders  
**Entrada:** Resultados da Task 1  
**Saída:** `output_*.md` (Markdown)

### Task 3: Extração de Visualizações (Opcional)
**Agente:** Report Analyzer  
**O que faz:** Cataloga todas as visualizações presentes no PDF  
**Entrada:** PDF do relatório  
**Saída:** JSON com metadados dos gráficos (títulos, eixos, dados)

### Task 4: Análise de Gráficos (Opcional)
**Agente:** Report Analyzer  
**O que faz:** Analisa dados de cada gráfico e extrai insights  
**Entrada:** Catálogo de visualizações (Task 3)  
**Saída:** JSON com análises detalhadas, tendências, outliers

### Task 5: Mapeamento para Critérios CAPES (Opcional)
**Agente:** Report Analyzer  
**O que faz:** Valida alinhamento dos gráficos com critérios CAPES  
**Entrada:** Análises (Task 4) + Critérios (Task 1)  
**Saída:** `conformance_report_*.md` com matriz de conformidade

### Task 6: Avaliação de Utilidade dos Gráficos (Opcional)
**Agente:** Utility Assessor  
**O que faz:** Avalia a utilidade e relevância de cada gráfico para a área específica  
**Entrada:** Análises (Task 4) + Critérios (Task 1) + Contexto (Task 5)  
**Saída:** `utility_assessment_*.md` com scores de assertividade

### Task 7: Análise Técnica de Gráfico PNG+CSV (Novo - Opcional)
**Agente:** Plot Data Analyst  
**O que faz:** Análise integrada de imagem PNG + dados CSV (tipo de gráfico, métricas estatísticas, tendências, outliers, qualidade de dados)  
**Entrada:** PNG plot + CSV data + assessment_data.json  
**Saída:** JSON estruturado com análise técnica completa

### Task 8: Geração de Insights PNG+CSV (Novo - Opcional)
**Agente:** Plot Insights Generator  
**O que faz:** Transforma análise técnica em insights estratégicos e narrativa em Markdown  
**Entrada:** JSON da Task 7 + assessment_data.json  
**Saída:** `plot_insights_*.md` com insights, tendências, oportunidades e recomendações

### Task 9: Avaliação de Importância do Gráfico (Novo - Opcional)
**Agente:** Utility Assessor  
**O que faz:** Avalia a importância e relevância do gráfico PNG para a área de avaliação  
**Entrada:** Insights (Task 8) + assessment_data.json  
**Saída:** `plot_importance_*.md` com score de importância e classificação

## 📊 Exemplo de Saída

### Sumário de Critérios (Task 2)
```markdown
# Análise de Critérios CAPES - Área 27

## Quesito 1: Programa (60%)
### Indicador 1.1: Identidade e Funcionamento
- Peso: 60%
- Tipo: Qualitativo
- Descritores: Corpo docente, infraestrutura, linhas de pesquisa

## Quesito 2: Corpo Docente (20%)
### Indicador 2.1: Titulação e Produção
- Peso: 20%
...
```

### Relatório de Conformidade (Task 5)
```json
{
  "matriz_conformidade": {
    "criterios_cobertos": 8,
    "criterios_total": 15,
    "taxa_cobertura_percentual": 53,
    "score_conformidade_geral": 72
  },
  "principais_forcas": [
    "Gráficos de produção bibliográfica bem estruturados",
    "Dados de corpo docente completos"
  ],
  "principais_lacunas": [
    "Falta visualização de impacto social",
    "Dados de formação de recursos humanos incompletos"
  ]
}
```

## 🛠️ Requisitos Técnicos

### Dependências Python

```
crewai>=0.1.0              # Framework multi-agente
crewai_files>=1.0.0        # Processamento de files
google-generativeai>=0.3.0 # API Google Gemini
docling>=1.0.0             # Extração de PDFs (opcional)
pydantic>=2.0              # Validação de dados
```

### Recursos Recomendados

- **RAM:** Mínimo 4GB (8GB recomendado)
- **Storage:** 2GB para ambiente virtual + dados
- **Internet:** Conexão estável (API calls)
- **Python:** 3.10+ (testado em 3.11, 3.13)

## ⚙️ Configuração Avançada

### Alterar Modelo LLM

Para usar um modelo diferente (ex: GPT-4), edite `main.py`:

```python
agent_llm = LLM(
    model="gpt-4",  # ou outro modelo
    api_key=openai_api_key,
    temperature=0.7,
)
```

### Aumentar Verbosidade

Para debug detalhado:

```python
agent = Agent(
    ...,
    verbose=True,  # Já está ativado por padrão
)
```

### Customizar Prompts

Edite os arquivos em `prompts/`:
- `prompts/agents/*.md` - Modifique role, goal, backstory
- `prompts/tasks/*.md` - Modifique descrição e expected output

## 🐛 Troubleshooting

### ❌ Erro: "GEMINI_API_KEY not found"
**Solução:**
```bash
# Verificar se variável foi exportada
echo $GEMINI_API_KEY  # Linux/Mac
echo %GEMINI_API_KEY%  # Windows

# Se vazio, exporte novamente
export GEMINI_API_KEY="sua-chave"
```

### ❌ Erro: "assessment_data.json not found"
**Solução:** Verifique se arquivo está no diretório raiz:
```bash
ls -la assessment_data.json  # Linux/Mac
dir assessment_data.json      # Windows
```

### ❌ Erro: "Module 'crewai' not found"
**Solução:** Instale dependências:
```bash
pip install -r requirements.txt
# ou
pip install crewai crewai_files google-generativeai
```

### ❌ Arquivo PDF não é processado
**Solução:** Verifique se:
1. Caminho do arquivo está correto
2. Arquivo tem permissões de leitura
3. É um PDF válido (não corrompido)

```bash
# Testar acesso ao arquivo
file relatorio.pdf  # Deve retornar "PDF document"
```

### ⚠️ Execução lenta
**Causas possíveis:**
- Conexão de internet instável
- PDF muito grande (>50MB)
- LLM respondendo lentamente

**Soluções:**
- Verifique conectividade
- Divida PDF em partes menores
- Aguarde resposta da API

## 📖 Documentação Adicional

- **[REPORT_ANALYZER_GUIDE.md](./REPORT_ANALYZER_GUIDE.md)** - Guia detalhado do agente Report Analyzer
- **[CAPES Criteria](https://www.gov.br/capes/)** - Critérios oficiais CAPES
- **[CrewAI Docs](https://docs.crewai.com)** - Framework multi-agente
- **[Google Gemini API](https://ai.google.dev/)** - Documentação da API

## 🎓 Casos de Uso

### 1. Verificação de Conformidade de PPG
```bash
python main.py relatorio_programa_computacao.pdf
```
Gera relatório mostrando quais critérios CAPES estão cobertos pelas visualizações.

### 2. Análise de Lacunas
```bash
python main.py
# Analisa critérios CAPES e identifica quais dados deveriam estar presentes
```

### 3. Validação de Relatórios Internos
```bash
python main.py relatorio_semestral.pdf
```
Valida se o relatório do programa atende aos padrões CAPES.

## 💡 Dicas de Uso

1. **assessment_data.json é obrigatório** - Define a grande área de estudo CAPES e seus critérios de avaliação
2. **PDF é opcional** - Use para validar se o relatório de um programa atende aos padrões de avaliação
3. **Prefix é opcional** - Padrão é timestamp; use para organizar múltiplas análises
4. **Revise os prompts** - Customize para sua área de conhecimento específica
5. **Preserve histórico** - Não delete arquivos em `output/` (versionamento)
6. **Teste incrementalmente** - Execute análise de critérios antes de adicionar PDFs

## 📈 Melhorias Realizadas

- [x] **Análise PNG+CSV:** Suporte a análise de gráficos PNG com dados CSV (Tasks 7-9)
- [x] **Dois agentes especializados:** Plot Data Analyst e Plot Insights Generator
- [x] **Workflow alternativo:** PNG+CSV como alternativa ao PDF

## 🔄 Próximas Melhorias

- [ ] Dashboard web interativo
- [ ] Comparação entre programas
- [ ] Histórico de conformidade ao longo do tempo
- [ ] Exportação para múltiplos formatos (PDF, Excel)
- [ ] Suporte a múltiplos gráficos PNG em lote
- [ ] Análise de gráficos interativos (HTML5)

## 📝 Licença

Este projeto está sob licença [MIT/Apache 2.0 - especificar].

## 👥 Contribuições

Contribuições são bem-vindas! Por favor:
1. Faça fork do projeto
2. Crie uma branch para sua feature (`git checkout -b feature/MinhaFeature`)
3. Commit suas mudanças (`git commit -m 'Adiciona MinhaFeature'`)
4. Push para a branch (`git push origin feature/MinhaFeature`)
5. Abra um Pull Request

## 📧 Contato & Suporte

- **Issues:** [GitHub Issues](link-do-projeto)
- **Discussões:** [GitHub Discussions](link-do-projeto)
- **Email:** [seu-email]

## 🙏 Agradecimentos

- CAPES - Por fornecer critérios de avaliação estruturados
- CrewAI - Framework multi-agente
- Google Gemini - Modelo de linguagem
- Comunidade Python Brasil

---

**Versão:** 1.0  
**Última Atualização:** 2025-03-02  
**Status:** ✅ Em Produção  
**Mantido por:** APOEMA Team
