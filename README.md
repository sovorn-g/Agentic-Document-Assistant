# Agentic Document Assistant

A local RAG assistant with project-scoped resources, persisted chat sessions, SQLite app state, and local Qdrant hybrid retrieval.

This app provides a lightweight "ChatGPT Projects"-style workspace for chatting with PDF and Markdown resources.

## What It Does

- Create separate projects.
- Upload PDF, `.md`, or `.markdown` resources per project.
- Keep multiple chat sessions inside each project.
- Persist chat history across restarts.
- Store compact rolling memory summaries per chat session.
- Index child chunks in embedded Qdrant with dense + sparse vectors.
- Retrieve only documents from the selected project.
- Cache compiled LangGraph agents per project and refresh that cache when resources change.
- Delete individual resources, chats, or projects.

## Quick Start: Local Python / Default Workflow

Use the local virtualenv for normal use, development, debugging, and validation.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and choose your LLM provider.

For DeepSeek:

```bash
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=sk-...
```

For local Ollama:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:4b-instruct-2507-q4_K_M
OLLAMA_BASE_URL=http://localhost:11434
```

If using Ollama locally, also run:

```bash
ollama serve
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Run the app from the repo root:

```bash
python app.py
```

Open:

```text
http://localhost:7860
```

For routine checks, use the venv and frontend build directly:

```bash
./.venv/bin/python -m py_compile server.py core/document_manager.py core/rag_system.py db/vector_db_manager.py utils.py
cd frontend && npm run build
```

## Docker / Compose: Optional Only

Docker is kept for people who want a container path, but it is **not** the default workflow for this project. Routine development should use the venv commands above.

A simple Compose file is included:

```bash
docker compose up --build
```

Stop it with:

```bash
docker compose down
```

Notes:

- Compose persists app data in `./storage`.
- Compose also creates an `ollama-data` volume for container Ollama models.
- The default Compose build installs Ollama because the default provider is `ollama`.
- For hosted providers, set these before building:

```bash
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=sk-...
INSTALL_OLLAMA=0
docker compose up --build
```

Docker is intentionally not tested during normal agent/dev work unless explicitly requested.

## Runtime Storage

Runtime data is ignored by git and lives under `storage/`:

| Path | Purpose |
|------|---------|
| `storage/app_state.sqlite3` | SQLite source of truth for projects, sessions, chat messages, documents, and memory summaries |
| `storage/qdrant_db/` | Local persistent embedded Qdrant database |
| `storage/projects/{project_id}/originals/` | Uploaded source files |
| `storage/projects/{project_id}/markdown/` | Markdown copies or converted PDFs |
| `storage/projects/{project_id}/parent_store/` | JSON parent chunks used after child retrieval |

Model caches are outside the repo by default. The dense Hugging Face cache is typically under:

```text
~/.cache/huggingface/hub/
```

FastEmbed/Qdrant sparse model caches are typically under your user cache directory.

Current retrieval models:

```python
DENSE_MODEL = "sentence-transformers/all-mpnet-base-v2"
SPARSE_MODEL = "Qdrant/bm25"
```

The dense model is the main local embedding cost. BM25 sparse encoding is usually much lighter.

## Project Layout

| Path | Purpose |
|------|---------|
| `app.py` | Venv entry point; launches FastAPI and serves the React frontend |
| `server.py` | FastAPI API, upload/delete/chat endpoints, static frontend serving |
| `config.py` | Storage, model, retrieval, memory, graph, and chunking settings |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Optional container image |
| `docker-compose.yml` | Optional Compose runner |
| `.dockerignore` | Prevents `.venv/` and runtime storage from entering Docker builds |
| `.env.example` | Example environment settings |
| `utils.py` | PDF-to-Markdown conversion, directory cleanup, token estimation |
| `document_chunker.py` | Parent/child Markdown chunking and metadata assignment |
| `frontend/` | React 19 + TypeScript + Vite UI |

### Core

| Path | Purpose |
|------|---------|
| `core/rag_system.py` | Initializes SQLite, Qdrant, embeddings, selected LLM provider, and cached LangGraph agents |
| `core/document_manager.py` | Project-scoped upload, conversion, indexing, deletion, and resource cache invalidation |
| `core/chat_interface.py` | SQLite-backed chat history, memory compaction, and graph execution |
| `core/observability.py` | Optional Langfuse callback setup |

### Storage Layer

| Path | Purpose |
|------|---------|
| `db/sqlite_store.py` | SQLite schema and CRUD for projects, sessions, messages, and documents |
| `db/vector_db_manager.py` | Embedded Qdrant client, dense/sparse embedding setup, collection access, metadata deletes |
| `db/parent_store_manager.py` | File-backed JSON parent chunk store |

### Agent

| Path | Purpose |
|------|---------|
| `rag_agent/graph.py` | Main LangGraph and retrieval subgraph construction |
| `rag_agent/graph_state.py` | Main and per-query graph state definitions |
| `rag_agent/nodes.py` | Summary, rewrite, orchestration, compression, fallback, and aggregation nodes |
| `rag_agent/edges.py` | Conditional routing |
| `rag_agent/tools.py` | Project-filtered `search_child_chunks` and parent retrieval tools |
| `rag_agent/prompts.py` | Agent prompts |
| `rag_agent/schemas.py` | Structured query analysis schema |

