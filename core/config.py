from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Centralized application settings.
    Pydantic will automatically read environment variables or from a .env file.
    """
    # Database
    DATABASE_URL: str

    # Azure OpenAI
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_DEPLOYMENT_NAME: str
    OPENAI_API_VERSION: str
    
    # Tavily Search
    TAVILY_API_KEY: str

    # Google OAuth
    GCP_OAUTH_CLIENT_ID: str
    GCP_OAUTH_CLIENT_SECRET: str
    ENCRYPTION_KEY: str
    AUTHORIZED_USERS: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

settings = Settings() 