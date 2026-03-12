from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8009, alias="APP_PORT")
    app_cors_origins: str = Field(default="http://localhost:5177", alias="APP_CORS_ORIGINS")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL")
    openai_request_timeout_seconds: int = Field(default=40, alias="OPENAI_REQUEST_TIMEOUT_SECONDS")

    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")
    rag_similarity_threshold: float = Field(default=0.3, alias="RAG_SIMILARITY_THRESHOLD")

    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    portal_jwt_secret: str = Field(default="replace_me", alias="PORTAL_JWT_SECRET")
    portal_jwt_algorithm: str = Field(default="HS256", alias="PORTAL_JWT_ALGORITHM")

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")

    external_link_secret: str = Field(default="replace_me", alias="EXTERNAL_LINK_SECRET")
    session_signing_secret: str = Field(default="replace_me", alias="SESSION_SIGNING_SECRET")

    # --- amoCRM ---
    amocrm_subdomain: str = Field(default="azaprimemat", alias="AMOCRM_SUBDOMAIN")
    amocrm_client_id: str = Field(default="", alias="AMOCRM_CLIENT_ID")
    amocrm_client_secret: str = Field(default="", alias="AMOCRM_CLIENT_SECRET")
    amocrm_redirect_uri: str = Field(default="http://localhost:8009/api/v1/amocrm/oauth/callback", alias="AMOCRM_REDIRECT_URI")
    amocrm_sales_pipeline_id: int = Field(default=10490514, alias="AMOCRM_SALES_PIPELINE_ID")
    amocrm_service_pipeline_id: int = Field(default=10490518, alias="AMOCRM_SERVICE_PIPELINE_ID")
    amocrm_telegram_id_field: int = Field(default=1396311, alias="AMOCRM_TELEGRAM_ID_FIELD")
    amocrm_product_field: int = Field(default=1396313, alias="AMOCRM_PRODUCT_FIELD")
    amocrm_amount_field: int = Field(default=1396315, alias="AMOCRM_AMOUNT_FIELD")

    # --- amoCRM Chat API (imBox) ---
    amocrm_chat_channel_id: str = Field(default="", alias="AMOCRM_CHAT_CHANNEL_ID")
    amocrm_chat_secret_key: str = Field(default="", alias="AMOCRM_CHAT_SECRET_KEY")

    # --- DMS API ---
    dms_base_url: str | None = Field(default=None, alias="DMS_BASE_URL")
    dms_username: str | None = Field(default=None, alias="DMS_USERNAME")
    dms_password: str | None = Field(default=None, alias="DMS_PASSWORD")

    # --- Escalation ---
    manager_telegram_chat_id: str = Field(default="", alias="MANAGER_TELEGRAM_CHAT_ID")

    @property
    def cors_origins(self) -> list[str]:
        return [x.strip() for x in self.app_cors_origins.split(",") if x.strip()]

    @property
    def amocrm_base_url(self) -> str:
        return f"https://{self.amocrm_subdomain}.amocrm.ru/api/v4"

    @property
    def amocrm_configured(self) -> bool:
        return bool(self.amocrm_client_id and self.amocrm_client_secret)

    @property
    def amocrm_chat_configured(self) -> bool:
        return bool(self.amocrm_chat_channel_id and self.amocrm_chat_secret_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
