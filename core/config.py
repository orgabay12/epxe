from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Loads and validates all environment variables."""
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_ENDPOINT: str
    OPENAI_API_VERSION: str
    AZURE_OPENAI_DEPLOYMENT_NAME: str
    TAVILY_API_KEY: str
    DATABASE_URL: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Create a single, global instance of the settings
# This will raise a validation error if any variables are missing
settings = Settings() 