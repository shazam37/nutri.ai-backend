from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GROQ_API_KEY: str
    USDA_API_KEY: str
    DATABASE_URL: str 
    JWT_SECRET: str 
    
    class Config:
        env_file = ".env"

settings = Settings()