## Configuration

All primary knobs are in `config.py` and can be overridden where `config.py` reads environment variables.

### LLM Providers

Supported providers:

```text
ollama, openai, google, deepseek
```

Examples:

```bash
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=sk-...
```

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4.1-mini
OPENAI_API_KEY=sk-...
```

```bash
LLM_PROVIDER=google
LLM_MODEL=gemini-2.5-flash
GOOGLE_API_KEY=...
```

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen3:4b-instruct-2507-q4_K_M
OLLAMA_BASE_URL=http://localhost:11434
```

Do not put real API keys in `config.py`.

### Retrieval

```python
RETRIEVAL_DEFAULT_TOP_K = 6
RETRIEVAL_MAX_TOP_K = 8
RETRIEVAL_SCORE_THRESHOLD = 0.7
```

Search uses Qdrant hybrid mode with dense and sparse retrieval. Each child chunk has metadata:

```text
project_id
document_id
source
parent_id
```

Retrieval filters on `metadata.project_id`, so one project cannot search another project's resources.

### Memory

```python
MEMORY_COMPACTION_MESSAGE_THRESHOLD = 12
MEMORY_RECENT_MESSAGE_COUNT = 8
```

Full chat scrollback remains in SQLite. The model receives the stored `memory_summary` plus recent messages.

### Graph Limits

```python
MAX_TOOL_CALLS = 8
MAX_ITERATIONS = 10
GRAPH_RECURSION_LIMIT = 50
BASE_TOKEN_THRESHOLD = 2000
TOKEN_GROWTH_FACTOR = 0.9
```

### Chunking

```python
CHILD_CHUNK_SIZE = 500
CHILD_CHUNK_OVERLAP = 100
MIN_PARENT_SIZE = 2000
MAX_PARENT_SIZE = 4000
HEADERS_TO_SPLIT_ON = [
    ("#", "H1"),
    ("##", "H2"),
    ("###", "H3"),
]
```

Changing chunk sizes or embedding models requires deleting and re-uploading affected documents.

## Document Lifecycle

On upload:

1. A document ID is generated.
2. The original file is copied into the selected project.
3. PDF is converted to Markdown, or Markdown is copied as-is.
4. Parent and child chunks are created.
5. Child chunks are inserted into Qdrant with project/document metadata.
6. Parent chunks are saved as JSON under the project's parent store.
7. A document row is saved in SQLite.
8. The project's cached agent graph/retrieval handle is refreshed.

On delete:

1. Original and Markdown files are removed.
2. Parent chunk JSON files for that document are removed.
3. Qdrant points matching `document_id` are deleted with wait enabled.
4. SQLite marks the document deleted.
5. The project's cached agent graph/retrieval handle is refreshed.

On project delete, project files, Qdrant points, document records, and chat sessions are removed.

## Langfuse Observability

Tracing is optional. Set these environment variables or put them in `.env`:

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Leave `LANGFUSE_ENABLED=false` or unset to disable tracing.

## Operational Notes

- This is a local/internal single-user style app.
- SQLite is the durable app state layer.
- Qdrant is embedded and local by default.
- Scanned PDFs are not OCRed. PDF conversion uses PyMuPDF/PyMuPDF4LLM.
- The local `.venv/` is ignored by git.
- Docker does not copy `.venv/` or `storage/` because of `.dockerignore`.
- If the dense embedding model cache is deleted, the next app start will download it again.
- If `DENSE_MODEL` changes, recreate Qdrant data or delete/re-upload affected documents because vector dimensions may change.

## Troubleshooting

| Issue | Likely Cause | Fix |
|------|--------------|-----|
| `python: command not found` | macOS shell only exposes `python3` | Use `python3 app.py` or activate `.venv` |
| DeepSeek startup fails with missing key | `LLM_PROVIDER=deepseek` but `DEEPSEEK_API_KEY` is unset | Put `DEEPSEEK_API_KEY=sk-...` in `.env` or export it in your shell |
| OpenAI startup fails with missing key | `LLM_PROVIDER=openai` but `OPENAI_API_KEY` is unset | Put `OPENAI_API_KEY=sk-...` in `.env` or export it in your shell |
| Google startup fails with missing key | `LLM_PROVIDER=google` but `GOOGLE_API_KEY` is unset | Put `GOOGLE_API_KEY=...` in `.env` or export it in your shell |
| Ollama answers fail | Ollama model is missing or Ollama is not running | Run `ollama serve` and `ollama pull qwen3:4b-instruct-2507-q4_K_M` |
| First startup is slow | Embedding models are downloading/loading | Wait for Hugging Face/FastEmbed caches to populate |
| Upload says `Added 0, skipped 1` | Unsupported/empty file or conversion/chunking issue | Try a non-empty PDF/Markdown file and check terminal logs |
| Retrieval returns nothing | No resources indexed, score threshold too strict, or wrong project selected | Upload resources, lower `RETRIEVAL_SCORE_THRESHOLD`, verify project |
| Stale results after config changes | Existing Qdrant vectors were created with old settings | Delete and re-upload affected resources |
| Docker loses projects | `storage/` is not mounted | Use the included `docker-compose.yml`, which mounts `./storage:/app/storage` |
