from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    dikson_data_dir: Path = Path("data")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
settings.dikson_data_dir.mkdir(parents=True, exist_ok=True)
