from contextlib import asynccontextmanager

from fastmcp import FastMCP

from connhex_mcp import __version__
from connhex_mcp.client import get_connhex


@asynccontextmanager
async def lifespan(_server):
    try:
        from connhex_mcp.auth.remote import ConnhexOAuthProvider

        if isinstance(_server.auth, ConnhexOAuthProvider):
            await _server.auth.start()
        yield
    finally:
        if isinstance(_server.auth, ConnhexOAuthProvider):
            await _server.auth.close()
        # Only close if a client was actually built; avoid forcing creation
        # during shutdown of a server that never served a request.
        if get_connhex.cache_info().currsize:
            await get_connhex().close()


mcp = FastMCP(
    "connhex",
    version=__version__,
    instructions=(
        "Connhex MCP server. Use these tools to interact with a Connhex Cloud instance."
    ),
    lifespan=lifespan,
)
