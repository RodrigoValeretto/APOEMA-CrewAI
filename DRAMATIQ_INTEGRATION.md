# Dramatiq Integration Guide

Este guia descreve como integrar Dramatiq com o APOEMA para executar análises de forma assíncrona.

## Visão Geral da Arquitetura

```
┌─────────────────┐
│  Client / App   │
│                 │
│  task.send()    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   RabbitMQ      │  Message Queue
│    Broker       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Dramatiq Worker │  Processa tasks
│                 │  Executa CrewAI
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  PostgreSQL     │  Armazena resultados
│   Database      │
└─────────────────┘
```

### Duas filas e dois workers

| Worker | Comando (compose) | Fila | Responsabilidade |
|---|---|---|---|
| `dramatiq_worker` (10 processos) | `dramatiq --verbose tasks` | `default` | Enfileiramento FIFO + execução do CrewAI (análises) |
| `converter_worker` (1 processo) | `dramatiq conversion_tasks -Q conversion --processes 1 --verbose` | `conversion` | Conversão docling de documentos de informativo (PDF/XLSX → JSON) |

- O broker (RabbitMQ) é configurado uma única vez em **`dramatiq_broker.py`**
  (`set_broker`), importado por `tasks.py` e `conversion_tasks.py` antes dos
  decorators `@dramatiq.actor` (exigência do Dramatiq).
- No CLI do Dramatiq **1.18 o módulo é o positional `broker`** (o módulo precisa
  expor um atributo `broker`) e `-Q` tem `nargs='*'` — por isso o comando do
  `converter_worker` põe o **módulo ANTES das opções** (`conversion_tasks -Q conversion`),
  senão o `-Q` "engole" o nome do módulo e o worker nem sobe.
- A conversão nunca bloqueia a fila FIFO de análises: são filas independentes, e o
  docling/torch só é carregado no processo que executa a conversão (import lazy em
  `conversion/engine.py`).

## Fluxo de Análise

### 1. Submissão da Task

```python
from tasks import run_analysis_flow

# Enviar análise para fila
result = run_analysis_flow.send(
    assessment_file="input/cc_assessment_data.json",
    pdf_file="input/cc_report.pdf",
    output_prefix="my_analysis",
    model="gemini"
)

print(f"Task ID: {result.message_id}")
```

### 2. Criação do Analysis Record

A task automaticamente cria um registro em `analysis`:

```sql
INSERT INTO analysis (type, status, created_at, updated_at)
VALUES ('pdf', 'processing', now(), now())
RETURNING id;
```

### 3. Execução do CrewAI

Durante a execução:
- A task executa o `run_apoema_flow()` ou `run_apoema_pipeline()`
- O analysis_id é passado via `os.environ["ANALYSIS_ID"]`
- Cada tarefa do CrewAI pode salvar resultados

### 4. Salvamento de Resultados

Conforme tarefas completam, use `save_analysis_result()`:

```python
from tasks import save_analysis_result
import os

# Dentro de uma callback ou hook do CrewAI
analysis_id = int(os.environ.get("ANALYSIS_ID"))

save_analysis_result(
    analysis_id=analysis_id,
    task_name="data_reader_task",
    result="Critérios CAPES extraídos com sucesso..."
)
```

### 5. Atualização de Status

Ao final, a task atualiza o status:

```sql
UPDATE analysis
SET status = 'completed', updated_at = now()
WHERE id = 123;
```

## Integrando com CrewAI

### Opção 1: Usando Callbacks

Se o CrewAI suporta callbacks:

```python
from crewai.flow.flow import Flow
from tasks import save_analysis_result
import os

class ApoemaFlow(Flow):
    def on_task_complete(self, task_result, **kwargs):
        """Callback chamado quando uma task completa"""
        analysis_id = int(os.environ.get("ANALYSIS_ID"))
        save_analysis_result(
            analysis_id,
            task_result.task.name,
            task_result.output
        )
```

### Opção 2: Wrapper ao redor do Flow

```python
def run_apoema_flow_with_tracking(assessment_file, **kwargs):
    analysis_id = int(os.environ.get("ANALYSIS_ID"))

    # Antes de cada etapa
    save_analysis_result(analysis_id, "flow_start", "Flow iniciado")

    # Executar flow
    result = run_apoema_flow(assessment_file, **kwargs)

    # Após conclusão
    save_analysis_result(analysis_id, "flow_complete", str(result))

    return result
```

### Opção 3: Instrumentação do Flow

Modifique `apoema_flow.py` para salvar resultados:

```python
import os
from tasks import save_analysis_result

class ApoemaFlow(Flow):
    @listen("data_reader_complete")
    def on_data_reader_complete(self, data):
        analysis_id = os.environ.get("ANALYSIS_ID")
        if analysis_id:
            save_analysis_result(
                int(analysis_id),
                "data_reader",
                str(data)
            )
```

## Usando as Tasks

### Via linha de comando (CLI)

```bash
# Terminal 1: Iniciar worker
docker-compose exec dramatiq_worker \
    dramatiq tasks

# Terminal 2: Submeter task
python -c "
from tasks import run_analysis_flow
result = run_analysis_flow.send(
    assessment_file='input/cc_assessment_data.json',
    model='gemini'
)
print(f'Task ID: {result.message_id}')
"
```

### Via Python Code

```python
from tasks import run_analysis_flow, run_analysis_crew
import time

# Opção 1: Flow (assíncrono)
result = run_analysis_flow.send(
    assessment_file="input/cc_assessment_data.json",
    pdf_file="input/cc_report.pdf",
    model="gemini"
)
task_id = result.message_id
print(f"Flow task enviada: {task_id}")

# Opção 2: Crew (assíncrono)
result = run_analysis_crew.send(
    assessment_file="input/adm_data.json",
    model="gemini"
)
task_id = result.message_id
print(f"Crew task enviada: {task_id}")
```

