import os
import sys
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# 1. Force load the .env file
load_dotenv()

class Settings(BaseSettings):
    PROJECT_NAME: str = "Agentic Honey-Pot"
    # 2. Pydantic will now find this in the loaded environment
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY")
    DATABASE_PATH: str = os.path.join("data", "honey.db")

    def validate_keys(self):
        if not self.GOOGLE_API_KEY:
            print("CRITICAL ERROR: GOOGLE_API_KEY not found.")
            print("Make sure you have a .env file with GOOGLE_API_KEY=AIzaSy...")
            sys.exit(1)

settings = Settings()
settings.validate_keys()