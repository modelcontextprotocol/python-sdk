"""Shared pydantic bases for the per-version wire-shape model packages.

Every model in the ``mcp.types.v*`` packages builds on one of the two bases
here, so the five packages cannot silently diverge in model configuration.
There is deliberately no alias generator: each wire name in a version package
is an explicit ``Field(alias=...)``, so the package file shows exactly what
goes on the wire and cannot inherit serialization behavior from elsewhere.
"""

from pydantic import BaseModel, ConfigDict


class WireModel(BaseModel):
    """Base for version-package models: unknown fields are dropped.

    ``extra="ignore"`` is a deliberate divergence from the schemas, which
    declare most wire objects open to extra fields. Closed models are what
    make a field the target protocol revision never defined register as a
    loss when a value is revalidated for that revision's wire, and they keep
    an empty result dumping as exactly ``{}`` (deployed peers reject an empty
    result that carries extra keys).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class OpenWireModel(BaseModel):
    """Base for ``_meta`` carrier models: unknown fields are retained.

    Unknown ``_meta`` keys must survive a validate -> re-dump round trip at
    every protocol revision, so the classes a ``_meta`` field references stay
    open.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")
