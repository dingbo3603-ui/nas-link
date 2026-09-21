from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    token: str = Field(default="development-token", alias="NAS_LINK_TOKEN")
    data_root: Path = Field(default=Path("./data"), alias="NAS_LINK_DATA_ROOT")
    clipboard_ttl_minutes: int = Field(default=60, alias="NAS_LINK_CLIPBOARD_TTL_MINUTES")
    auto_organize: bool = Field(default=True, alias="NAS_LINK_AUTO_ORGANIZE")
    deepseek_content_mode: str = Field(default="snippet", alias="NAS_LINK_DEEPSEEK_CONTENT_MODE")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_classify_model: str = Field(default="deepseek-flash", alias="DEEPSEEK_CLASSIFY_MODEL")
    deepseek_answer_model: str = Field(default="deepseek-v4-pro", alias="DEEPSEEK_ANSWER_MODEL")

    @property
    def db_path(self) -> Path:
        return self.data_root / "index" / "nas-link.sqlite3"

    def ensure_directories(self) -> None:
        for relative in (
            "index",
            "inbox",
            "dropbox",
            "review/duplicates",
            "library",
            "transfers",
            "backups/blobs",
            "backups/manifests",
            "logs",
        ):
            (self.data_root / relative).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
