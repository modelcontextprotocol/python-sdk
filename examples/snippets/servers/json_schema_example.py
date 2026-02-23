from pydantic import BaseModel, Field


class SearchParams(BaseModel):
    query: str = Field(description="Search query string")
    max_results: int = Field(default=10, description="Maximum results to return")


# Pydantic generates a JSON Schema 2020-12 compatible schema:
schema = SearchParams.model_json_schema()
# {
#     "properties": {
#         "query": {"description": "Search query string", "type": "string"},
#         "max_results": {
#             "default": 10,
#             "description": "Maximum results to return",
#             "type": "integer",
#         },
#     },
#     "required": ["query"],
#     "title": "SearchParams",
#     "type": "object",
# }
