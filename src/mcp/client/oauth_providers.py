"""
Implementations of OAuthClientProvider for common use cases.
"""

import json
import webbrowser

from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class InMemoryOAuthProvider:
    """
    A simple in-memory OAuth provider for development and testing.

    This provider stores all OAuth data in memory and will lose state
    when the application restarts. For production use, implement a
    persistent storage solution.
    """

    def __init__(
        self,
        redirect_url: str,
        client_metadata: OAuthClientMetadata,
    ):
        self._redirect_url = redirect_url
        self._client_metadata = client_metadata
        self._client_information: OAuthClientInformationFull | None = None
        self._tokens: OAuthToken | None = None
        self._code_verifier: str | None = None

    @property
    def redirect_url(self) -> str:
        """The URL to redirect the user agent to after authorization."""
        return self._redirect_url

    @property
    def client_metadata(self) -> OAuthClientMetadata:
        """Metadata about this OAuth client."""
        return self._client_metadata

    async def client_information(self) -> OAuthClientInformationFull | None:
        """
        Loads information about this OAuth client, as registered already with the
        server, or returns None if the client is not registered with the server.
        """
        return self._client_information

    async def save_client_information(
        self, client_information: OAuthClientInformationFull
    ) -> None:
        """
        Saves client information after dynamic registration.
        """
        self._client_information = client_information

    async def tokens(self) -> OAuthToken | None:
        """
        Loads any existing OAuth tokens for the current session, or returns
        None if there are no saved tokens.
        """
        return self._tokens

    async def save_tokens(self, tokens: OAuthToken) -> None:
        """
        Stores new OAuth tokens for the current session, after a successful
        authorization.
        """
        self._tokens = tokens

    async def redirect_to_authorization(self, authorization_url: str) -> None:
        """
        Opens the authorization URL in the default web browser.
        """
        print(f"Opening authorization URL: {authorization_url}")
        webbrowser.open(authorization_url)

    async def save_code_verifier(self, code_verifier: str) -> None:
        """
        Saves a PKCE code verifier for the current session.
        """
        self._code_verifier = code_verifier

    async def code_verifier(self) -> str:
        """
        Loads the PKCE code verifier for the current session.
        """
        if self._code_verifier is None:
            raise ValueError("No code verifier available")
        return self._code_verifier


class FileBasedOAuthProvider(InMemoryOAuthProvider):
    """
    OAuth provider that persists tokens and client information to files.

    This is suitable for development and simple applications where
    file-based persistence is acceptable.
    """

    def __init__(
        self,
        redirect_url: str,
        client_metadata: OAuthClientMetadata,
        tokens_file: str = "oauth_tokens.json",
        client_info_file: str = "oauth_client_info.json",
    ):
        super().__init__(redirect_url, client_metadata)
        self._tokens_file = tokens_file
        self._client_info_file = client_info_file

        # Load existing data on initialization
        self._load_client_information()
        self._load_tokens()

    def _load_tokens(self) -> None:
        """Load tokens from file if it exists."""
        try:
            with open(self._tokens_file) as f:
                data = json.load(f)
                self._tokens = OAuthToken.model_validate(data)
        except (FileNotFoundError, json.JSONDecodeError):
            self._tokens = None

    def _save_tokens_to_file(self) -> None:
        """Save tokens to file."""
        if self._tokens:
            with open(self._tokens_file, "w") as f:
                json.dump(self._tokens.model_dump(), f, indent=2)

    def _load_client_information(self) -> None:
        """Load client information from file if it exists."""
        try:
            with open(self._client_info_file) as f:
                data = json.load(f)
                self._client_information = OAuthClientInformationFull.model_validate(
                    data
                )
        except (FileNotFoundError, json.JSONDecodeError):
            self._client_information = None

    def _save_client_information_to_file(self) -> None:
        """Save client information to file."""
        if self._client_information:
            with open(self._client_info_file, "w") as f:
                json.dump(self._client_information.model_dump(), f, indent=2)

    async def save_tokens(self, tokens: OAuthToken) -> None:
        """
        Stores new OAuth tokens and saves them to file.
        """
        await super().save_tokens(tokens)
        self._save_tokens_to_file()

    async def save_client_information(
        self, client_information: OAuthClientInformationFull
    ) -> None:
        """
        Saves client information and saves it to file.
        """
        await super().save_client_information(client_information)
        self._save_client_information_to_file()
