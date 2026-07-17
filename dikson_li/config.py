from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    openai_api_key: str
    openai_model: str = "gpt-5.2"
    data_dir: str = "data"

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        return cls(
            openai_api_key=api_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.2").strip() or "gpt-5.2",
            data_dir=os.getenv("DIKSON_DATA_DIR", "data").strip() or "data",
        )
