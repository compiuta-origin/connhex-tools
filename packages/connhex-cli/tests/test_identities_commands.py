import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from connhex.errors import InvalidResponseError
from connhex.schemas.iam import IdentitiesPage, Identity
from typer.testing import CliRunner

from connhex_cli.commands import identities
from connhex_cli.main import app

runner = CliRunner()


@pytest.fixture
def iam(monkeypatch):
    service = Mock()
    service.list_identities.return_value = IdentitiesPage(
        identities=[Identity(id="one", traits={"email": "a@test.com"})],
        limit=2,
        offset=3,
        has_more=True,
        next_offset=5,
    )
    service.get_identity.return_value = Identity(id="one")
    monkeypatch.setattr(
        identities,
        "connhex_client",
        lambda ctx: SimpleNamespace(iam=service),
    )
    return service


def test_list_json_and_options(iam):
    result = runner.invoke(
        app,
        [
            "identities",
            "list",
            "--limit",
            "2",
            "--offset",
            "3",
            "--credentials-identifier",
            "a@test.com",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["identities"][0]["id"] == "one"
    assert payload["next_offset"] == 5
    iam.list_identities.assert_called_once_with(
        limit=2, offset=3, credentials_identifier="a@test.com"
    )


def test_list_table(iam):
    result = runner.invoke(app, ["-o", "table", "identities", "list"])
    assert result.exit_code == 0, result.output
    assert "one" in result.output and "Next offset: 5" in result.output


@pytest.mark.parametrize("output", ["json", "table"])
def test_get(iam, output):
    result = runner.invoke(app, ["-o", output, "identities", "get", "one"])
    assert result.exit_code == 0, result.output
    assert "one" in result.output
    iam.get_identity.assert_called_once_with("one")


@pytest.mark.parametrize("args", [["--limit", "0"], ["--offset", "-1"]])
def test_invalid_args(iam, args):
    result = runner.invoke(app, ["identities", "list", *args])
    assert result.exit_code == 2
    iam.list_identities.assert_not_called()


def test_invalid_response_error(iam):
    iam.list_identities.side_effect = InvalidResponseError("Invalid response")
    result = runner.invoke(app, ["identities", "list"])
    assert result.exit_code == 1
    assert "Error: Invalid response" in result.output


@pytest.mark.parametrize("args", [[], ["list"], ["get"]])
def test_help(args):
    assert runner.invoke(app, ["identities", *args, "--help"]).exit_code == 0
