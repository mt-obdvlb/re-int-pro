from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Commands run from the repository root. Resolve data independently of whether
# Python imports this package from a source checkout or an installed wheel.
ROOT = Path.cwd().resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    llm_mode: Literal["fake", "bailian"] = "fake"
    bailian_api: SecretStr = SecretStr("")
    bailian_base_url: Literal["https://dashscope.aliyuncs.com/compatible-mode/v1"] = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    bailian_model: Literal["qwen-plus-2025-12-01"] = "qwen-plus-2025-12-01"
    probeops_snapshot_dir: Path = ROOT / "data/snapshots"
    # A lower operator cap is separate from the immutable 450 CNY admission cap.
    probeops_spend_cap_micro_cny: int = Field(default=1000000, ge=1, le=450000000)
    otlp_endpoint: Literal["", "http://127.0.0.1:4318/v1/traces"] = ""
    probeops_db_path: Path = ROOT / ".runtime/probeops.sqlite3"
    probeops_telemetry_dir: Path = ROOT / ".runtime/telemetry"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    fake_delay_seconds: float = Field(default=0.8, ge=0, le=5)


def settings() -> Settings:
    try:
        return Settings()
    except ValueError:
        raise SystemExit("配置无效。检查服务端配置类型和供应商白名单。") from None
