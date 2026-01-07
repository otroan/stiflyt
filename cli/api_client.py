"""API client for route segments endpoint."""
import requests
from typing import Optional, Dict, Any, List
from .config import CLIConfig


class APIError(Exception):
    """Base exception for API errors."""
    pass


class ConnectionError(APIError):
    """Raised when connection to API fails."""
    pass


class AuthenticationError(APIError):
    """Raised when authentication fails."""
    pass


class APIResponseError(APIError):
    """Raised when API returns an error response."""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[Dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class RouteSegmentsClient:
    """Client for querying route segments from the API."""

    def __init__(self, config: CLIConfig):
        """
        Initialize API client.

        Args:
            config: CLIConfig instance with API settings
        """
        self.config = config
        self.base_url = config.api_url.rstrip('/')

    def get_segments(
        self,
        rutenummer_prefix: Optional[str] = None,
        vedlikeholdsansvarlig: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = False
    ) -> Dict[str, Any]:
        """
        Query route segments from the API.

        Args:
            rutenummer_prefix: Filter by route number prefix (e.g., "bre")
            vedlikeholdsansvarlig: Filter by organization (e.g., "DNT Oslo")
            limit: Maximum number of results (default: 100, max: 1000)
            offset: Pagination offset (default: 0)
            include_geometry: Include GeoJSON geometry in response (default: False)

        Returns:
            Dictionary with segments, total, limit, and offset

        Raises:
            ConnectionError: If connection to API fails
            AuthenticationError: If authentication fails
            APIResponseError: If API returns an error
        """
        # Validate that at least one filter is provided
        if not rutenummer_prefix and not vedlikeholdsansvarlig:
            raise ValueError("At least one filter must be provided: rutenummer_prefix or vedlikeholdsansvarlig")

        # Build query parameters
        params = {
            "limit": min(limit, 1000),  # Enforce max limit
            "offset": max(offset, 0),  # Enforce min offset
            "include_geometry": include_geometry
        }

        if rutenummer_prefix:
            params["rutenummer_prefix"] = rutenummer_prefix
        if vedlikeholdsansvarlig:
            params["vedlikeholdsansvarlig"] = vedlikeholdsansvarlig

        # Build full URL
        url = f"{self.base_url}/routes/segments"

        # Prepare request
        auth = self.config.get_auth()
        headers = {
            "Accept": "application/json"
        }

        try:
            response = requests.get(
                url,
                params=params,
                auth=auth,
                headers=headers,
                timeout=self.config.timeout
            )

            # Handle HTTP errors
            if response.status_code == 401:
                raise AuthenticationError("Authentication failed. Check your credentials.")
            elif response.status_code == 400:
                error_detail = response.json().get("detail", "Bad request")
                raise APIResponseError(f"Bad request: {error_detail}", status_code=400)
            elif response.status_code == 404:
                raise APIResponseError("Endpoint not found. Check API URL.", status_code=404)
            elif response.status_code >= 500:
                error_detail = response.json().get("detail", "Server error")
                raise APIResponseError(f"Server error: {error_detail}", status_code=response.status_code)
            elif not response.ok:
                raise APIResponseError(
                    f"API returned status {response.status_code}",
                    status_code=response.status_code
                )

            # Parse JSON response
            try:
                return response.json()
            except ValueError as e:
                raise APIResponseError(f"Invalid JSON response: {e}")

        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Could not connect to API at {self.base_url}: {e}")
        except requests.exceptions.Timeout as e:
            raise ConnectionError(f"Request to API timed out: {e}")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Request failed: {e}")

