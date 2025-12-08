"""
Configuration settings for the DUBU journaling automation.
"""
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        """Initialize settings from environment variables."""
        # Logging configuration
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        self.log_file: str = os.getenv("LOG_FILE", "dubu_journaling.log")

        # Microsoft Graph API configuration
        self.client_id: str = os.getenv("CLIENT_ID", "")
        self.tenant_id: str = os.getenv("TENANT_ID", "")
        self.username: str = os.getenv("EMAIL_USERNAME")
        self.password: str = os.getenv("EMAIL_PASSWORD", "")
        self.scope: str = os.getenv("GRAPH_SCOPE", "https://graph.microsoft.com/.default")

        # Database/Tracking credentials (loaded via Credential.get_credential)
        self.tracking_credential_name: str = "Odense SQL Server"
        self.user_credential_name: str = "RoboA"

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary (excluding sensitive data)."""
        return {
            "log_level": self.log_level,
            "log_file": self.log_file,
            "client_id": self.client_id,
            "tenant_id": self.tenant_id,
            "username": self.username,
            "scope": self.scope,
        }


# Global settings instance
settings = Settings()
