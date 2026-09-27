from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "sqlite:///./arena.db"
    llm_model: str = "openrouter/qwen/qwen3.8-27b:free"
    llm_fallbacks: str = "openrouter/nvidia/nemotron-3-super-120b-a12b:free,openrouter/google/gemma-4-31b-it:free"
    llm_api_key: str = ""
    llm_api_base: str | None = None
    llm_timeout: float = 60.0
    offline_mode: bool = False
    incomplete_session_min_turns: int = 3
    admin_token: str = ""


settings = Settings()
