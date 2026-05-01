from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GROQ_API_KEY: str
    USDA_API_KEY: str
    DATABASE_URL: str 
    JWT_SECRET: str 
    ADMIN_EMAILS: str = ""
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY:    str = ""
    CLOUDINARY_API_SECRET: str = ""
    
    class Config:
        env_file = ".env"

settings = Settings()
