from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    PROJECT_NAME: str = "Talento Up"
    BUSINESS_NAME: str = "DUARUS E.A.S"
    BUSINESS_RUC: str = "80170151-1"
    API_V1_STR: str = "/api/v1"
    
    # URL Base para links en correos (Importante para tareas en background)
    BASE_URL: str = "http://localhost:8006"
    
    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "sectoruno_db"
    POSTGRES_PORT: int = 5432 

    # Security
    SECRET_KEY: str = "super_secret_key_change_in_production_999"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # --- EMAIL SETTINGS ---
    SMTP_ENABLED: bool = False # Si es False, solo loguea en consola (Mock)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAILS_FROM_EMAIL: str = "talento@sectoruno.com.py"
    EMAILS_FROM_NAME: str = "Talento Humano UP"
    SMTP_TLS: bool = True

    GEMINI_API_KEY: Optional[str] = None

    # --- SUPERADMIN SETTINGS ---
    SUPERADMIN_EMAIL: str = "superadmin@example.com"
    SUPERADMIN_PASSWORD: str = "superpassword"

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def BASE_DOMAIN(self) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(self.BASE_URL)
        return parsed.hostname or "localhost"

    @property
    def BASE_SCHEME(self) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(self.BASE_URL)
        return parsed.scheme or "http"

    def get_tenant_url(self, subdomain: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(self.BASE_URL)
        if parsed.hostname == "localhost":
            return f"{parsed.scheme}://{subdomain}.localhost:{parsed.port}" if parsed.port else f"{parsed.scheme}://{subdomain}.localhost"
        return f"{parsed.scheme}://{subdomain}.{parsed.hostname}:{parsed.port}" if parsed.port else f"{parsed.scheme}://{subdomain}.{parsed.hostname}"

settings = Settings()