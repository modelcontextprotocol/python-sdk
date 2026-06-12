"""Deliberate divergences between SDK type names and MCP schema export names.

Every public schema export of every supported protocol version either maps to
an SDK definition of the same name, or appears in exactly one of the three
tables below. The tables are consumed by the spec-oracle comparison tests, so
each entry is a reviewed decision, not drift.
"""

from __future__ import annotations

from typing import Final

SDK_TO_SCHEMA_RENAMES: Final[dict[str, str]] = {
    # The SDK keeps its original envelope names: 2025-11-25 renamed the
    # schema's success-response type to JSONRPCResultResponse and its error
    # response to JSONRPCErrorResponse.
    "JSONRPCResponse": "JSONRPCResultResponse",
    "JSONRPCError": "JSONRPCErrorResponse",
    # v1.x-surviving SDK name; the schema hoisted the named "Error" export
    # only in 2025-11-25.
    "ErrorData": "Error",
    # v1.x-surviving SDK name; the schema (2025-11-25+) spells out "Elicitation".
    "ElicitCompleteNotification": "ElicitationCompleteNotification",
}
"""SDK name -> schema name, where the SDK deliberately keeps a different name."""

SCHEMA_NOT_MODELED: Final[dict[str, str]] = {
    # 2025-11-25 recycled the export name "JSONRPCResponse" for the union
    # JSONRPCResultResponse | JSONRPCErrorResponse. The SDK keeps that name for
    # the success-only envelope model, so the union sense is deliberately not
    # modeled: JSONRPCMessage parses both members, and session/transport code
    # types them as JSONRPCResponse | JSONRPCError.
    "JSONRPCResponse": "name-recycled-union",
    "JSONRPCBatchRequest": "jsonrpc-batching-2025-03-26-only-never-implemented",
    "JSONRPCBatchResponse": "jsonrpc-batching-2025-03-26-only-never-implemented",
    # JSON aliases added in the 2026-07-28 schema; the Python side is
    # Any / dict[str, Any] / list[Any].
    "JSONValue": "json-alias-builtins-serve",
    "JSONObject": "json-alias-builtins-serve",
    "JSONArray": "json-alias-builtins-serve",
    # Pagination cursor: a schema alias for string, inlined as the plain `str`
    # `cursor`/`nextCursor` fields of the paginated request/result bases.
    "Cursor": "alias-for-str-inlined-on-consuming-fields-removed-at-v2",
    # 2026-07-28-only JSON-RPC success wrappers around result payloads; the SDK
    # keeps the envelope/payload split (the payloads are modeled, the wrappers
    # are not).
    "DiscoverResultResponse": "envelope-wrapper",
    "ListResourcesResultResponse": "envelope-wrapper",
    "ListResourceTemplatesResultResponse": "envelope-wrapper",
    "ReadResourceResultResponse": "envelope-wrapper",
    "ListPromptsResultResponse": "envelope-wrapper",
    "GetPromptResultResponse": "envelope-wrapper",
    "ListToolsResultResponse": "envelope-wrapper",
    "CallToolResultResponse": "envelope-wrapper",
    "CompleteResultResponse": "envelope-wrapper",
    # @internal shared base (2025-11-25+); its single field `uri` is carried
    # verbatim by ReadResource/Subscribe/UnsubscribeRequestParams.
    "ResourceRequestParams": "structural-base-flattened",
    # @internal shared base (2025-11-25); its single field `task` is declared
    # directly on the four task-augmentable params classes
    # (CallToolRequestParams, CreateMessageRequestParams, both ElicitRequest
    # params variants).
    "TaskAugmentedRequestParams": "structural-base-flattened",
    # Elicitation requested-schema vocabulary: the SDK deliberately keeps
    # ElicitRequestedSchema = dict[str, Any] (untyped passthrough); the
    # restricted-JSON-Schema union and its members are not modeled.
    # OD-13 alternative: model the vocabulary as additive standalone classes.
    "PrimitiveSchemaDefinition": "elicitation-requested-schema-untyped",
    "StringSchema": "elicitation-requested-schema-untyped",
    "NumberSchema": "elicitation-requested-schema-untyped",
    "BooleanSchema": "elicitation-requested-schema-untyped",
    "EnumSchema": "elicitation-requested-schema-untyped",
    "SingleSelectEnumSchema": "elicitation-requested-schema-untyped",
    "UntitledSingleSelectEnumSchema": "elicitation-requested-schema-untyped",
    "TitledSingleSelectEnumSchema": "elicitation-requested-schema-untyped",
    "MultiSelectEnumSchema": "elicitation-requested-schema-untyped",
    "UntitledMultiSelectEnumSchema": "elicitation-requested-schema-untyped",
    "TitledMultiSelectEnumSchema": "elicitation-requested-schema-untyped",
    "LegacyTitledEnumSchema": "elicitation-requested-schema-untyped",
    # The `_meta` carriers: `Meta` (a private dict alias) covers MetaObject, and
    # `RequestParamsMeta` is deliberately not field-equivalent to
    # RequestMetaObject — the reserved keys ride its open `extra_items=Any` map
    # and are injected/validated at the wire boundary. Not a model rename: the
    # oracle harness's name map pairs RequestMetaObject with RequestParamsMeta
    # only so the def does not surface as a missing type; the TypedDict reduces
    # to an opaque open dict in the harness's signature algebra, so per-key
    # constraints are not compared there. The reserved-key handling is verified
    # by the wire-boundary tests and the required-_meta method-set oracle test
    # instead.
    "MetaObject": "nominal-alias-covered-by-dict",
    "RequestMetaObject": "meta-managed-at-boundary",
    # @internal TS mixin {icons?: Icon[]}; the generated JSON schemas flatten it
    # (zero $refs to the $def) and the SDK declares the field inline on each of
    # Implementation/Resource/ResourceTemplate/Prompt/Tool.
    "Icons": "interface-mixin-flattened",
    # The eight named-error wrapper interfaces: documentation vehicles (the
    # five standard ones) or response-shaped frames whose payloads ARE modeled
    # (the three with typed data). The generic ErrorData plus the error-code
    # constants (and the *ErrorData payload classes) cover every wire value.
    "ParseError": "named-error-wrapper",
    "InvalidRequestError": "named-error-wrapper",
    "MethodNotFoundError": "named-error-wrapper",
    "InvalidParamsError": "named-error-wrapper",
    "InternalError": "named-error-wrapper",
    "UnsupportedProtocolVersionError": "named-error-wrapper",
    "MissingRequiredClientCapabilityError": "named-error-wrapper",
    "URLElicitationRequiredError": "named-error-wrapper",
}
"""Schema export -> reason code, for schema names deliberately not modeled."""

SDK_ONLY_NAMES: Final[frozenset[str]] = frozenset(
    {
        # Alias for the inline "light" | "dark" icon-theme literal; exported by
        # no schema version.
        "IconTheme",
        # Typed payloads + constants for error codes whose schema-side wrapper
        # interfaces are in SCHEMA_NOT_MODELED above.
        "UnsupportedProtocolVersionErrorData",
        "UNSUPPORTED_PROTOCOL_VERSION",
        "MissingRequiredClientCapabilityErrorData",
        "MISSING_REQUIRED_CLIENT_CAPABILITY",
        "ElicitationRequiredErrorData",
        # Named sub-models for shapes every schema version declares inline on
        # CompleteRequest/CompleteResult.
        "Completion",
        "CompletionArgument",
        "CompletionContext",
        # SDK-side split of the schema's single CreateMessageResult: the narrow
        # single-block class keeps the v2-base name, and the array/tool-content
        # shape (2025-11-25+) lives on its own class. SamplingContent names the
        # narrow class's inline content union; StopReason names the inline
        # stop-reason union.
        "CreateMessageResultWithTools",
        "SamplingContent",
        "StopReason",
    }
)
"""Public ``mcp.types`` names with no schema counterpart in any supported version."""
