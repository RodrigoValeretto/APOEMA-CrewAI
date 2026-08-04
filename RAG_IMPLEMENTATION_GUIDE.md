# RAG Implementation Guide

Complete guide to the APOEMA RAG system architecture, setup, usage, and integration.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [System Components](#system-components)
4. [Setup & Configuration](#setup--configuration)
5. [Usage Examples](#usage-examples)
6. [API Integration](#api-integration)
7. [CrewAI Agent Integration](#crewai-agent-integration)
8. [Deduplication Strategy](#deduplication-strategy)
9. [Best Practices](#best-practices)
10. [Troubleshooting](#troubleshooting)

---

## Quick Start

### 1. Start Docker Environment

```bash
make docker-up
```

This automatically:
- Starts PostgreSQL with pgvector extension
- Starts RabbitMQ for task queue
- Starts Ollama for embeddings
- Starts API server (port 8000)
- Starts Dramatiq workers
- **Indexes files from `input/` and `uploads/` directories**

### 2. Check RAG Status

```bash
# View indexed documents
make rag-list

# View RAG statistics
make rag-stats

# Search the RAG database
make rag-search query="What assessment standards apply to engineering programs?"
```

### 3. Upload a File via API

```bash
curl -X POST http://localhost:8000/api/files/assessment \
  -F "file=@cc_assessment_data.json"

# Response:
# {
#   "id": 15,
#   "filename": "cc_assessment_data.json",
#   "file_type": "assessment",
#   "size": 10485,
#   "created_at": "2026-07-21T10:30:45.123456"
# }
```

**Note:** File is saved immediately and available for analysis. RAG indexing happens asynchronously in the background.

### 4. Run Analysis with RAG Context

```bash
curl -X POST http://localhost:8000/api/analysis \
  -H "Content-Type: application/json" \
  -d '{
    "assessment_file": "/uploads/15_cc_assessment_data.json",
    "model": "ollama"
  }'

# The analysis CrewAI agents have access to RAG tool for semantic search
```

---

## Architecture Overview

### High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         APOEMA System                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌──────────────┐         ┌──────────────┐                          │
│  │   FastAPI    │         │   CrewAI     │                          │
│  │  (API Layer) │────────>│ (Agents)     │                          │
│  └──────┬───────┘         └──────┬───────┘                          │
│         │                        │                                   │
│    File Upload            Query Execution                           │
│    (Sync)                (Synchronous)                              │
│         │                        │                                   │
│         ├──────────────┬─────────┤                                   │
│         │              │         │                                   │
│         v              v         v                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  RabbitMQ    │  │  PostgreSQL  │  │   Ollama     │              │
│  │  (Task Queue)│  │  (pgvector)  │  │ (Embeddings) │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                  │                      │
│    Enqueue Task      Store & Search     Generate Vectors            │
│    (Non-blocking)    Semantic Info      for Similarity              │
│         │                 │                  │                      │
│         └────────┬────────┘──────────────────┘                      │
│                  │                                                   │
│                  v                                                   │
│         ┌─────────────────────┐                                      │
│         │ Dramatiq Workers    │                                      │
│         │ (Background Tasks)  │                                      │
│         └─────────────────────┘                                      │
│         ├─ Analysis Processor (Priority 0)                          │
│         ├─ Queue Manager (Priority 10)                             │
│         └─ RAG Indexer (Priority 5)                                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Request Lifecycle

#### File Upload (Non-Blocking)

```
1. POST /api/files/{type} with file
                ↓
2. Save file to disk (50-200ms)
                ↓
3. Create database record (5-10ms)
                ↓
4. Call index_file_for_rag.send()
                ↓
5. Return 201 Created response (total ~60-210ms)
                ↓
6. [Async] RabbitMQ processes indexing task
                ↓
7. [Async] Worker: Generate embeddings (100-500ms per chunk)
                ↓
8. [Async] Worker: Insert chunks into pgvector (5-15ms per chunk)
                ↓
9. [Async] Complete (1-5 minutes later)
```

#### Analysis Query (With RAG Context)

```
1. POST /api/analysis with file paths
                ↓
2. Create analysis record (pending)
                ↓
3. Call enqueue_analysis_for_sequential_processing.send()
                ↓
4. Return response
                ↓
5. Queue manager checks if other analyses running
                ↓
6. If not, call run_analysis_flow_with_tracking.send()
                ↓
7. CrewAI agents execute with RAG tool access
                ↓
8. Agent calls RAG query: "rag_tool.query(question)"
                ↓
9. RAG Manager: Generate embedding for question (200ms)
                ↓
10. pgvector: Similarity search (50-200ms)
                ↓
11. Format results and return to agent
                ↓
12. Agent processes context and generates response
                ↓
13. Results saved to analysis_results table
```

---

## System Components

### 1. **RAG Manager** (`rag/rag_manager.py`)

Core RAG operations.

**Key Methods:**

```python
# Embedding generation
embedding = rag_manager.generate_embedding(text)

# Document management
doc_id = rag_manager.create_document(
    source_path="/path/to/file.json",
    source_type="json",
    title="Assessment Data",
    file_hash="abc123...",
    metadata={"indexed_at": "2026-07-21T10:30:00Z"}
)

# Chunk insertion
chunk_id = rag_manager.insert_chunk(
    document_id=doc_id,
    chunk_index=0,
    content="Chunk text here...",
    embedding=[0.123, 0.456, ...],
    metadata={"chunk_type": "text"}
)

# Semantic search
results = rag_manager.similarity_search(
    query="What are assessment criteria?",
    limit=5,
    similarity_threshold=0.3,
    source_types=["json", "pdf"]
)

# Vector index creation (run once after initial load)
rag_manager.create_vector_index(lists=100)
```

### 2. **RAG Indexer** (`rag/rag_indexer.py`)

File processing and chunking.

**Key Methods:**

```python
indexer = RagIndexer(rag_manager)

# Set chunking parameters
indexer.chunk_size = 1000
indexer.chunk_overlap = 200

# Index different file types
doc_id = indexer.index_pdf("/path/to/report.pdf")
doc_id = indexer.index_json("/path/to/assessment.json")
doc_id = indexer.index_text("/path/to/document.txt")

# Index entire directory
doc_ids = indexer.index_directory(
    directory="/path/to/files",
    file_types=[".pdf", ".json"],
    recursive=True
)

# Check if document exists (deduplication)
file_hash = rag_manager.compute_file_hash("/path/to/file.pdf")
existing_id = rag_manager.document_exists(file_hash)
if existing_id:
    print(f"Already indexed as doc_id={existing_id}")
```

### 3. **Task Queue** (`tasks.py`)

Asynchronous task processing via Dramatiq.

**Key Actors:**

```python
# Queue management (highest priority)
enqueue_analysis_for_sequential_processing(
    analysis_id, assessment_file, pdf_file, png_file, csv_file,
    output_prefix, model
)

# Analysis execution (normal priority)
run_analysis_flow_with_tracking(
    analysis_id, assessment_file, pdf_file, png_file, csv_file,
    output_prefix, model
)

# RAG indexing (medium-low priority)
index_file_for_rag(file_path, file_type)
```

### 4. **RAG Tool** (`apoema_agent.py`)

Wrapper for CrewAI agent access to RAG.

```python
from apoema_rag_tool import ApoemaRagTool

# Initialize tool
rag_tool = ApoemaRagTool()

# Execute search
results = rag_tool._run(
    query="What are the specific requirements for civil engineering accreditation?",
    similarity_threshold=0.35,
    limit=3
)

# Results are formatted for LLM context
# "--- Result 1 (similarity: 0.87) ---\n
#  Source: /path/to/doc\n
#  Document: Assessment Data\n
#  Type: json\n
#  Content: ..."
```

---

## Setup & Configuration

### 1. Environment Variables

Create `.env` or modify `config.py`:

```python
# Database
DB_HOST = "postgres"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "postgres"
DB_NAME = "apoema"

# Ollama (embeddings)
OLLAMA_BASE_URL = "http://ollama:11434"

# RAG Configuration
RAG_EMBEDDING_MODEL = "nomic-embed-text"  # 768-dim, 200ms per embedding
RAG_EMBEDDING_DIM = 768
RAG_CHUNK_SIZE = 1000  # characters per chunk
RAG_CHUNK_OVERLAP = 200  # overlap for context

# Directories
RAG_INPUT_DIR = "input"  # Reference documents
UPLOAD_DIR = "uploads"  # User uploads
```

### 2. Database Schema

RAG uses two main tables (created by `schema.sql`):

```sql
-- rag_documents: Metadata for each indexed file
CREATE TABLE rag_documents (
    id SERIAL PRIMARY KEY,
    source_path TEXT NOT NULL,          -- Original file path
    source_type VARCHAR(50) NOT NULL,   -- pdf, json, txt, md
    title VARCHAR(500),                 -- Document title
    file_hash VARCHAR(64),              -- SHA256 of raw bytes
    metadata JSONB,                     -- {content_hash, indexed_at, ...}
    chunk_count INT DEFAULT 0,          -- Number of chunks
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- rag_chunks: Individual text chunks with embeddings
CREATE TABLE rag_chunks (
    id SERIAL PRIMARY KEY,
    document_id INT NOT NULL,           -- Foreign key to rag_documents
    chunk_index INT NOT NULL,           -- Position within document
    content TEXT NOT NULL,              -- Actual text
    content_hash VARCHAR(64),           -- SHA256 of chunk content
    embedding vector(768),              -- pgvector (768-dim)
    embedding_model VARCHAR(100),       -- Model used (nomic-embed-text)
    metadata JSONB,                     -- {chunk_type, position, ...}
    token_count INT,                    -- Estimated token count
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(document_id, chunk_index),
    FOREIGN KEY(document_id) REFERENCES rag_documents(id) ON DELETE CASCADE
);

-- Vector index for fast semantic search
CREATE INDEX idx_rag_chunks_embedding
ON rag_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### 3. Docker Compose Setup

Key services (from `docker-compose.yml`):

```yaml
services:
  # PostgreSQL with pgvector
  apoema-postgres:
    image: pgvector/pgvector:latest
    environment:
      POSTGRES_DB: apoema
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - ./schema.sql:/docker-entrypoint-initdb.d/schema.sql
      - postgres_data:/var/lib/postgresql/data

  # RabbitMQ for Dramatiq
  apoema-rabbitmq:
    image: rabbitmq:management
    ports:
      - "5672:5672"
      - "15672:15672"

  # Ollama for embeddings
  apoema-ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    environment:
      OLLAMA_MODELS_DIR: /models
    volumes:
      - ollama_data:/models

  # FastAPI server
  apoema-app:
    build: .
    command: python run_api.py
    ports:
      - "8000:8000"
    depends_on:
      - apoema-postgres
      - apoema-rabbitmq
      - apoema-ollama

  # Dramatiq worker (analysis + RAG)
  apoema-dramatiq-worker:
    build: .
    command: dramatiq tasks --processes 4 --threads 2
    depends_on:
      - apoema-postgres
      - apoema-rabbitmq
      - apoema-ollama
    volumes:
      - ./uploads:/app/uploads
      - ./input:/app/input
```

### 4. Initialization

```bash
# Start environment
make docker-up

# Wait for services to be ready (~30 seconds)
sleep 30

# Index reference documents
make rag-index

# View statistics
make rag-stats
```

---

## Usage Examples

### Example 1: Upload and Index Assessment File

```bash
# Upload via API
curl -X POST http://localhost:8000/api/files/assessment \
  -F "file=@assessments/medicine_2024.json"

# Immediate response (file saved, indexing in background)
# {
#   "id": 42,
#   "filename": "medicine_2024.json",
#   "file_type": "assessment",
#   "size": 50000,
#   "created_at": "2026-07-21T10:30:45Z"
# }

# Check RAG status (after 1-2 minutes)
make rag-stats

# Output:
# {
#   "total_documents": 126,
#   "total_chunks": 2545,
#   "documents_by_type": [
#     {"source_type": "json", "count": 61},  # New document counted
#     {"source_type": "pdf", "count": 45}
#   ]
# }
```

### Example 2: Search RAG Database

```bash
# Search for engineering assessment criteria
make rag-search query="What are the accreditation criteria for engineering programs?"

# Output:
# Searching RAG database for: "What are the accreditation criteria for..."
#
# --- Result 1 (similarity: 0.89) ---
# Source: /app/input/engineering_assessment.json
# Document: Engineering Program Assessment
# Type: json
# Content: "Accreditation Criteria Section 1: Engineering design integration,
#           student learning outcomes assessment, ABET compliance requirements..."
#
# --- Result 2 (similarity: 0.81) ---
# Source: /app/uploads/42_medicine_2024.json
# Document: Medicine Program Assessment
# Type: json
# Content: "While medicine differs from engineering, both require verification of
#           learning outcomes through comprehensive assessment rubrics..."
```

### Example 3: Upload and Analyze Concurrently

```bash
# Start analysis
ANALYSIS_ID=$(curl -s -X POST http://localhost:8000/api/analysis \
  -H "Content-Type: application/json" \
  -d '{
    "assessment_file": "input/engineering.json",
    "pdf_file": "input/accreditation_report.pdf",
    "model": "ollama"
  }' | jq -r '.id')

echo "Analysis $ANALYSIS_ID started"

# Meanwhile, upload new file (doesn't block)
curl -X POST http://localhost:8000/api/files/pdf \
  -F "file=@reports/new_accreditation.pdf"

# Check analysis progress
curl http://localhost:8000/api/analysis/$ANALYSIS_ID

# Both happen concurrently:
# - Analysis: CrewAI agents processing (10 minutes)
# - Indexing: PDF file being embedded and indexed (20 seconds)
# No interference or blocking
```

### Example 4: Prevent Duplicate Indexing

```bash
# Upload original
curl -X POST http://localhost:8000/api/files/assessment \
  -F "file=@data.json"
# Response: doc_id=100

# Upload identical file with different name (tier 1 check)
curl -X POST http://localhost:8000/api/files/assessment \
  -F "file=@data_copy.json"
# File hash matches → Skip, return doc_id=100 (no duplication)

# Upload semantically identical but different formatting
curl -X POST http://localhost:8000/api/files/assessment \
  -F "file=@data_reformatted.json"
# Tier 1 fails (different formatting = different bytes)
# Tier 2: Content hash matches → Skip, return doc_id=100 (semantic duplicate)

# Result: Database has 1 copy, 3 logical documents reference same data
```

---

## API Integration

### File Upload Endpoints

Upload endpoints save the file immediately and return the response. Assessment and PDF uploads trigger RAG indexing asynchronously; CSV and PNG uploads are saved for analysis only (they are **not** indexed into RAG).

#### POST /api/files/assessment

```bash
curl -X POST http://localhost:8000/api/files/assessment \
  -F "file=@assessment.json"

# Response:
{
  "id": 15,
  "filename": "assessment.json",
  "file_type": "assessment",
  "size": 10240,
  "created_at": "2026-07-21T10:30:45.123456"
}
```

**RAG Behavior:**
- File indexed immediately via `index_json()`
- Tier 1: File hash check
- Tier 2: Content hash check
- Returns existing doc_id if duplicate found
- Otherwise creates new document and chunks

#### POST /api/files/pdf

```bash
curl -X POST http://localhost:8000/api/files/pdf \
  -F "file=@report.pdf"
```

**RAG Behavior:**
- File indexed via `index_pdf()`
- Text extraction (pymupdf → pdfplumber → PyPDF2)
- Semantic deduplication
- Chunks created for each page/section

#### POST /api/files/csv

```bash
curl -X POST http://localhost:8000/api/files/csv \
  -F "file=@data.csv"
```

**RAG Behavior:**
- File saved but **NOT indexed** (CSV files feed the plot-analysis workflow, not RAG)
- Returns immediately
- Available for analysis via file reference

#### POST /api/files/png

```bash
curl -X POST http://localhost:8000/api/files/png \
  -F "file=@plot.png"
```

**RAG Behavior:**
- File saved but **NOT indexed** (images have no searchable text)
- Returns immediately
- Available for analysis via file reference

### Analysis Endpoints

#### GET /api/analysis/{analysis_id}

```bash
curl http://localhost:8000/api/analysis/1

# Response:
{
  "id": 1,
  "type": "basic",  # or "pdf", or "png_csv"
  "status": "processing",  # pending, processing, completed, failed
  "created_at": "2026-07-21T10:00:00Z",
  "updated_at": "2026-07-21T10:05:30Z",
  "progress": {
    "total_tasks_expected": 6,
    "completed_tasks": 3,
    "percentage": 50.0
  },
  "results": [
    {
      "id": 1,
      "task_name": "assessment_evaluation",
      "result": "Assessment content evaluated. Key findings: ...",
      "created_at": "2026-07-21T10:02:15Z"
    }
  ]
}
```

**RAG Integration:**
- During analysis execution, CrewAI agents access RAG via `rag_tool`
- Agent can query: "What are similar assessment structures in the database?"
- RAG returns formatted context from similar documents
- Agent incorporates into analysis

---

## CrewAI Agent Integration

### Access RAG from Agents

#### 1. Tool Registration

```python
# In apoema_agent.py
from apoema_rag_tool import ApoemaRagTool

# Create tool instance
rag_tool = ApoemaRagTool()

# Register with agents
assessment_agent = Agent(
    role="Assessment Analyzer",
    goal="Analyze government assessment standards",
    tools=[rag_tool],  # Add RAG tool
    llm=llm,
)
```

#### 2. Agent Query Example

```python
# Agent executes task:
task = Task(
    description="""
    Analyze the provided assessment document and compare it with similar
    assessments in the knowledge base. Identify gaps and strengths.

    Use the rag_tool to search for similar assessment documents.
    """,
    agent=assessment_agent,
    expected_output="Analysis report with comparisons"
)

# Under the hood, agent might execute:
# Agent: "I should search for similar assessment documents"
# Tool Call: rag_tool._run(
#   query="Similar assessment criteria for civil engineering programs",
#   limit=3,
#   similarity_threshold=0.35
# )

# RAG Response:
# --- Result 1 (similarity: 0.91) ---
# Source: /app/input/engineering_assessment.json
# Content: "Civil Engineering Assessment Criteria:
#   1. Design integration and project-based learning
#   2. Professional ethics assessment
#   3. ..."

# Agent: "These assessments show similar structure. The provided assessment
# includes criteria that exceed these in 3 areas but lacks assessment of..."
```

### Customize RAG Queries

```python
# In agent description, guide RAG behavior
description = """
When analyzing assessments, use the rag_tool to find similar documents.

RAG Tips:
- Use similarity_threshold=0.35-0.5 for broad searches
- Use limit=5-10 for comprehensive context
- Search for: "What assessment criteria apply to [program]?"
"""
```

### Monitor RAG Calls

```bash
# View logs showing RAG queries
docker logs -f apoema-dramatiq-worker | grep -A 2 "similarity_search"

# Output:
# [Analysis 5] Agent: "Using rag_tool to find assessment documents"
# [RAG Search] Query: "Assessment criteria for engineering"
# [RAG Search] Results: 5 chunks (similarity: 0.87, 0.82, 0.79, 0.76, 0.72)
```

---

## Deduplication Strategy

### Tier 1: File Hash (Byte-Level)

**What it catches:**
```
Original file:     assessment.json (10KB, MD5: abc123...)
Duplicate copy:    assessment_backup.json (10KB, MD5: abc123...)
Result:            Tier 1 match → Skip, return existing doc_id
```

**Process:**
```python
file_hash = compute_file_hash(file_path)  # SHA256 of raw bytes
existing_id = document_exists(file_hash)  # Check if hash exists
if existing_id:
    return existing_id  # Already indexed
```

**Cost:** O(file_size), ~50-100ms

### Tier 2: Content Hash (Semantic)

**What it catches:**
```
File A:
{
  "name": "Assessment",
  "year": 2024,
  "criteria": [...]
}

File B:
{
  "year": 2024,
  "name": "Assessment",
  "criteria": [...]
}

Result: Tier 1 miss (different key order)
        Tier 2 match (normalized JSON identical) → Skip
```

**Process:**
```python
text = extract_text(file_path)
content_hash = compute_content_hash(text)  # Normalize + hash
existing_id = content_hash_exists(content_hash)
if existing_id:
    return existing_id  # Already indexed (different formatting)
```

**Cost:** O(content_size), ~10-50ms

### Deduplication in Metadata

Stored for audit trail:

```python
# From index_json() in rag_indexer.py
doc_id = rag_manager.create_document(
    source_path=json_path,
    source_type="json",
    title=title,
    file_hash=file_hash,
    metadata={
        "file_name": os.path.basename(json_path),
        "content_hash": content_hash,  # For reference
        "indexed_at": datetime.now().isoformat(),
    },
)
```

### Force Re-indexing

```bash
# Bypass deduplication for testing
make rag-reindex  # Uses --force flag

# Or programmatically
indexer = RagIndexer(rag_manager)
indexer.force_reindex = True
doc_id = indexer.index_json("test.json")  # Ignores deduplication
```

---

## Best Practices

### 1. Document Organization

**Reference Documents (input/):**
```
input/
├── 2024/
│   ├── engineering_assessment.json
│   ├── medicine_assessment.json
│   └── law_assessment.json
└── 2023/
    ├── engineering_assessment.json
    └── medicine_assessment.json
```

**User Uploads (uploads/):**
```
uploads/
├── 1_assessment.json       # Auto-indexed on upload
├── 2_report.pdf
├── 3_data.csv              # Saved but not indexed
├── 4_plot.png              # Saved but not indexed
└── 5_assessment_copy.json  # Dedup: references doc_id 1
```

### 2. Chunking Strategy

**For Different File Types:**

```python
# Assessment JSON: Larger chunks (contain context)
indexer.chunk_size = 1500
indexer.chunk_overlap = 300

# PDFs: Medium chunks (respects page boundaries)
indexer.chunk_size = 1000
indexer.chunk_overlap = 200

# Plain text: Medium chunks (semantic units)
indexer.chunk_size = 1000
indexer.chunk_overlap = 200
```

### 3. Search Thresholds

**For Different Use Cases:**

```python
# Strict matching (exact topic)
results = rag.similarity_search(
    query="ABET accreditation criteria for civil engineering",
    similarity_threshold=0.5  # Only very similar results
)

# Moderate matching (related topics)
results = rag.similarity_search(
    query="Assessment criteria for engineering programs",
    similarity_threshold=0.35  # Default
)

# Broad matching (any related content)
results = rag.similarity_search(
    query="What assessment standards exist?",
    similarity_threshold=0.2  # More permissive
)
```

### 4. Vector Index Maintenance

```bash
# After initial indexing, create index
make rag-index --create-vector-index

# After adding many documents (1000+), recreate index
make rag-reindex --create-vector-index

# Monitor index performance
docker exec -it apoema-postgres psql -U postgres -d apoema -c \
  "SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read
   FROM pg_stat_user_indexes
   WHERE tablename = 'rag_chunks';"
```

### 5. Monitoring RAG Health

```bash
# Daily check: Verify new documents indexed
make rag-stats

# Weekly check: Search test queries
make rag-search query="Common assessment criteria"
make rag-search query="Accreditation requirements"

# Monthly check: Look for anomalies
docker exec -it apoema-postgres psql -U postgres -d apoema -c \
  "SELECT source_type, COUNT(*) as count, AVG(chunk_count) as avg_chunks
   FROM rag_documents
   GROUP BY source_type;"
```

---

## Troubleshooting

### Problem: Upload API Returns Immediately, But File Not in RAG

**Symptom:**
```bash
curl -X POST http://localhost:8000/api/files/assessment -F "file=@test.json"
# Returns 201 Created immediately

make rag-list
# File not listed (yet)
```

**Explanation:** This is **normal**. RAG indexing happens asynchronously (1-5 minutes later).

**Diagnosis:**
```bash
# Check Dramatiq worker logs
docker logs apoema-dramatiq-worker | grep -A 5 "RAG Indexing"

# Should show:
# [RAG Indexing] Starting indexing for assessment: /app/uploads/123_test.json
# [RAG Indexing] ✓ Successfully indexed assessment (doc_id=50): ...
```

**If still not showing after 5 minutes:**
```bash
# Check if Ollama is running
curl http://localhost:11434/api/models

# Check if RabbitMQ has tasks queued
docker logs apoema-rabbitmq

# Restart worker
docker restart apoema-dramatiq-worker
```

### Problem: RAG Searches Return No Results

**Symptom:**
```bash
make rag-search query="Assessment criteria"
# Output: "No relevant documents found in the RAG database"
```

**Possible Causes:**

1. **No documents indexed:**
   ```bash
   make rag-list
   # If empty, run:
   make rag-index
   ```

2. **Vector index not created:**
   ```bash
   docker exec -it apoema-postgres psql -U postgres -d apoema -c \
     "SELECT indexname FROM pg_indexes WHERE tablename='rag_chunks';"
   # If no idx_rag_chunks_embedding, run:
   make rag-index --create-vector-index
   ```

3. **Similarity threshold too high:**
   ```bash
   # Try lower threshold
   make rag-search query="Assessment" threshold=0.2
   ```

4. **Query too different from documents:**
   ```bash
   # Try broader search
   make rag-search query="criteria"  # Shorter, more general
   ```

### Problem: Database Growing Very Large

**Symptom:**
```bash
make rag-stats
# {
#   "total_documents": 50,
#   "total_chunks": 50000,  # Very high for 50 documents
#   ...
# }
```

**Diagnosis - Check for duplicates:**

```bash
docker exec -it apoema-postgres psql -U postgres -d apoema -c \
  "SELECT title, COUNT(*) as doc_count, SUM(chunk_count) as total_chunks
   FROM rag_documents
   GROUP BY title
   HAVING COUNT(*) > 1
   ORDER BY total_chunks DESC;"
```

**If duplicates found:**

```bash
# Option 1: Re-index with deduplication
make rag-reindex

# Option 2: Manual cleanup (if you're sure about duplicates)
docker exec -it apoema-postgres psql -U postgres -d apoema -c \
  "DELETE FROM rag_documents WHERE id = 42;"
```

### Problem: Indexing Appears Stuck

**Symptom:**
```bash
# Upload file, wait 10 minutes
make rag-list
# File not appearing

docker logs apoema-dramatiq-worker
# No recent RAG messages
```

**Diagnosis:**

```bash
# Check if Ollama is responsive
curl http://ollama:11434/api/models
# If hangs, Ollama is stuck

# Check database connection
docker exec apoema-postgres pg_isready
# Should output "accepting connections"

# Check RabbitMQ
docker exec apoema-rabbitmq rabbitmqctl status
```

**Solution:**

```bash
# Restart problematic services
docker restart apoema-ollama
docker restart apoema-dramatiq-worker

# Or restart entire environment
make docker-down
make docker-up
```

---

## Summary Table

| Task | Command | Time | Notes |
|------|---------|------|-------|
| Start environment | `make docker-up` | 30s | Auto-indexes input/ |
| List documents | `make rag-list` | <1s | Shows all indexed docs |
| View statistics | `make rag-stats` | 1s | Document counts by type |
| Search RAG | `make rag-search query="..."` | 1-3s | Uses cosine similarity |
| Create index | `make rag-index` | 10-60s | Required for fast search |
| Upload file | `curl ... /api/files/*` | 100-500ms | File saved, indexing async |
| Analyze | `curl ... /api/analysis` | 10 min | Uses RAG in background |
| Re-index (force) | `make rag-reindex` | varies | Reprocesses all files |
