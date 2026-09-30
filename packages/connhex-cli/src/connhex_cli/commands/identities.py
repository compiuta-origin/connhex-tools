import typer

from connhex_cli.client import connhex_client
from connhex_cli.context import CLIContext
from connhex_cli.output import console, render

identities_app = typer.Typer(help="Read Connhex identities.")


@identities_app.command("list")
def list_identities(
    ctx: typer.Context,
    limit: int = typer.Option(50, min=1, help="Max identities to return."),
    offset: int = typer.Option(0, min=0, help="Number of identities to skip."),
    credentials_identifier: str | None = typer.Option(
        None, help="Exact credential identifier (email or username)."
    ),
) -> None:
    """List identities; high offsets require additional API requests."""
    cli_ctx: CLIContext = ctx.obj
    result = connhex_client(ctx).iam.list_identities(
        limit=limit,
        offset=offset,
        credentials_identifier=credentials_identifier,
    )
    if cli_ctx.output == "json":
        render(result, "json")
    else:
        render(result.identities, "table")
        if result.next_offset is not None:
            console.print(f"Next offset: {result.next_offset}")


@identities_app.command("get")
def get_identity(
    ctx: typer.Context, identity_id: str = typer.Argument(...)
) -> None:
    """Get a single identity without credential information."""
    cli_ctx: CLIContext = ctx.obj
    render(connhex_client(ctx).iam.get_identity(identity_id), cli_ctx.output)
