"""Shared pydantic bases for the generated `mcp_types._v*` wire-shape packages.

Both bases set `defer_build=True`: pydantic then skips core-schema, validator
and serializer construction at class creation and builds each model once, on
its first validation. A generated package defines ~175 models but a connection
touches only the handful its negotiated version and methods use, so importing a
package is class-body execution only and the schema build is paid lazily,
per model, exactly once.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, RootModel

_RootT = TypeVar("_RootT")


class WireModel(BaseModel):
    """Base for generated wire models: enables `populate_by_name`; subclasses set `extra` themselves."""

    model_config = ConfigDict(populate_by_name=True, defer_build=True)


class WireRootModel(RootModel[_RootT], Generic[_RootT]):
    """Base for generated named-alias root models (`X(WireRootModel[T])`).

    Carrying `defer_build` on this generic base defers the `WireRootModel[T]`
    parameterization itself (a model class in its own right) as well as the
    named subclass; a config on the subclass alone would still build the
    parameterized base eagerly.
    """

    model_config = ConfigDict(defer_build=True)
