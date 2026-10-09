from mcp.types import ToolAnnotations

from connhex_mcp.client import get_connhex
from connhex_mcp.mcp_instance import mcp


@mcp.tool(
    title="Get Current User and Session",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def whoami() -> dict:
    """
    Returns information about the currently authenticated user.
    Use this to verify the connection and see user's identity (active Connhex Accounts session).
    """
    return await get_connhex().iam.whoami()
