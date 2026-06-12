"""Deliberate divergences between SDK type names and MCP schema export names.

Each MCP protocol revision publishes a schema whose exported type names do not
always map one-to-one onto the SDK's public names. This module records those
naming decisions and the reasons behind them — an entry here is a reviewed
decision, not drift.

Three tables:

- ``SDK_TO_SCHEMA_RENAMES``: the SDK models this wire shape under a different
  name than the schema export (SDK name -> schema name).
- ``SCHEMA_NOT_MODELED``: the schema export is deliberately not modeled as an
  SDK type. The value is a short kebab-case reason code naming the modeling
  decision (for example ``"named-error-wrapper"``: error wrapper interfaces
  whose wire values the generic ``ErrorData`` envelope already covers).
- ``SDK_ONLY_NAMES``: SDK-coined public names that accompany the decisions
  above — exports for constructs the schema leaves inline or unmodeled (a
  named inline literal, an SDK-side result split, the data payloads of the
  unmodeled error wrappers).

This module is the review record, not the comparison. The comparison lives in
``tests/spec_oracles/``: its ``_harness.py`` builds the schema -> SDK name
pairing by inverting ``SDK_TO_SCHEMA_RENAMES`` (so the rename record has one
home) and is itself authoritative for the version-scoped pairing overrides
and the machinery exemptions, while its ``burndown_allowlist.json`` is
authoritative for the standing divergence findings, version by version.
``tests/types/test_spec_names.py`` asserts the records agree where they
overlap: every deliberately-unmodeled schema export listed here is
acknowledged by the allowlist, and every SDK-only name listed here is one the
comparison also treats as schema-less.

The ``# OD-13 alternative:`` comment below follows the decision-marker
convention described in the ``mcp.types._types`` module docstring: it names a
reviewed design alternative that was NOT taken, as a record, not a TODO.
"""

from typing import Final

SDK_TO_SCHEMA_RENAMES: Final[dict[str, str]] = {
    # The schema only hoisted "Error" as a named export in 2025-11-25; the SDK
    # name survives from v1.x.
    "ErrorData": "Error",
    # 2025-11-25 renamed the success envelope and recycled "JSONRPCResponse"
    # for the success|error union (see SCHEMA_NOT_MODELED); the SDK keeps its
    # original names for both envelope models.
    "JSONRPCResponse": "JSONRPCResultResponse",
    "JSONRPCError": "JSONRPCErrorResponse",
    # The SDK keeps its v1.x notification name; the schema (2025-11-25 and
    # later) spells out "Elicitation".
    "ElicitCompleteNotification": "ElicitationCompleteNotification",
    # The schema (2026-07-28) names the request-scoped `_meta` object; the SDK
    # models it as an open TypedDict that types `progressToken` and carries the
    # reserved `io.modelcontextprotocol/*` keys as extra items (see the
    # `*_META_KEY` constants).
    "RequestParamsMeta": "RequestMetaObject",
}

