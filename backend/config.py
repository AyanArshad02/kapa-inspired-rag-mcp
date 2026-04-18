from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str
    cohere_api_key: str = ""
    langsmith_api_key: str = ""

    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379"
    postgres_url: str = "postgresql+asyncpg://kapa:kapa_dev_password@localhost:5432/kapa_rag"

    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536

    llm_default_model: str = "gpt-4o"
    llm_fast_model: str = "gpt-4o-mini"
    llm_fast_token_threshold: int = 500

    top_k_retrieval: int = 20
    top_n_rerank: int = 5
    max_context_tokens: int = 6000
    cache_ttl_seconds: int = 3600

    service_port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
