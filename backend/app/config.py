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
    openai_tts_model: str = Field(default="tts-1", alias="OPENAI_TTS_MODEL")
    openai_tts_voice: str = Field(default="nova", alias="OPENAI_TTS_VOICE")

    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")
    rag_similarity_threshold: float = Field(default=0.3, alias="RAG_SIMILARITY_THRESHOLD")

    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    portal_jwt_secret: str = Field(default="replace_me", alias="PORTAL_JWT_SECRET")
    portal_jwt_algorithm: str = Field(default="HS256", alias="PORTAL_JWT_ALGORITHM")

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")

    external_link_secret: str = Field(default="replace_me", alias="EXTERNAL_LINK_SECRET")
    session_signing_secret: str = Field(default="replace_me", alias="SESSION_SIGNING_SECRET")

    # --- amoCRM ---
    amocrm_subdomain: str = Field(default="azamatrasuli", alias="AMOCRM_SUBDOMAIN")
    amocrm_client_id: str = Field(default="", alias="AMOCRM_CLIENT_ID")
    amocrm_client_secret: str = Field(default="", alias="AMOCRM_CLIENT_SECRET")
    amocrm_redirect_uri: str = Field(default="http://localhost:8009/api/v1/amocrm/oauth/callback", alias="AMOCRM_REDIRECT_URI")
    amocrm_sales_pipeline_id: int = Field(default=10689842, alias="AMOCRM_SALES_PIPELINE_ID")
    amocrm_service_pipeline_id: int = Field(default=10689990, alias="AMOCRM_SERVICE_PIPELINE_ID")
    amocrm_telegram_id_field: int = Field(default=1404988, alias="AMOCRM_TELEGRAM_ID_FIELD")
    amocrm_product_field: int = Field(default=1404990, alias="AMOCRM_PRODUCT_FIELD")
    amocrm_amount_field: int = Field(default=1404992, alias="AMOCRM_AMOUNT_FIELD")

    # --- amoCRM Chat API (imBox) ---
    amocrm_chat_channel_id: str = Field(default="", alias="AMOCRM_CHAT_CHANNEL_ID")
    amocrm_chat_secret_key: str = Field(default="", alias="AMOCRM_CHAT_SECRET_KEY")

    # --- DMS API ---
    dms_base_url: str | None = Field(default=None, alias="DMS_BASE_URL")
    dms_username: str | None = Field(default=None, alias="DMS_USERNAME")
    dms_password: str | None = Field(default=None, alias="DMS_PASSWORD")

    # --- Frontend ---
    frontend_url: str = Field(default="https://edplam-eurika.vercel.app", alias="FRONTEND_URL")

    # --- Escalation ---
    manager_telegram_chat_id: str = Field(default="", alias="MANAGER_TELEGRAM_CHAT_ID")

    # --- Dashboard ---
    dashboard_api_key: str = Field(default="", alias="DASHBOARD_API_KEY")

    # --- Conversational Memory ---
    memory_enabled: bool = Field(default=True, alias="MEMORY_ENABLED")
    memory_idle_minutes: int = Field(default=5, alias="MEMORY_IDLE_MINUTES")
    memory_min_messages: int = Field(default=3, alias="MEMORY_MIN_MESSAGES")
    memory_max_context_tokens: int = Field(default=800, alias="MEMORY_MAX_CONTEXT_TOKENS")
    memory_summary_top_k: int = Field(default=3, alias="MEMORY_SUMMARY_TOP_K")
    memory_atoms_top_k: int = Field(default=5, alias="MEMORY_ATOMS_TOP_K")
    memory_summary_threshold: float = Field(default=0.4, alias="MEMORY_SUMMARY_THRESHOLD")
    memory_atom_threshold: float = Field(default=0.35, alias="MEMORY_ATOM_THRESHOLD")
    memory_recency_halflife_days: int = Field(default=30, alias="MEMORY_RECENCY_HALFLIFE_DAYS")
    memory_cross_role_types: str = Field(default="preference,entity,decision", alias="MEMORY_CROSS_ROLE_TYPES")

    # --- History & Running Summary ---
    history_max_context_tokens: int = Field(default=100_000, alias="HISTORY_MAX_CONTEXT_TOKENS")
    conversation_summary_threshold: int = Field(default=30, alias="CONVERSATION_SUMMARY_THRESHOLD")
    conversation_summary_keep_recent: int = Field(default=20, alias="CONVERSATION_SUMMARY_KEEP_RECENT")

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
