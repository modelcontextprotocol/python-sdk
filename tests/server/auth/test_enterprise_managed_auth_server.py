"""Tests for Enterprise Managed Authorization server-side implementation."""

import time
from unittest.mock import patch

import jwt
import pytest

from src.mcp.server.auth.extensions.enterprise_managed_auth import (
    IDJAGClaims,
    IDJAGValidator,
    JWTValidationConfig,
    ReplayPreventionStore,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def jwt_validation_config():
    """Create a basic JWT validation config."""
    return JWTValidationConfig(
        trusted_idp_issuers=["https://idp.example.com"],
        server_auth_issuer="https://auth.mcp-server.example/",
        server_resource_id="https://mcp-server.example/",
        replay_prevention_enabled=True,
    )


@pytest.fixture
def valid_id_jag_claims():
    """Create valid ID-JAG claims."""
    return {
        "jti": "unique-jwt-id-12345",
        "iss": "https://idp.example.com",
        "sub": "user123",
        "aud": "https://auth.mcp-server.example/",
        "resource": "https://mcp-server.example/",
        "client_id": "mcp-client-app",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "scope": "read write",
        "email": "user@example.com",
    }


@pytest.fixture
def create_id_jag(valid_id_jag_claims):
    """Factory to create ID-JAG tokens."""
    def _create(claims=None, secret="test-secret"):
        claims_data = valid_id_jag_claims.copy()
        if claims:
            claims_data.update(claims)
        return jwt.encode(
            claims_data,
            secret,
            algorithm="HS256",
            headers={"typ": "oauth-id-jag+jwt"},
        )
    return _create


# ============================================================================
# Tests for ReplayPreventionStore
# ============================================================================


def test_replay_prevention_store_mark_and_check():
    """Test marking JTI as used and checking."""
    store = ReplayPreventionStore(ttl=3600)

    jti = "test-jti-123"

    # Initially not used
    assert not store.is_used(jti)

    # Mark as used
    store.mark_used(jti)

    # Now should be used
    assert store.is_used(jti)


def test_replay_prevention_store_cleanup():
    """Test that expired JTIs are cleaned up."""
    store = ReplayPreventionStore(ttl=1)  # 1 second TTL

    jti1 = "test-jti-1"
    jti2 = "test-jti-2"

    # Mark first JTI
    store.mark_used(jti1)
    assert store.is_used(jti1)

    # Wait for expiry
    time.sleep(1.1)

    # Mark second JTI (triggers cleanup)
    store.mark_used(jti2)

    # First JTI should be cleaned up
    assert not store.is_used(jti1)

    # Second JTI should still be there
    assert store.is_used(jti2)


def test_replay_prevention_store_multiple_jtis():
    """Test storing multiple JTIs."""
    store = ReplayPreventionStore(ttl=3600)

    jtis = [f"jti-{i}" for i in range(10)]

    for jti in jtis:
        store.mark_used(jti)

    for jti in jtis:
        assert store.is_used(jti)


# ============================================================================
# Tests for JWTValidationConfig
# ============================================================================


def test_jwt_validation_config_defaults():
    """Test JWT validation config with default values."""
    config = JWTValidationConfig(
        trusted_idp_issuers=["https://idp.example.com"],
        server_auth_issuer="https://auth.server.example/",
        server_resource_id="https://server.example/",
    )

    assert config.jwks_uri is None
    assert config.jwks_cache_ttl == 3600
    assert config.allowed_algorithms == ["RS256", "ES256"]
    assert config.replay_prevention_enabled is True
    assert config.replay_cache_ttl == 3600
    assert config.clock_skew_seconds == 60


def test_jwt_validation_config_custom_values():
    """Test JWT validation config with custom values."""
    config = JWTValidationConfig(
        trusted_idp_issuers=["https://idp1.example.com", "https://idp2.example.com"],
        server_auth_issuer="https://auth.server.example/",
        server_resource_id="https://server.example/",
        jwks_uri="https://idp.example.com/.well-known/jwks.json",
        jwks_cache_ttl=7200,
        allowed_algorithms=["RS256"],
        replay_prevention_enabled=False,
        replay_cache_ttl=1800,
        clock_skew_seconds=120,
    )

    assert len(config.trusted_idp_issuers) == 2
    assert config.jwks_uri == "https://idp.example.com/.well-known/jwks.json"
    assert config.jwks_cache_ttl == 7200
    assert config.allowed_algorithms == ["RS256"]
    assert config.replay_prevention_enabled is False
    assert config.replay_cache_ttl == 1800
    assert config.clock_skew_seconds == 120


# ============================================================================
# Tests for IDJAGClaims
# ============================================================================


def test_id_jag_claims_required_fields(valid_id_jag_claims):
    """Test IDJAGClaims with all required fields."""
    claims = IDJAGClaims.model_validate({**valid_id_jag_claims, "typ": "oauth-id-jag+jwt"})

    assert claims.typ == "oauth-id-jag+jwt"
    assert claims.jti == "unique-jwt-id-12345"
    assert claims.iss == "https://idp.example.com"
    assert claims.sub == "user123"
    assert claims.aud == "https://auth.mcp-server.example/"
    assert claims.resource == "https://mcp-server.example/"
    assert claims.client_id == "mcp-client-app"
    assert claims.scope == "read write"
    assert claims.email == "user@example.com"


def test_id_jag_claims_optional_fields():
    """Test IDJAGClaims without optional fields."""
    claims_data = {
        "typ": "oauth-id-jag+jwt",
        "jti": "jti123",
        "iss": "https://idp.example.com",
        "sub": "user123",
        "aud": "https://auth.server.example/",
        "resource": "https://server.example/",
        "client_id": "client123",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
    }

    claims = IDJAGClaims.model_validate(claims_data)
    assert claims.scope is None
    assert claims.email is None


def test_id_jag_claims_extra_fields():
    """Test that IDJAGClaims allows extra fields."""
    claims_data = {
        "typ": "oauth-id-jag+jwt",
        "jti": "jti123",
        "iss": "https://idp.example.com",
        "sub": "user123",
        "aud": "https://auth.server.example/",
        "resource": "https://server.example/",
        "client_id": "client123",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "custom_field": "custom_value",
        "another_field": 123,
    }

    claims = IDJAGClaims.model_validate(claims_data)
    assert claims.model_extra.get("custom_field") == "custom_value"
    assert claims.model_extra.get("another_field") == 123


# ============================================================================
# Tests for IDJAGValidator
# ============================================================================


def test_id_jag_validator_initialization(jwt_validation_config):
    """Test IDJAGValidator initialization."""
    validator = IDJAGValidator(jwt_validation_config)

    assert validator.config == jwt_validation_config
    assert isinstance(validator.replay_store, ReplayPreventionStore)
    assert validator.jwks_client is None  # No JWKS URI provided


def test_id_jag_validator_with_jwks():
    """Test IDJAGValidator initialization with JWKS URI."""
    config = JWTValidationConfig(
        trusted_idp_issuers=["https://idp.example.com"],
        server_auth_issuer="https://auth.server.example/",
        server_resource_id="https://server.example/",
        jwks_uri="https://idp.example.com/.well-known/jwks.json",
    )

    validator = IDJAGValidator(config)

    assert validator.jwks_client is not None


def test_validate_id_jag_success(jwt_validation_config, create_id_jag):
    """Test successful ID-JAG validation (without signature verification)."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    # Mock the JWT decode to skip signature verification
    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            "jti": "unique-jwt-id-12345",
            "iss": "https://idp.example.com",
            "sub": "user123",
            "aud": "https://auth.mcp-server.example/",
            "resource": "https://mcp-server.example/",
            "client_id": "mcp-client-app",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "scope": "read write",
        }

        claims = validator.validate_id_jag(id_jag, expected_client_id="mcp-client-app")

        assert claims.jti == "unique-jwt-id-12345"
        assert claims.iss == "https://idp.example.com"
        assert claims.sub == "user123"
        assert claims.client_id == "mcp-client-app"


def test_validate_id_jag_invalid_typ_header(jwt_validation_config, create_id_jag):
    """Test validation fails with invalid typ header."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = jwt.encode(
        {"iss": "https://idp.example.com"},
        "secret",
        algorithm="HS256",
        headers={"typ": "JWT"},  # Wrong typ
    )

    with pytest.raises(ValueError, match="Invalid typ header"):
        validator.validate_id_jag(id_jag, expected_client_id="client")


