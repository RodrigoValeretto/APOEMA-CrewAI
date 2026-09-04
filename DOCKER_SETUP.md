# Docker Setup Guide - APOEMA-CrewAI

Este guia descreve como usar o Docker Compose para executar a aplicação APOEMA-CrewAI com PostgreSQL, pgvector, RabbitMQ e Flyway.

## Arquitetura

```
┌─────────────────────────────────────────────────┐
│         Docker Compose Services                 │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐  ┌──────────────┐            │
│  │   PostgreSQL │  │  RabbitMQ    │            │
│  │  + pgvector  │  │  (Management)│            │
│  │              │  │              │            │
│  │  Port: 5432  │  │  5672 / 15672│            │
│  └──────────────┘  └──────────────┘            │
│         │                │                      │
│         └────┬───────────┘                      │
│              │                                  │
│       ┌──────▼──────────┐  ┌─────────────┐     │
│       │    Flyway       │  │ Dramatiq    │     │
│       │  (Migrations)   │  │  Worker     │     │
│       └─────────────────┘  └─────────────┘     │
│                                                 │
│       ┌──────────────────────────────────┐     │
│       │      Main Application (app)      │     │
│       │                                  │     │
│       │  - CrewAI Agents & Tasks         │     │
│       │  - Database Integration          │     │
│       │  - Dramatiq Task Submission      │     │
│       │                                  │     │
│       │  Port: 8000                      │     │
│       └──────────────────────────────────┘     │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Serviços atuais:** `postgres`, `rabbitmq`, `ollama`, `flyway`, `app` (FastAPI :8000),
`dramatiq_worker` (fila `default` — análises) e **`converter_worker`** (fila
`conversion` — conversão de documentos PDF/XLSX→JSON via docling; 1 processo,
volumes `./:/app` + `hf_cache` para os modelos HuggingFace do docling).

> **Notas de build (Dockerfile):**
> - `dramatiq` é **pinado `<2`** (`>=1.15.0,<2.0.0`): a linha 2.x quebra a CLI
>   (exige positional `broker`) e a API de filas.
> - `torch` é instalado **CPU-only** (`--index-url .../whl/cpu`) antes do `pip
>   install -e ".[converter]"` — o wheel padrão do PyPI puxa pacotes `nvidia-*`
>   CUDA (vários GB, estouram o disco do build).
> - docling no `python:slim` precisa de libs apt (`libgl1`, `libglib2.0-0`,
>   `libxcb*`, `libxkbcommon0`) — sem elas a conversão falha com
>   `libxcb.so.1: cannot open shared object file`.
> - Extra opcional `[converter]` = `docling` + `openpyxl` (a importação do docling
>   é lazy: só o `converter_worker` carrega torch).

## Pré-requisitos

- Docker e Docker Compose instalados
- Arquivo `.env` configurado (baseado em `.env.example`)
- API Keys configuradas (GEMINI_API_KEY, OPENAI_API_KEY)

## Configuração Inicial

### 1. Criar arquivo `.env`

```bash
cp .env.example .env
```

Edite o arquivo `.env` e configure:
- `GEMINI_API_KEY` - Sua chave de API do Google Gemini
- `OPENAI_API_KEY` - Sua chave de API do OpenAI (opcional)
- Outras variáveis conforme necessário

### 2. Criar diretório de migrations

O diretório de migrations já foi criado em `migrations/sql/` com a migração inicial:

```
migrations/
└── sql/
    └── V1__initial_schema.sql
```

### 3. Buildando imagens (opcional)

```bash
docker-compose build
```

## Executando a Aplicação

### Iniciar todos os serviços

```bash
docker-compose up -d
```

### Ver logs

```bash
# Todos os serviços
docker-compose logs -f

# Serviço específico
docker-compose logs -f postgres
docker-compose logs -f rabbitmq
docker-compose logs -f dramatiq_worker
docker-compose logs -f app
```

### Parar os serviços

```bash
docker-compose down
```

### Remover volumes (CUIDADO - deleta dados)

```bash
docker-compose down -v
```

## Verificando a Saúde dos Serviços

### PostgreSQL

```bash
# Conectar ao PostgreSQL
docker exec -it apoema-postgres psql -U apoema -d apoema_db