### Via API (exemplo com FastAPI)

```python
from fastapi import FastAPI
from tasks import run_analysis_flow

app = FastAPI()

@app.post("/api/analysis")
async def create_analysis(assessment_file: str, model: str = "gemini"):
    """Submeter nova análise"""
    result = run_analysis_flow.send(
        assessment_file=assessment_file,
        model=model
    )
    return {
        "task_id": result.message_id,
        "status": "queued"
    }

@app.get("/api/analysis/{analysis_id}")
async def get_analysis(analysis_id: int):
    """Obter resultado da análise"""
    # Implementar query ao banco
    pass
```

## Monitorando Tasks

### Ver status no banco de dados

```bash
# Conectar ao PostgreSQL
docker exec -it apoema-postgres psql -U apoema -d apoema_db

# Listar todas as análises
SELECT id, type, status, created_at FROM analysis ORDER BY created_at DESC;

# Ver resultados de uma análise específica
SELECT task_name, result, created_at FROM analysis_results
WHERE analysis_id = 1
ORDER BY created_at;

# Ver análises pendentes
SELECT * FROM analysis WHERE status = 'processing';
```

### Ver logs do worker

```bash
# Follow logs do Dramatiq worker
docker-compose logs -f dramatiq_worker

# Buscar por erro
docker-compose logs dramatiq_worker | grep ERROR
```

### Verificar RabbitMQ Management

Acesse: http://localhost:15672

- Username: `guest`
- Password: `guest`

Monitore:
- Queues (filas de tarefas)
- Connections (conexões ativas)
- Channels (canais de mensagem)

## Tratamento de Erros

### Task falha

Se a task falha:

1. Status em `analysis` é atualizado para `failed`
2. Erro é salvo em `analysis_results` com task_name `"run_analysis_flow_error"`
3. Worker re-tenta conforme configurado (padrão: max_retries=0)

```python
@dramatiq.actor(store_results=True, max_retries=3)  # Retry até 3 vezes
def run_analysis_flow(...):
    ...
```

### Investigar erro

```bash
# Ver últimas análises com falha
docker exec -it apoema-postgres psql -U apoema -d apoema_db -c "
SELECT id, type, status, created_at FROM analysis
WHERE status = 'failed'
ORDER BY created_at DESC LIMIT 5;
"

# Ver mensagem de erro
SELECT result FROM analysis_results
WHERE task_name = 'run_analysis_flow_error'
ORDER BY created_at DESC LIMIT 1;
```

## Performance e Escalabilidade

### Múltiplos Workers

```bash
# Iniciar 3 workers
for i in {1..3}; do
    docker run --name apoema-worker-$i \
        --network apoema_network \
        -e RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672// \
        apoema-crewai \
        dramatiq tasks &
done
```

### Prioridade de Tasks

```python
@dramatiq.actor(priority=10)  # Prioridade alta (padrão é 0)
def run_priority_analysis(...):
    ...

# Submeter com prioridade
run_priority_analysis.send(...).options(priority=10)
```

### Dead Letter Queue (DLQ)

Tasks que falham permanentemente vão para a DLQ:

```python
# Ver DLQ no RabbitMQ Management
# Exchange: dramatiq-dead-letter
# Queue: apoema.dead-letter
```

## Exemplo Completo

```python
# app.py
from fastapi import FastAPI
from tasks import run_analysis_flow
from database import get_analysis_status
import os

app = FastAPI()

@app.post("/analyze")
def submit_analysis(
    assessment_file: str,
    pdf_file: str = None,
    model: str = "gemini"
):
    """Submeter análise assíncrona"""
    # Enviar para fila
    task_result = run_analysis_flow.send(
        assessment_file=assessment_file,
        pdf_file=pdf_file,
        model=model
    )

    return {
        "task_id": task_result.message_id,
        "status": "queued"
    }

@app.get("/analysis/{analysis_id}")
def get_analysis(analysis_id: int):
    """Obter resultado da análise"""
    analysis = get_analysis_status(analysis_id)

    return {
        "id": analysis_id,
        "status": analysis["status"],
        "type": analysis["type"],
        "created_at": analysis["created_at"],
        "results": get_analysis_results(analysis_id)
    }

# Executar
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Troubleshooting

### Worker não consome tarefas

```bash
# Verificar conexão RabbitMQ
docker-compose logs rabbitmq | grep error

# Reiniciar worker
docker-compose restart dramatiq_worker

# Verificar variáveis de ambiente
docker-compose exec dramatiq_worker env | grep RABBITMQ
```

### Task fica em "processing" eternamente

```bash
# Verificar se worker está rodando
docker-compose ps dramatiq_worker

# Ver logs de erro
docker-compose logs dramatiq_worker | tail -50

# Resetar fila (cuidado!)
docker-compose exec rabbitmq \
    rabbitmqctl purge_queue apoema
```

### Resultado não salvo no banco

Certifique-se de:
1. PostgreSQL está saudável
2. Tabela `analysis_results` existe
3. `analysis_id` é válido
4. Variáveis de ambiente `DB_*` estão configuradas

```bash
# Verificar conexão ao banco
docker-compose exec app psql -c "SELECT 1"
```

## Recursos

- [Dramatiq Documentation](https://dramatiq.io/)
- [RabbitMQ Tutorial](https://www.rabbitmq.com/getstarted.html)
- [CrewAI Documentation](https://docs.crewai.com/)
- [PostgreSQL Transactions](https://www.postgresql.org/docs/current/tutorial-transactions.html)