from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    search_embedding_provider: Literal["local", "openai"] = "local"
    dikson_data_dir: Path = Path("data")
    git_repositories_dir: Path = Path("repositories")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
settings.dikson_data_dir.mkdir(parents=True, exist_ok=True)
