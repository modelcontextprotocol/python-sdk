import sys

import mcp_client.client.auth.utils as _implementation
from mcp_client.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_client_info_from_metadata_url,
    create_client_registration_request,
    create_oauth_metadata_request,
    credentials_match_issuer,
    extract_field_from_www_auth,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    get_client_metadata_scopes,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    handle_registration_response,
    handle_token_response_scopes,
    is_valid_client_metadata_url,
    issuers_match,
    should_use_client_metadata_url,
    union_scopes,
    validate_authorization_response_iss,
    validate_metadata_issuer,
)

__all__ = [
    "build_oauth_authorization_server_metadata_discovery_urls",
    "build_protected_resource_metadata_discovery_urls",
    "create_client_info_from_metadata_url",
    "create_client_registration_request",
    "create_oauth_metadata_request",
    "credentials_match_issuer",
    "extract_field_from_www_auth",
    "extract_resource_metadata_from_www_auth",
    "extract_scope_from_www_auth",
    "get_client_metadata_scopes",
    "handle_auth_metadata_response",
    "handle_protected_resource_response",
    "handle_registration_response",
    "handle_token_response_scopes",
    "is_valid_client_metadata_url",
    "issuers_match",
    "should_use_client_metadata_url",
    "union_scopes",
    "validate_authorization_response_iss",
    "validate_metadata_issuer",
]

sys.modules[__name__] = _implementation
