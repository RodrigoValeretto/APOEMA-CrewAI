# Testing the APOEMA API

Guia prático para testar a API FastAPI integrada com CrewAI, Dramatiq e PostgreSQL.

## 🚀 Quick Start

### 1. Setup Docker Compose

```bash
# Iniciar todos os serviços
docker-compose up -d

# Verificar se tudo está rodando
docker-compose ps

# Deve mostrar:
# apoema-postgres        ✓
# apoema-rabbitmq        ✓
# apoema-flyway          ✓ (completed successfully)
# apoema-dramatiq-worker ✓
# apoema-app             ✓
```

### 2. Iniciar API FastAPI

```bash
# Em um terminal separado
python run_api.py

# Output:
# INFO:     Uvicorn running on http://0.0.0.0:8000
# INFO:     Application startup complete
```

### 3. Verificar Health Check

```bash
curl http://localhost:8000/health

# Response:
# {
#   "status": "ok",
#   "timestamp": "2024-06-09T12:00:00.123456Z",
#   "services": {
#     "api": "ok",
#     "database": "ok"
#   }
# }
```

---

## 📝 Test Cases

### Test 1: Submeter Análise BÁSICA

```bash
curl -X POST http://localhost:8000/api/analysis \
  -H "Content-Type: application/json" \
  -d '{
    "assessment_file": "/app/input/cc_assessment_data.json",
    "model": "gemini"
  }'

# Response (201 Created):
# {
#   "id": 1,
#   "type": "basic",
#   "status": "pending",
#   "created_at": "2024-06-09T12:00:00Z"
# }

# Nota: analysis_id = 1 para próximos testes
```

### Test 2: Polling de Status (Durante Execução)

```bash
# Logo após submeter (T~1s)
curl http://localhost:8000/api/analysis/1

# Response:
# {
#   "id": 1,
#   "type": "basic",
#   "status": "pending",
#   "created_at": "2024-06-09T12:00:00Z",
#   "updated_at": "2024-06-09T12:00:00Z",
#   "results": [],
#   "progress": {
#     "total_tasks_expected": 2,
#     "completed_tasks": 0,
#     "percentage": 0.0
#   }
# }
```

### Test 3: Polling Após alguns segundos

```bash
# Esperar 10 segundos e repetir
curl http://localhost:8000/api/analysis/1

# Response (Task 1 completa):
# {
#   "id": 1,
#   ...
#   "status": "processing",
#   "results": [
#     {
#       "id": 1,
#       "task_name": "task_1_data_analysis",
#       "result": "Encontrados 5 critérios...",
#       "created_at": "2024-06-09T12:00:02Z"
#     }
#   ],
#   "progress": {
#     "total_tasks_expected": 2,
#     "completed_tasks": 1,
#     "percentage": 50.0
#   }
# }
```

### Test 4: Análise PDF

```bash
curl -X POST http://localhost:8000/api/analysis \
  -H "Content-Type: application/json" \
  -d '{
    "assessment_file": "/app/input/cc_assessment_data.json",
    "pdf_path": "/app/input/cc_report.pdf",
    "model": "gemini"
  }'

# Response (201):
# {
#   "id": 2,
#   "type": "pdf",
#   "status": "pending",
#   "created_at": "2024-06-09T12:05:00Z"
# }

# Esperar ~35 segundos para 6 tasks completarem
# Então:
curl http://localhost:8000/api/analysis/2

# Deve retornar status='completed' com 6 resultados
```

### Test 5: Listar Análises

```bash
curl "http://localhost:8000/api/analysis?skip=0&limit=10"

# Response:
# {
#   "total": 2,
#   "skip": 0,
#   "limit": 10,
#   "items": [
#     {
#       "id": 2,
#       "type": "pdf",
#       "status": "completed",
#       "created_at": "2024-06-09T12:05:00Z",
#       "results_count": 6
#     },
#     {
#       "id": 1,
#       "type": "basic",
#       "status": "completed",
#       "created_at": "2024-06-09T12:00:00Z",
#       "results_count": 2
#     }
#   ]
# }
```

### Test 6: Filtrar por tipo

