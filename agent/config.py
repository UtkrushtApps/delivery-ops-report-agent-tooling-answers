"""Configuration loaded from environment with safe defaults."""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").strip() in ("1", "true", "True")


class Config:
    AGENT_TEST_MODE: bool = _bool("AGENT_TEST_MODE", False)
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "gpt-4o-mini")
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://delivery_app:delivery_pass@127.0.0.1:5432/delivery_ops",
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    REPORT_CACHE_TTL_SECONDS: int = int(os.getenv("REPORT_CACHE_TTL_SECONDS", "300"))
    # Schema version stamped into cache payloads; bump to invalidate old entries.
    CACHE_SCHEMA_VERSION: int = 2
    ALLOWED_REPORT_TYPES = ("account_summary",)


config = Config()

