from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError


class AuthorizationManager:
    """
    Manages token generation, validation, and error handling for authorization
    in the MCP Python SDK.

    """

    def __init__(self, secret_key: str, issuer: str, audience: str) -> None:
        """
        Initializes the AuthorizationManager with the required configurations.
        """
        self.secret_key = secret_key
        self.issuer = issuer
        self.audience = audience

    def generate_token(self, payload: dict[str, Any], expires_in: int = 3600) -> str:
        """
        Generates a JWT token with the given payload.
        """
        expiration = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        payload.update({
            "exp": expiration,
            "iss": self.issuer,
            "aud": self.audience  # Use audience as a single string consistently
        })

        try:
            token = jwt.encode(payload, self.secret_key, algorithm="HS256")
            return token
        except JWTError as e:
            raise ValueError(f"Token generation failed: {e}")

    def validate_token(self, token: str) -> dict[str, Any] | None:
        """
        Validates the given JWT token and returns the claims if valid.
        """
        try:
            # Decode with strict audience and issuer checks
            decoded_token = jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"verify_signature": True}
            )
            if decoded_token.get("aud") != self.audience:
                print("Invalid audience.")
                return None
            if decoded_token.get("iss") != self.issuer:
                print("Invalid issuer.")
                return None
            return decoded_token
        except ExpiredSignatureError:
            print("Token has expired.")
            return None
        except JWTClaimsError as e:
            print(f"Invalid claims: {e}")
            return None
        except JWTError as e:
            print(f"Invalid token: {e}")
            return None

    def get_claim(self, token: str, claim_key: str) -> Any:
        """
        Extracts a specific claim from the validated token.
        """
        claims = self.validate_token(token)
        return claims.get(claim_key) if claims else None