```bash
curl "http://localhost:8000/api/analysis?type=pdf"

# Retorna apenas análises do tipo PDF
```

### Test 7: Filtrar por status

```bash
curl "http://localhost:8000/api/analysis?status=completed"

# Retorna apenas análises completas
```

### Test 8: Obter resultados específicos

```bash
curl http://localhost:8000/api/analysis/1/results

# Response:
# {
#   "analysis_id": 1,
#   "results": [
#     {
#       "id": 1,
#       "task_name": "task_1_data_analysis",
#       "result": "...",
#       "created_at": "2024-06-09T12:00:02Z"
#     },
#     {
#       "id": 2,
#       "task_name": "task_2_summarization",
#       "result": "...",
#       "created_at": "2024-06-09T12:00:03Z"
#     }
#   ]
# }
```

### Test 9: Upload de Arquivo Assessment

```bash
curl -X POST http://localhost:8000/api/files/assessment \
  -F "file=@input/adm_data.json"

# Response (201):
# {
#   "id": 1,
#   "filename": "adm_data.json",
#   "file_type": "assessment",
#   "size": 112000,
#   "created_at": "2024-06-09T12:10:00Z"
# }

# Usar esse file_id em análises subsequentes
curl -X POST http://localhost:8000/api/analysis \
  -H "Content-Type: application/json" \
  -d '{
    "assessment_file_id": 1,
    "model": "gemini"
  }'
```

### Test 10: Upload de PDF

```bash
curl -X POST http://localhost:8000/api/files/pdf \
  -F "file=@input/adm_report.pdf"

# Response (201):
# {
#   "id": 2,
#   "filename": "adm_report.pdf",
#   "file_type": "pdf",
#   "size": 11900000,
#   "created_at": "2024-06-09T12:11:00Z"
# }

# Usar em análise PDF
curl -X POST http://localhost:8000/api/analysis \
  -H "Content-Type: application/json" \
  -d '{
    "assessment_file_id": 1,
    "pdf_file_id": 2,
    "model": "gemini"
  }'
```

### Test 11: Deletar Análise

```bash
curl -X DELETE http://localhost:8000/api/analysis/1

# Response:
# {
#   "message": "Analysis deleted successfully",
#   "id": 1
# }

# Verificar que foi deletada:
curl http://localhost:8000/api/analysis/1

# Response (404):
# {
#   "error": "ANALYSIS_NOT_FOUND",
#   "message": "Analysis with ID 1 not found",
#   "timestamp": "2024-06-09T12:12:00Z"
# }
```

### Test 12: Deletar File

```bash
curl -X DELETE http://localhost:8000/api/files/1

# Response:
# {
#   "message": "File deleted successfully",
#   "id": 1
# }
```

---

## 🔍 Debugging

### Ver logs da API

```bash
# Terminal rodando a API mostra logs em tempo real
# Exemplo:
# INFO:     → POST /api/analysis
# INFO:     ← POST /api/analysis 201 (0.234s)
```

### Ver logs do Dramatiq Worker

```bash
docker-compose logs -f dramatiq_worker

# Exemplo:
# ✓ Saved result for task_1_data_analysis
# ✓ Saved result for task_2_summarization
```

### Ver logs do PostgreSQL

```bash
docker-compose logs -f postgres

# Para debuggar problemas de conexão
```

### Ver logs do RabbitMQ

```bash
docker-compose logs -f rabbitmq

# Acessar Management UI: http://localhost:15672
# User: guest
# Password: guest
```

### Verificar BD diretamente

```bash
# Conectar ao PostgreSQL
docker exec -it apoema-postgres psql -U apoema -d apoema_db

# Ver análises
SELECT * FROM analysis ORDER BY created_at DESC;

# Ver resultados
SELECT * FROM analysis_results WHERE analysis_id = 1;

# Ver files
SELECT * FROM analysis_files;

# Contar results
SELECT analysis_id, COUNT(*) as count FROM analysis_results GROUP BY analysis_id;
```

---

## 📊 Monitorando Análises

### Em tempo real (polling manual)

