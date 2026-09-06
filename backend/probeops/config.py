from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    llm_mode: Literal["fake"] = "fake"
    bailian_api: SecretStr = SecretStr("")
    probeops_db_path: Path = ROOT / ".runtime/probeops.sqlite3"
    probeops_telemetry_dir: Path = ROOT / ".runtime/telemetry"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    fake_delay_seconds: float = Field(default=0.8, ge=0, le=5)


def settings() -> Settings:
    try:
        return Settings()
    except ValueError:
        raise SystemExit("配置无效。P1 仅支持 LLM_MODE=fake；检查配置类型。") from None