def test_validate_id_jag_expired(jwt_validation_config, create_id_jag):
    """Test validation fails for expired token."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag(claims={"exp": int(time.time()) - 100})  # Expired

    with patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}

        # jwt.decode will raise ExpiredSignatureError
        with pytest.raises(ValueError, match="ID-JAG has expired"):
            validator.validate_id_jag(id_jag, expected_client_id="client")


def test_validate_id_jag_untrusted_issuer(jwt_validation_config, create_id_jag):
    """Test validation fails for untrusted issuer."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            "jti": "jti123",
            "iss": "https://untrusted-idp.example.com",  # Untrusted
            "sub": "user123",
            "aud": "https://auth.mcp-server.example/",
            "resource": "https://mcp-server.example/",
            "client_id": "client",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
        }

        with pytest.raises(ValueError, match="Untrusted issuer"):
            validator.validate_id_jag(id_jag, expected_client_id="client")


def test_validate_id_jag_invalid_audience(jwt_validation_config, create_id_jag):
    """Test validation fails for invalid audience."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            "jti": "jti123",
            "iss": "https://idp.example.com",
            "sub": "user123",
            "aud": "https://wrong-server.example/",  # Wrong audience
            "resource": "https://mcp-server.example/",
            "client_id": "client",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
        }

        with pytest.raises(ValueError, match="Invalid audience"):
            validator.validate_id_jag(id_jag, expected_client_id="client")


def test_validate_id_jag_invalid_resource(jwt_validation_config, create_id_jag):
    """Test validation fails for invalid resource."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            "jti": "jti123",
            "iss": "https://idp.example.com",
            "sub": "user123",
            "aud": "https://auth.mcp-server.example/",
            "resource": "https://wrong-server.example/",  # Wrong resource
            "client_id": "client",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
        }

        with pytest.raises(ValueError, match="Invalid resource"):
            validator.validate_id_jag(id_jag, expected_client_id="client")