```bash
#!/bin/bash

# watch_analysis.sh - Monitor uma análise em tempo real

analysis_id=$1
interval=${2:-5}  # Default 5 segundos

while true; do
  clear
  echo "=== Analysis Status: $analysis_id ==="
  curl -s http://localhost:8000/api/analysis/$analysis_id | jq '.'
  echo "=== Last update: $(date) ==="
  sleep $interval
done

# Usage:
# chmod +x watch_analysis.sh
# ./watch_analysis.sh 1 5
```

### Ver progresso

```bash
curl -s http://localhost:8000/api/analysis/1 | jq '.progress'

# Output:
# {
#   "total_tasks_expected": 6,
#   "completed_tasks": 3,
#   "percentage": 50.0
# }
```

---

## 🛠️ Troubleshooting

### Problema: "Database connection error"

```bash
# Verificar se PostgreSQL está rodando
docker-compose ps postgres

# Verificar logs
docker-compose logs postgres

# Reconectar:
docker-compose restart postgres

# Rodar migrations
docker-compose up flyway
```

### Problema: "RabbitMQ connection error"

```bash
# Verificar RabbitMQ
docker-compose ps rabbitmq

# Reiniciar
docker-compose restart rabbitmq

# Acessar Management UI
# http://localhost:15672 (guest/guest)
```

### Problema: Task não está sendo processada

```bash
# Verificar se Dramatiq worker está rodando
docker-compose ps dramatiq_worker

# Ver logs
docker-compose logs -f dramatiq_worker

# Reconectar:
docker-compose restart dramatiq_worker

# Verificar fila RabbitMQ (via Management UI)
# http://localhost:15672 → Queues
```

### Problema: Arquivo não encontrado

```bash
# Usar caminhos absolutos ou relativos de /app
# Dentro do container, arquivos estão em /app/input/

# Ou usar file uploads ao invés de caminhos
curl -X POST http://localhost:8000/api/files/assessment \
  -F "file=@input/cc_assessment_data.json"
```

### Problema: CORS error no frontend

```bash
# Configurar CORS_ORIGINS no .env
CORS_ORIGINS="http://localhost:3000,http://localhost:8080"

# Ou aceitar qualquer origin (não recomendado em produção)
CORS_ORIGINS="*"
```

---

## 📈 Performance Testing

### Submeter múltiplas análises rapidamente

```bash
#!/bin/bash

for i in {1..10}; do
  curl -X POST http://localhost:8000/api/analysis \
    -H "Content-Type: application/json" \
    -d "{
      \"assessment_file\": \"/app/input/cc_assessment_data.json\",
      \"model\": \"gemini\"
    }" &
  echo "Submitted analysis $i"
  sleep 0.5
done

wait
echo "All submitted!"

# Monitorar status
curl http://localhost:8000/api/analysis?limit=100 | jq '.items[] | {id, status, results_count}'
```

### Load testing (usando Apache Bench)

```bash
ab -n 100 -c 10 http://localhost:8000/health

# -n: número de requisições (100)
# -c: concurrent requests (10)
```

---

## ✅ Checklist de Testes

- [ ] Health check retorna "ok"
- [ ] Análise BÁSICA cria record no BD
- [ ] Polling retorna status correto
- [ ] Tasks 1-2 completam e salvam resultados
- [ ] Análise PDF executa 6 tasks
- [ ] Análise PNG+CSV executa 5 tasks
- [ ] Listar análises com paginação
- [ ] Filtrar por tipo e status
- [ ] Upload de arquivo funciona
- [ ] Deletar análise remove do BD
- [ ] Error handling retorna 400/404/500 correto
- [ ] CORS headers presentes em responses
- [ ] Logs mostram todas operações
- [ ] Dramatiq worker processa tasks
- [ ] PostgreSQL armazena resultados

---

## 📚 Recursos

- API Docs: http://localhost:8000/docs (Swagger UI)
- ReDoc: http://localhost:8000/redoc
- RabbitMQ UI: http://localhost:15672
- Postgres: localhost:5432 (user: apoema)

---

**Última atualização:** Junho 2024
**Versão:** 1.0.0
**Status:** Pronto para testes ✅
