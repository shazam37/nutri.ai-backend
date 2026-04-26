from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GROQ_API_KEY: str
    USDA_API_KEY: str
    DATABASE_URL: str = "postgresql+asyncpg://nutriai@127.0.0.1:5432/nutriai"
    JWT_SECRET: str 
    
    class Config:
        env_file = ".env"

settings = Settings()