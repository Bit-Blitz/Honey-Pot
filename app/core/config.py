import os
import sys
from typing import Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# 1. Force load the .env file
load_dotenv()

class Settings(BaseSettings):
    PROJECT_NAME: str = "Agentic Honey-Pot"
    GOOGLE_API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY")
    API_KEY: str = os.getenv("API_KEY", "helware-secret-key-2024")
    DATABASE_PATH: str = os.path.join("data", "honey.db")

    def validate_keys(self):
        if not self.GOOGLE_API_KEY:
            print("WARNING: GOOGLE_API_KEY not found. LLM features will fail.")
            # We don't exit(1) here to allow the app to start for non-LLM endpoints

settings = Settings()
settings.validate_keys()