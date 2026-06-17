from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "chatbot-api"
    APP_ENV: str = "development"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    DATABASE_URL: str = "postgresql://chatbot:chatbot@localhost:5432/chatbot_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL_SECONDS: int = 3600
    REDIS_CONNECT_TIMEOUT: float = 1.0
    REDIS_SOCKET_TIMEOUT: float = 1.0
    QDRANT_URL: str = "http://localhost:6333"
    JWT_SECRET: str = "change-me"
    LLM_PROVIDER: str = "mock"
    LLM_API_KEY: str = ""

    # Local LLM (Ollama)
    OLLAMA_URL: str = "http://localhost:11434"
    LLM_MODEL_LIGHT: str = "qwen2.5:3b"   # precheck / classify / rewrite
    LLM_MODEL_HEAVY: str = "qwen2.5:7b"   # answer generation
    LLM_TIMEOUT: float = 10.0
    LLM_ROUTER_TIMEOUT: float = 8.0
    LLM_ANSWER_TIMEOUT: float = 30.0
    ROUTER_RISK_OVERRIDE_CONFIDENCE: float = 0.65

    # Web fallback
    WEB_FALLBACK_ENABLED: bool = False
    WEB_FALLBACK_PROVIDER: str = "tavily"
    WEB_FALLBACK_CONFIDENCE_THRESHOLD: float = 0.35
    TAVILY_API_KEY: str = ""
    TAVILY_SEARCH_DEPTH: str = "basic"
    TAVILY_MAX_RESULTS: int = 5
    TAVILY_INCLUDE_RAW_CONTENT: bool = False

    # Qdrant + embedding (RAG retrieval)
    QDRANT_API_KEY: str = ""                       # để trống nếu Qdrant local không bật auth
    QDRANT_CLUSTER_ENDPOINT: str = ""
    QDRANT_COLLECTION: str = "doc_store"            # TÊN COLLECTION CỦA BẠN
    QDRANT_MEMORY_COLLECTION: str = "chat_store"
    QDRANT_VECTOR_NAME: str = ""                   # để trống nếu collection dùng vector mặc định (unnamed)
    QDRANT_PAYLOAD_TEXT: str = "text"              # field payload chứa nội dung văn bản
    QDRANT_PAYLOAD_SOURCE: str = "source"          # field payload chứa nguồn/citation
    EMBEDDING_MODEL: str = "keepitreal/vietnamese-sbert"  # phải KHỚP model build collection
    QDRANT_TIMEOUT: float = 10.0
    DATABASE_CONNECT_TIMEOUT: float = 5.0
    RETRIEVAL_CONTEXT_MAX_TOKENS: int = 2200
    RETRIEVAL_MAX_DOCUMENTS: int = 8
    RETRIEVAL_MIN_RERANK_SCORE: float = -0.2
    KEYWORD_SCROLL_MAX_POINTS: int = 2048
    WORKER_TASKS_ENABLED: bool = True
    SUMMARY_TRIGGER_MESSAGE_COUNT: int = 12
    SUMMARY_RECENT_MESSAGE_LIMIT: int = 40

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