def test_validate_id_jag_client_id_mismatch(jwt_validation_config, create_id_jag):
    """Test validation fails for client_id mismatch."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            "jti": "jti123",
            "iss": "https://idp.example.com",
            "sub": "user123",
            "aud": "https://auth.mcp-server.example/",
            "resource": "https://mcp-server.example/",
            "client_id": "wrong-client",  # Doesn't match expected
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
        }

        with pytest.raises(ValueError, match="client_id mismatch"):
            validator.validate_id_jag(id_jag, expected_client_id="expected-client")


def test_validate_id_jag_missing_jti(jwt_validation_config, create_id_jag):
    """Test validation fails for missing jti."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            # Missing jti
            "iss": "https://idp.example.com",
            "sub": "user123",
            "aud": "https://auth.mcp-server.example/",
            "resource": "https://mcp-server.example/",
            "client_id": "client",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
        }

        with pytest.raises(ValueError, match="Missing jti claim"):
            validator.validate_id_jag(id_jag, expected_client_id="client")


def test_validate_id_jag_replay_detection(jwt_validation_config, create_id_jag):
    """Test replay attack detection."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            "jti": "replay-jti-123",
            "iss": "https://idp.example.com",
            "sub": "user123",
            "aud": "https://auth.mcp-server.example/",
            "resource": "https://mcp-server.example/",
            "client_id": "client",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
        }

        # First validation should succeed
        claims = validator.validate_id_jag(id_jag, expected_client_id="client")
        assert claims.jti == "replay-jti-123"

        # Second validation with same jti should fail
        with pytest.raises(ValueError, match="Token replay detected"):
            validator.validate_id_jag(id_jag, expected_client_id="client")


def test_validate_id_jag_replay_disabled(create_id_jag):
    """Test that replay detection can be disabled."""
    config = JWTValidationConfig(
        trusted_idp_issuers=["https://idp.example.com"],
        server_auth_issuer="https://auth.mcp-server.example/",
        server_resource_id="https://mcp-server.example/",
        replay_prevention_enabled=False,  # Disabled
    )

    validator = IDJAGValidator(config)
    id_jag = create_id_jag()

    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            "jti": "jti123",
            "iss": "https://idp.example.com",
            "sub": "user123",
            "aud": "https://auth.mcp-server.example/",
            "resource": "https://mcp-server.example/",
            "client_id": "client",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
        }

        # Should succeed multiple times
        validator.validate_id_jag(id_jag, expected_client_id="client")
        validator.validate_id_jag(id_jag, expected_client_id="client")


@pytest.mark.anyio
async def test_handle_jwt_bearer_grant_success(jwt_validation_config, create_id_jag):
    """Test successful JWT bearer grant handling."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    with patch("jwt.decode") as mock_decode, patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "oauth-id-jag+jwt", "alg": "HS256"}
        mock_decode.return_value = {
            "jti": "jti123",
            "iss": "https://idp.example.com",
            "sub": "user123",
            "aud": "https://auth.mcp-server.example/",
            "resource": "https://mcp-server.example/",
            "client_id": "client123",
            "exp": int(time.time()) + 300,
            "iat": int(time.time()),
            "scope": "read write",
        }

        result = await validator.handle_jwt_bearer_grant(
            assertion=id_jag,
            client_id="client123",
        )

        assert result["token_type"] == "Bearer"
        assert "access_token" in result
        assert result["expires_in"] == 3600
        assert result["scope"] == "read write"


@pytest.mark.anyio
async def test_handle_jwt_bearer_grant_validation_failure(jwt_validation_config, create_id_jag):
    """Test JWT bearer grant with validation failure."""
    validator = IDJAGValidator(jwt_validation_config)
    id_jag = create_id_jag()

    with patch("jwt.get_unverified_header") as mock_header:
        mock_header.return_value = {"typ": "wrong-typ", "alg": "HS256"}

        with pytest.raises(ValueError, match="Invalid typ header"):
            await validator.handle_jwt_bearer_grant(
                assertion=id_jag,
                client_id="client123",
            )