SCHEMA_NOT_MODELED: Final[dict[str, str]] = {
    # 2025-11-25 recycled the export name "JSONRPCResponse" for the union
    # JSONRPCResultResponse | JSONRPCErrorResponse. The SDK keeps that name for
    # the success-only envelope model, so the union sense is deliberately not
    # modeled: JSONRPCMessage parses both members, and session/transport code
    # types them as JSONRPCResponse | JSONRPCError.
    "JSONRPCResponse": "name-recycled-union",
    "JSONRPCBatchRequest": "jsonrpc-batching-2025-03-26-only-never-implemented",
    "JSONRPCBatchResponse": "jsonrpc-batching-2025-03-26-only-never-implemented",
    # 2026-07-28 JSON aliases; the Python side uses builtins.
    "JSONValue": "json-alias-builtins-serve",  # Any
    "JSONObject": "json-alias-builtins-serve",  # dict[str, Any]
    "JSONArray": "json-alias-builtins-serve",  # list[Any]
    # General `_meta` containers are the SDK's open `Meta` mapping
    # (`dict[str, Any]`); the schema's named alias for them adds no structure.
    # (The request-scoped `RequestMetaObject` IS modeled — see
    # SDK_TO_SCHEMA_RENAMES.)
    "MetaObject": "nominal-alias-covered-by-dict",
    # @internal TS mixin {icons?: Icon[]}; the generated JSON schemas flatten it
    # (zero $refs to the $def) and the SDK declares the field inline on each of
    # Implementation/Resource/ResourceTemplate/Prompt/Tool.
    "Icons": "interface-mixin-flattened",
    # Every schema version exports `Cursor` as a bare alias of string; the SDK
    # inlines `str` on the consuming pagination fields and dropped the named
    # alias from its public surface in v2.
    "Cursor": "alias-for-str-inlined-on-consuming-fields-removed-at-v2",
    # @internal shared base interface (2025-11-25 and later) whose single field
    # `uri` is declared directly on ReadResourceRequestParams,
    # SubscribeRequestParams, and UnsubscribeRequestParams.
    "ResourceRequestParams": "structural-base-flattened",
    # 2026-07-28 grouped exports pairing a result type with its JSON-RPC
    # response frame. The SDK keeps the envelope/payload split: the generic
    # success envelope (`JSONRPCResponse`) carries any typed result body.
    "DiscoverResultResponse": "envelope-wrapper",
    "ListResourcesResultResponse": "envelope-wrapper",
    "ListResourceTemplatesResultResponse": "envelope-wrapper",
    "ReadResourceResultResponse": "envelope-wrapper",
    "ListPromptsResultResponse": "envelope-wrapper",
    "GetPromptResultResponse": "envelope-wrapper",
    "ListToolsResultResponse": "envelope-wrapper",
    "CallToolResultResponse": "envelope-wrapper",
    "CompleteResultResponse": "envelope-wrapper",
    # 2025-11-25 shared base interface for the params classes that accept a
    # `task` field; the SDK declares the field directly on each of the four
    # task-augmentable params classes.
    "TaskAugmentedRequestParams": "structural-base-flattened",
    # The named-error wrapper interfaces: documentation vehicles (the five
    # standard JSON-RPC ones) or error frames whose data payloads ARE modeled
    # (`UnsupportedProtocolVersionErrorData` and friends). The generic
    # `ErrorData` envelope plus the code constants cover every wire value.
    # Elicitation requested-schema vocabulary: the SDK deliberately keeps
    # ElicitRequestedSchema = dict[str, Any] (untyped passthrough); the
    # restricted-JSON-Schema union and its members are not modeled.
    # OD-13 alternative: model the requested-schema vocabulary as typed classes alongside the untyped field.
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
    "ParseError": "named-error-wrapper",
    "InvalidRequestError": "named-error-wrapper",
    "MethodNotFoundError": "named-error-wrapper",
    "InvalidParamsError": "named-error-wrapper",
    "InternalError": "named-error-wrapper",
    "UnsupportedProtocolVersionError": "named-error-wrapper",
    "MissingRequiredClientCapabilityError": "named-error-wrapper",
    "URLElicitationRequiredError": "named-error-wrapper",
}

SDK_ONLY_NAMES: Final[frozenset[str]] = frozenset(
    {
        # Names the inline "light" | "dark" literal of Icon.theme; no schema
        # version exports a named alias for it.
        "IconTheme",
        # Error-code constants and data payload models for errors the schemas
        # define only inside named-error wrapper interfaces (deliberately not
        # modeled — see SCHEMA_NOT_MODELED).
        "UnsupportedProtocolVersionErrorData",
        "UNSUPPORTED_PROTOCOL_VERSION",
        "MissingRequiredClientCapabilityErrorData",
        "MISSING_REQUIRED_CLIENT_CAPABILITY",
        "ElicitationRequiredErrorData",
        # The schemas inline the completion request's argument/context objects
        # on CompleteRequestParams; the SDK names them.
        "CompletionArgument",
        "CompletionContext",
        # SDK-side split of the schema's CreateMessageResult: the wide
        # (2025-11-25+) array-content shape gets its own class so the
        # single-block class keeps its v1.x constructor surface.
        "CreateMessageResultWithTools",
        # Names the untyped requested-schema dict on form-mode elicitation
        # params (see the elicitation-requested-schema-untyped rows above).
        "ElicitRequestedSchema",
    }
)
