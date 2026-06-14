from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str
    cohere_api_key: str = ""
    langsmith_api_key: str = ""
    github_token: str = ""

    # S3 — used for tenant-uploaded PDF / Markdown files
    s3_bucket: str = "kapa-rag-uploads"
    s3_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    qdrant_url: str = "http://localhost:6333"
    redis_url: str = "redis://localhost:6379"
    postgres_url: str = "postgresql+asyncpg://kapa:kapa_dev_password@localhost:5432/kapa_rag"

    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536

    llm_default_model: str = "gpt-4o"
    llm_fast_model: str = "gpt-4o-mini"
    llm_fast_token_threshold: int = 500

    llm_provider: str = "openai"
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free"

    top_k_retrieval: int = 20
    top_n_rerank: int = 5
    max_context_tokens: int = 6000
    cache_ttl_seconds: int = 3600
    rate_limit_per_minute: int = 20

    service_port: int = 8000

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 30

    # Observability
    environment: str = "dev"
    cloudwatch_log_group: str = "/kapa-rag/production"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
