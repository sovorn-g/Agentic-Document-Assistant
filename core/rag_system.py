import uuid
from pathlib import Path
import config
from db.vector_db_manager import VectorDbManager
from db.parent_store_manager import ParentStoreManager
from db.sqlite_store import SQLiteStore
from core.chunking import DocumentChunker
from rag_agent.tools import ToolFactory
from rag_agent.graph import create_agent_graph
from core.observability import Observability

class RAGSystem:

    def __init__(self, collection_name=config.CHILD_COLLECTION):
        self.collection_name = collection_name
        self.vector_db = VectorDbManager()
        self.store = SQLiteStore()
        self.chunker = DocumentChunker()
        self.observability = Observability()
        self.llm = None
        self.collection = None
        self.agent_graph = None
        self._agent_graph_cache = {}
        self.thread_id = str(uuid.uuid4())
        self.recursion_limit = config.GRAPH_RECURSION_LIMIT

    def initialize(self):
        self.vector_db.create_collection(self.collection_name)
        self.refresh_collection()

        self.llm = self._create_llm()
        self.agent_graph = self.create_agent_graph()

    def refresh_collection(self):
        self.collection = self.vector_db.get_collection(self.collection_name)
        return self.collection

    def _create_llm(self):
        provider = config.LLM_PROVIDER

        if provider == "ollama":
            from langchain_ollama import ChatOllama
            no_thinking_kwargs = self._no_thinking_kwargs(ChatOllama)

            return ChatOllama(
                model=config.LLM_MODEL,
                temperature=config.LLM_TEMPERATURE,
                base_url=config.OLLAMA_BASE_URL,
                **no_thinking_kwargs,
            )

        if provider == "openai":
            self._require_api_key("OPENAI_API_KEY", config.OPENAI_API_KEY, provider)
            from langchain_openai import ChatOpenAI
            no_thinking_kwargs = self._no_thinking_kwargs(ChatOpenAI)

            return ChatOpenAI(
                model=config.LLM_MODEL,
                temperature=config.LLM_TEMPERATURE,
                api_key=config.OPENAI_API_KEY,
                **no_thinking_kwargs,
            )

        if provider == "google":
            self._require_api_key("GOOGLE_API_KEY", config.GOOGLE_API_KEY, provider)
            from langchain_google_genai import ChatGoogleGenerativeAI
            no_thinking_kwargs = self._no_thinking_kwargs(ChatGoogleGenerativeAI)

            return ChatGoogleGenerativeAI(
                model=config.LLM_MODEL,
                temperature=config.LLM_TEMPERATURE,
                google_api_key=config.GOOGLE_API_KEY,
                **no_thinking_kwargs,
            )

        if provider == "deepseek":
            self._require_api_key("DEEPSEEK_API_KEY", config.DEEPSEEK_API_KEY, provider)
            from langchain_deepseek import ChatDeepSeek
            no_thinking_kwargs = self._no_thinking_kwargs(ChatDeepSeek)

            return ChatDeepSeek(
                model=config.LLM_MODEL,
                temperature=config.LLM_TEMPERATURE,
                api_key=config.DEEPSEEK_API_KEY,
                **no_thinking_kwargs,
            )

        raise ValueError(
            f"Unsupported LLM_PROVIDER={provider!r}. "
            "Supported providers: ollama, openai, google, deepseek."
        )

    @staticmethod
    def _no_thinking_kwargs(llm_cls):
        if not config.LLM_DISABLE_THINKING:
            return {}

        kwargs = {
            "extra_body": {
                "thinking": {"type": "disabled"},
            },
        }
        supported_fields = set(getattr(llm_cls, "model_fields", {}))
        return {key: value for key, value in kwargs.items() if key in supported_fields}

    @staticmethod
    def _require_api_key(env_name: str, value: str, provider: str) -> None:
        if not value:
            raise RuntimeError(
                f"{env_name} is required when LLM_PROVIDER={provider}. "
                "Set it in .env or your shell environment."
            )

    def get_project_storage_dir(self, project_id: str) -> Path:
        path = Path(config.PROJECTS_STORAGE_DIR) / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_project_markdown_dir(self, project_id: str) -> Path:
        path = self.get_project_storage_dir(project_id) / "markdown"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_project_originals_dir(self, project_id: str) -> Path:
        path = self.get_project_storage_dir(project_id) / "originals"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_parent_store(self, project_id: str) -> ParentStoreManager:
        return ParentStoreManager(self.get_project_storage_dir(project_id) / "parent_store")

    def create_agent_graph(self, project_id=None):
        cache_key = project_id or "__default__"
        if cache_key in self._agent_graph_cache:
            return self._agent_graph_cache[cache_key]

        parent_store = self.get_parent_store(project_id) if project_id else ParentStoreManager()
        collection = self.refresh_collection()
        tools = ToolFactory(
            collection,
            project_id=project_id,
            parent_store_manager=parent_store,
        ).create_tools()
        graph = create_agent_graph(self.llm, tools)
        self._agent_graph_cache[cache_key] = graph
        return graph

    def clear_agent_graph_cache(self, project_id=None):
        if project_id is None:
            self._agent_graph_cache.clear()
            self.agent_graph = None
            return
        self._agent_graph_cache.pop(project_id, None)

    def invalidate_project_resources(self, project_id=None):
        """Refresh retrieval handles and force a fresh project graph after KB changes."""
        self.refresh_collection()
        self.clear_agent_graph_cache(project_id)

    def get_config(self):
        cfg = {"configurable": {"thread_id": self.thread_id}, "recursion_limit": self.recursion_limit}
        handler = self.observability.get_handler()
        if handler:
            cfg["callbacks"] = [handler]
        return cfg

    def reset_thread(self):
        try:
            if self.agent_graph:
                self.agent_graph.checkpointer.delete_thread(self.thread_id)
        except Exception as e:
            print(f"Warning: Could not delete thread {self.thread_id}: {e}")
        self.thread_id = str(uuid.uuid4())
