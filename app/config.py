from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GROQ_API_KEY: str
    USDA_API_KEY: str
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost/nutriai"
    JWT_SECRET: str = "change-this-to-a-long-random-string-before-deploy"
    
    class Config:
        env_file = ".env"

settings = Settings()