# Listar tabelas
\dt

# Sair
\q
```

### RabbitMQ Management Console

Acesse: http://localhost:15672

- Username: `guest`
- Password: `guest`

### Verificar Migrations

```bash
docker-compose logs flyway
```

## Usando Dramatiq para Tarefas Assíncronas

### Definindo uma task

Crie um arquivo `tasks.py`:

```python
import dramatiq
from dramatiq.brokers.rabbitmq import RabbitMQBroker

broker = RabbitMQBroker(url="amqp://guest:guest@rabbitmq:5672//")
dramatiq.set_broker(broker)

@dramatiq.actor
def analyze_assessment(assessment_data):
    """Task para análise de avaliação"""
    # Sua lógica aqui
    return {"status": "completed"}
```

### Enviando uma task

```python
from tasks import analyze_assessment

# Enviar task para fila
analyze_assessment.send({"assessment": "data"})
```

### Monitorar tasks

```bash
docker-compose logs -f dramatiq_worker
```

## Conectando à Aplicação

### Terminal/CLI

```bash
docker exec -it apoema-app python main.py --assessment-file input/cc_assessment_data.json
```

### Dentro do container app

```bash
docker exec -it apoema-app bash
python main.py --help
```

## Estrutura de Banco de Dados

### Tabela `analysis`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | SERIAL | ID único da análise |
| type | VARCHAR(100) | Tipo de análise (ex: 'report_analysis') |
| status | VARCHAR(50) | Status (pending, processing, completed, failed) |
| created_at | TIMESTAMP | Data de criação |
| updated_at | TIMESTAMP | Data de última atualização |

### Tabela `analysis_results`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | SERIAL | ID único do resultado |
| analysis_id | INTEGER | Referência para a análise |
| task_name | VARCHAR(255) | Nome da task que produziu o resultado |
| result | TEXT | Resultado da análise |
| created_at | TIMESTAMP | Data de criação |

## Adicionando Novas Migrations

Crie um novo arquivo SQL em `migrations/sql/`:

```bash
# Exemplo: criar nova tabela
touch migrations/sql/V2__add_new_table.sql
```

Nomeação: `V{version}__{description}.sql`

- `V1__initial_schema.sql`
- `V2__add_new_table.sql`
- `V3__add_indexes.sql`

A próxima vez que o Flyway rodar, aplicará as novas migrations automaticamente.

## Troubleshooting

### Flyway não consegue conectar ao PostgreSQL

```bash
# Verificar se PostgreSQL está saudável
docker-compose ps

# Ver logs do Flyway
docker-compose logs flyway

# Aguardar PostgreSQL ficar pronto
docker-compose down
docker-compose up postgres
# Aguarde alguns segundos...
docker-compose up -d
```

### RabbitMQ não está respondendo

```bash
# Verificar status do RabbitMQ
docker-compose logs rabbitmq

# Reiniciar RabbitMQ
docker-compose restart rabbitmq
```

### Dramatiq worker não consegue conectar

Certifique-se de que:
- RabbitMQ está saudável: `docker-compose ps`
- `RABBITMQ_URL` está corretamente configurada no `.env`
- O container dramatiq_worker consegue resolver o hostname `rabbitmq`

### Permissões de arquivo no Linux

Se você tiver problemas de permissão, execute:

```bash
sudo chown -R $USER:$USER .
```

## Parar e Limpar

```bash
# Parar serviços mantendo volumes
docker-compose down

# Parar e remover volumes (cuidado!)
docker-compose down -v

# Remover imagens também
docker-compose down -v --rmi all
```

## Variáveis de Ambiente Disponíveis

Veja `.env.example` para lista completa de variáveis configuráveis:

- Database: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- RabbitMQ: `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`
- LLM APIs: `GEMINI_API_KEY`, `OPENAI_API_KEY`
- Aplicação: `APP_PORT`, `PYTHONUNBUFFERED`

## Recursos

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [PostgreSQL pgvector](https://github.com/pgvector/pgvector)
- [Flyway Documentation](https://flywaydb.org/)
- [Dramatiq Documentation](https://dramatiq.io/)
- [RabbitMQ Documentation](https://www.rabbitmq.com/documentation.html)