from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir, user_data_dir, user_log_dir
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "StreamInspector"
APP_AUTHOR = "StreamInspector"


class UiSettings(BaseModel):
    theme: str = "dark"
    language: str = "es"
    restore_geometry: bool = True


class StorageSettings(BaseModel):
    database_name: str = "sessions.sqlite3"
    save_bodies: bool = True
    max_body_bytes: int = Field(default=10 * 1024 * 1024, ge=0)


class AppSettings(BaseSettings):
    """Configuración persistente de la aplicación.

    NOTA: el host y el puerto del proxy NO viven aquí. Se guardan en `QSettings`
    desde `gui/proxy_window.py` y llegan al motor de proxy mediante
    `ProxyStartRequested(host, port)`. Mantener una sola fuente de verdad evita
    el bug clásico de "configuro por env var y la UI la ignora" o viceversa.
    Las variables de entorno `STREAMINSPECTOR_PROXY__HOST` y
    `STREAMINSPECTOR_PROXY__PORT` ya no se consultan; usa el menú Proxy.
    """

    model_config = SettingsConfigDict(
        env_prefix="STREAMINSPECTOR_",
        env_nested_delimiter="__",
        extra="ignore",
    )

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
