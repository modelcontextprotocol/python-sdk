from typing import Any

from starlette.responses import JSONResponse


class PydanticJSONResponse(JSONResponse):
    # Pydantic serialization instead of stock json.dumps, so models with fields like AnyHttpUrl serialize.
    def render(self, content: Any) -> bytes:
        return content.model_dump_json(exclude_none=True).encode("utf-8")
