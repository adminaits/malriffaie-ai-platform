from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "Malriffaie AI Concierge"
    env: str = "development"
    frontend_url: str = "http://localhost:5173"
    supabase_url: str
    supabase_service_role_key: str
    supabase_anon_key: str | None = None
    jwt_secret: str = "change-this-jwt-secret-in-render"
    admin_token_expire_minutes: int = 720
    default_admin_email: str = "admin@aits.cc"
    default_admin_password: str = "Aits123!"
    default_hf_model: str = "mistralai/Mistral-7B-Instruct-v0.3"
    default_embedding_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    tap_secret_key: str | None = None
    email_from: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_pass: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache
def get_settings() -> Settings:
    return Settings()
