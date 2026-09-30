import logging
from typing import Literal

import click
import httpx
import typer
from connhex.errors import ConnhexAPIError, ConnhexError
from typer.core import TyperGroup

from connhex_cli import __version__
from connhex_cli.commands.auth import auth_app
from connhex_cli.commands.identities import identities_app
from connhex_cli.commands.connectables import connectables_app
from connhex_cli.commands.messages import messages_app
from connhex_cli.commands.models import models_app
from connhex_cli.commands.resources import resources_app
from connhex_cli.commands.rules import rules_app
from connhex_cli.commands.things import things_app
from connhex_cli.context import CLIContext
from connhex_cli.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def _format_cli_error(error: Exception) -> str:
    if isinstance(error, ConnhexAPIError):
        return f"Connhex API returned {error.status}: {error.detail}"
    if isinstance(error, httpx.RequestError):
        return f"Network error: {error}"
    return str(error)


class ConnhexCLIGroup(TyperGroup):
    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except (ConnhexError, httpx.RequestError) as e:
            if ctx.params.get("debug"):
                raise
            typer.echo(f"Error: {_format_cli_error(e)}", err=True)
            raise typer.Exit(1) from e


app = typer.Typer(
    cls=ConnhexCLIGroup,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(auth_app, name="auth")
app.add_typer(identities_app, name="identities")
app.add_typer(things_app, name="things")
app.add_typer(models_app, name="models")
app.add_typer(resources_app, name="resources")
app.add_typer(rules_app, name="rules")
app.add_typer(messages_app, name="messages")
app.add_typer(connectables_app, name="connectables")


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"connhex-cli {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    instance_url: str | None = typer.Option(
        None, "--instance-url", envvar="CONNHEX_INSTANCE_URL"
    ),
    token: str | None = typer.Option(
        None, "--token", envvar="CONNHEX_BEARER_TOKEN"
    ),
    output: Literal["table", "json"] = typer.Option("json", "--output", "-o"),
    log_config: str | None = typer.Option(
        None,
        "--log-config",
        envvar="CONNHEX_LOG_CONFIG",
        help="Path to a JSON logging config file.",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        envvar="CONNHEX_CLI_DEBUG",
        help="Show tracebacks for SDK and network errors.",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        is_eager=True,
        callback=_version_cb,
    ),
) -> None:
    setup_logging(path=log_config)
    logger.info("connhex-cli %s starting", __version__)
    ctx.ensure_object(dict)
    ctx.obj = CLIContext(instance_url=instance_url, token=token, output=output)
