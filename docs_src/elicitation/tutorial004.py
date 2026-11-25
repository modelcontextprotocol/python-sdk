from typing import Annotated

from pydantic import BaseModel

from mcp.server import MCPServer
from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    Resolve,
)

mcp = MCPServer("Files")

_FOLDERS: dict[str, list[str]] = {"/tmp/empty": [], "/tmp/project": ["main.py", "README.md"]}


class Confirm(BaseModel):
    ok: bool


async def confirm_delete(path: str) -> Confirm | Elicit[Confirm]:
    """Resolver: ask for confirmation only when the folder is not empty."""
    file_count = len(_FOLDERS.get(path, []))
    if file_count == 0:
        return Confirm(ok=True)  # nothing to confirm, no round-trip to the client
    return Elicit(f"{path} has {file_count} file(s). Delete anyway?", Confirm)


@mcp.tool()
async def delete_folder(
    path: str,
    confirm: Annotated[ElicitationResult[Confirm], Resolve(confirm_delete)],
) -> str:
    """Delete a folder, asking for confirmation when it is not empty."""
    match confirm:
        case AcceptedElicitation(data=Confirm(ok=True)):
            _FOLDERS.pop(path, None)
            return f"deleted {path}"
        case AcceptedElicitation():
            return "kept the folder"
        case DeclinedElicitation():
            return "declined: folder not deleted"
        case CancelledElicitation():
            return "cancelled: folder not deleted"
