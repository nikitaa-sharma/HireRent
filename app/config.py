"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Runtime settings with sensible local-development defaults."""

    app_name: str = os.getenv("APP_NAME", "Hirent")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/hirelens.db")
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "uploads"))
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
    vector_store_dir: Path = Path(os.getenv("VECTOR_STORE_DIR", "data/vector_store"))
    embedding_model_name: str = os.getenv(
        "EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"
    )
    llm_provider: str = os.getenv("LLM_PROVIDER", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_api_url: str = os.getenv(
        "LLM_API_URL", "https://api.openai.com/v1/chat/completions"
    )


settings = Settings()

APP_NAME = settings.app_name
DATABASE_URL = settings.database_url
UPLOAD_DIR = settings.upload_dir
MAX_UPLOAD_SIZE_MB = settings.max_upload_size_mb
VECTOR_STORE_DIR = settings.vector_store_dir
EMBEDDING_MODEL_NAME = settings.embedding_model_name
LLM_PROVIDER = settings.llm_provider
LLM_API_KEY = settings.llm_api_key
LLM_MODEL = settings.llm_model
LLM_API_URL = settings.llm_api_url
