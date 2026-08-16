"""Shared configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # App
    app_name: str = "ecs-rebuild"
    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    default_user_id: str = "1"

    # LLM (DashScope / OpenAI-compatible)
    api_key: str = Field(default="", validation_alias="API_KEY")
    llm_model: str = "qwen-plus"
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    coder_model: str = "qwen3-coder-plus"

    # MySQL
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "ecs"
    db_user: str = "root"
    db_password: str = ""

    # Neo4j
    neo4j_url: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Embeddings (OpenAI-compatible HTTP or DashScope)
    embed_base_url: str = "http://127.0.0.1:10010/v1"
    embed_model: str = "bge-base-zh-v1.5"
    embed_api_key: str = "EMPTY"

    # Checkpoint / session
    checkpoint_backend: str = "memory"  # memory | sqlite | postgres
    checkpoint_sqlite_path: str = ".checkpoints/langgraph.db"
    checkpoint_postgres_uri: str = ""

    # Knowledge
    knowledge_enabled: bool = True
    knowledge_top_k: int = 10

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
