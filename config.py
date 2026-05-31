import os

# --- Directory Configuration ---
_BASE_DIR = os.path.dirname(__file__)

STORAGE_DIR = os.path.join(_BASE_DIR, "storage")
PROJECTS_STORAGE_DIR = os.path.join(STORAGE_DIR, "projects")
APP_DB_PATH = os.path.join(STORAGE_DIR, "app_state.sqlite3")
MARKDOWN_DIR = os.path.join(STORAGE_DIR, "markdown_docs")
PARENT_STORE_PATH = os.path.join(STORAGE_DIR, "parent_store")
QDRANT_DB_PATH = os.path.join(STORAGE_DIR, "qdrant_db")

# --- Qdrant Configuration ---
CHILD_COLLECTION = "document_child_chunks"
SPARSE_VECTOR_NAME = "sparse"

# --- Model Configuration ---
DENSE_MODEL = "sentence-transformers/all-mpnet-base-v2"
SPARSE_MODEL = "Qdrant/bm25"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0"))
LLM_DISABLE_THINKING = os.environ.get("LLM_DISABLE_THINKING", "true").lower() == "true"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# --- Agent Configuration ---
MAX_TOOL_CALLS = 8
MAX_ITERATIONS = 10
GRAPH_RECURSION_LIMIT = 50
BASE_TOKEN_THRESHOLD = 2000
TOKEN_GROWTH_FACTOR = 0.9
MEMORY_COMPACTION_MESSAGE_THRESHOLD = 12
MEMORY_RECENT_MESSAGE_COUNT = 8

# --- Retrieval Configuration ---
RETRIEVAL_DEFAULT_TOP_K = 6
RETRIEVAL_MAX_TOP_K = 8
RETRIEVAL_SCORE_THRESHOLD = 0.7

# --- Text Splitter Configuration ---
CHILD_CHUNK_SIZE = 500
CHILD_CHUNK_OVERLAP = 100
MIN_PARENT_SIZE = 2000
MAX_PARENT_SIZE = 4000
HEADERS_TO_SPLIT_ON = [
    ("#", "H1"),
    ("##", "H2"),
    ("###", "H3")
]

# --- Langfuse Observability ---
LANGFUSE_ENABLED = os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000")
