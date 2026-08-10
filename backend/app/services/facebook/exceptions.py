"""Facebook integration domain errors."""


class FacebookIntegrationError(Exception):
    """Base error for expected Facebook integration failures."""


class FacebookConfigurationError(FacebookIntegrationError):
    """Raised when required Facebook configuration is missing."""


class FacebookOAuthStateError(FacebookIntegrationError):
    """Raised when an OAuth state is invalid, expired, or already used."""


class FacebookApiError(FacebookIntegrationError):
    """Raised when Graph API returns an error response."""


class FacebookPermissionError(FacebookApiError):
    """Raised when Facebook denies a request because permissions are insufficient."""


class FacebookTokenError(FacebookApiError):
    """Raised when a token is invalid, expired, or revoked."""


class FacebookPageUnavailableError(FacebookIntegrationError):
    """Raised when a page is not available to the authenticated user."""
