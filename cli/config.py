"""Configuration management for CLI."""
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class CLIConfig:
    """Configuration for CLI API client."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize CLI configuration.

        Args:
            api_url: Base URL for the API (defaults to http://localhost:8000/api/v1)
            username: HTTP Basic Auth username (optional)
            password: HTTP Basic Auth password (optional)
            timeout: Request timeout in seconds
        """
        self.api_url = api_url or os.getenv("STIFLYT_API_URL", "http://localhost:8000/api/v1")
        self.username = username or os.getenv("STIFLYT_USERNAME")
        self.password = password or os.getenv("STIFLYT_PASSWORD")
        self.timeout = timeout

    def get_auth(self) -> Optional[tuple]:
        """Get HTTP Basic Auth tuple if credentials are available."""
        if self.username and self.password:
            return (self.username, self.password)
        return None

