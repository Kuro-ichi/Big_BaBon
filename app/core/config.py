from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "chatbot-api"
    APP_ENV: str = "development"
    DATABASE_URL: str = "postgresql://chatbot:chatbot@localhost:5432/chatbot_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    JWT_SECRET: str = "change-me"
    LLM_PROVIDER: str = "mock"
    LLM_API_KEY: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
