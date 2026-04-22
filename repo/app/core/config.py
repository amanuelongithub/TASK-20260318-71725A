from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Medical Ops Middle Platform API"
    environment: str = "dev"
    secret_key: str = "INSECURE-DEV-SECRET-CHANGE-ME"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/medical_ops"
    redis_url: str = "redis://localhost:6379/0"
    offline_mode: bool = True
    use_redis_login_tracking: bool = False
    file_storage_path: str = "./storage"
    max_file_size_mb: int = 20
    aes_key: str = "INSECURE-DEV-AES-KEY-CHANGE-ME--" # Must be 32 bytes if used for AES-256
    allow_plain_http: bool = False # ENFORCED: Compliance requires HTTPS-only transmission.


settings = Settings()
