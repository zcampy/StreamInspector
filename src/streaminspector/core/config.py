from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from platformdirs import user_config_dir, user_data_dir, user_log_dir

APP_NAME = "StreamInspector"
APP_AUTHOR = "StreamInspector"


class ProxySettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    enabled: bool = False


class UiSettings(BaseModel):
    theme: str = "dark"
    language: str = "es"
    restore_geometry: bool = True


class StorageSettings(BaseModel):
    database_name: str = "sessions.sqlite3"
    save_bodies: bool = True
    max_body_bytes: int = Field(default=10 * 1024 * 1024, ge=0)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STREAMINSPECTOR_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    proxy: ProxySettings = ProxySettings()
    ui: UiSettings = UiSettings()
    storage: StorageSettings = StorageSettings()

    @property
    def config_dir(self) -> Path:
        return Path(user_config_dir(APP_NAME, APP_AUTHOR))

    @property
    def data_dir(self) -> Path:
        return Path(user_data_dir(APP_NAME, APP_AUTHOR))

    @property
    def log_dir(self) -> Path:
        return Path(user_log_dir(APP_NAME, APP_AUTHOR))

    def ensure_directories(self) -> None:
        for directory in (self.config_dir, self.data_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)
