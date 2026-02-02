import os
import sys
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Agentic Honey-Pot"
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY")
    DATABASE_PATH: str = os.path.join("data", "honey.db")

    def validate_keys(self):
        if not self.GOOGLE_API_KEY:
            print("CRITICAL: GOOGLE_API_KEY is missing in .env file.")
            sys.exit(1)

settings = Settings()
settings.validate_keys()