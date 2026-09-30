from typing import Annotated

from connhex.schemas.iam import IdentitiesPage, Identity
from mcp.types import ToolAnnotations
from pydantic import Field

from connhex_mcp.client import get_connhex
from connhex_mcp.mcp_instance import mcp


@mcp.tool(
    title="List Identities",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def list_identities(
    limit: Annotated[int, Field(gt=0, description="Max identities.")] = 10,
    offset: Annotated[int, Field(ge=0, description="Identities to skip.")] = 0,
    credentials_identifier: Annotated[
        str | None, "Exact credential identifier (email or username)."
    ] = None,
) -> IdentitiesPage:
    """List Connhex identities without credentials using limit/offset.

    High offsets require additional API requests. Use next_offset for
    continuation; concurrent identity changes can affect pagination.
    """
    return await get_connhex().iam.list_identities(
        limit=limit,
        offset=offset,
        credentials_identifier=credentials_identifier,
    )


@mcp.tool(
    title="Get Identity",
    annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False
    ),
)
async def get_identity(
    identity_id: Annotated[str, "UUID of the identity."],
) -> Identity:
    """Get a Connhex identity by ID without credential information."""
    return await get_connhex().iam.get_identity(identity_id)
