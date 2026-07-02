from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str | None = None
    SUPABASE_KEY: str  # Must be the Service Role Key
    SUPABASE_JWT_SECRET: str
    
    # Task 2 vars
    LLM_PROVIDER: str = "gemini" # gemini or anthropic
    GEMINI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    META_WEBHOOK_VERIFY_TOKEN: str | None = "test-token"
    META_API_TOKEN: str | None = None
    RESEND_API_KEY: str | None = None
    RESEND_WEBHOOK_SECRET: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_ADMIN_CHAT_ID: str | None = None
    
    # Redis Queue Config
    REDIS_URL: str = "redis://localhost:6379"
    DATABASE_URL: str | None = None
    
    model_config = SettingsConfigDict(extra="ignore")

settings = Settings()
