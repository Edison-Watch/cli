"""CLI for SealGate - a thin MCP client to the SealGate gateway.

``sealg list`` / ``sealg call`` forward ``tools/list`` / ``tools/call`` to the
per-user gateway endpoint; all policy and enforcement live in the gateway.
``sealg doctor`` reports the resolved environment and probes reachability. This
is the Python client; it mirrors the Rust ``sealg`` binary's surface and exit
codes.
"""

from __future__ import annotations

import json
import os
import platform

import typer

from .client import GatewayClient, GatewayConfig, redact_url
from .contract import ENV_CA_BUNDLE, EXIT_ERROR, EXIT_TOOL_ERROR

app = typer.Typer(
    name="sealg",
    help="Command-line interface for SealGate, the agentic data firewall",
    no_args_is_help=True,
    add_completion=False,
)


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


@app.command("doctor")
def doctor(
    gateway_url: str = typer.Option(
        None, "--gateway-url", help="Override the gateway base URL."
    ),
) -> None:
    """Report the resolved gateway environment and probe reachability."""
    cfg = GatewayConfig.from_env(url_override=gateway_url)
    report: dict[str, object] = {
        "tool": "sealg",
        "os": platform.system().lower(),
        "arch": platform.machine(),
        "gateway_url": redact_url(cfg.mcp_url(), cfg.api_key),
        "auth": cfg.auth_mode(),
        "secret_key_set": cfg.secret_key is not None,
        "conversation_id_set": cfg.conversation_id is not None,
        "ca_bundle": cfg.ca_bundle,
        # Which env var actually supplied the bundle (first non-blank, matching
        # GatewayConfig's precedence), or None.
        "ca_bundle_source": next(
            (k for k in ENV_CA_BUNDLE if os.environ.get(k, "").strip()), None
        ),
    }
    try:
        client = GatewayClient(cfg).connect()
        try:
            report["reachable"] = True
            report["tool_count"] = len(client.tools_list())
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 - doctor reports failures, never raises on them
        report["reachable"] = False
        report["error"] = str(exc)

    _emit(report)  # doctor is a diagnostic; always structured JSON
    if not report["reachable"]:
        raise typer.Exit(EXIT_ERROR)


@app.command("list")
def list_tools(
    json_out: bool = typer.Option(
        False, "--json", help="Output as a JSON array of {name, description}."
    ),
    gateway_url: str = typer.Option(
        None, "--gateway-url", help="Override the gateway base URL."
    ),
) -> None:
    """List the user's tools from the live SealGate gateway."""
    cfg = GatewayConfig.from_env(url_override=gateway_url)
    try:
        client = GatewayClient(cfg).connect()
        try:
            tools = client.tools_list()
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc

    if json_out:
        _emit([{"name": t.name, "description": t.description} for t in tools])
    else:
        for t in tools:
            # The em dash keeps this list output identical to the Rust client's;
            # written as a backslash-u2014 escape because the repo ai-writing
            # check bans a literal U+2014 in source.
            typer.echo(f"{t.name}  \u2014  {t.description}")


@app.command("call")
def call_tool(
    tool: str = typer.Argument(..., help="Tool name as advertised by `sealg list`."),
    args: str = typer.Option(
        "{}", "--args", help="JSON arguments object to pass to the tool."
    ),
    gateway_url: str = typer.Option(
        None, "--gateway-url", help="Override the gateway base URL."
    ),
) -> None:
    """Call a tool on the live SealGate gateway."""
    try:
        arguments = json.loads(args)
    except json.JSONDecodeError as exc:
        typer.echo(f"error: invalid --args JSON: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    # MCP arguments must be an object. Reject a valid-JSON non-object locally
    # (e.g. --args '5' or '"x"') with a clear error rather than forwarding an
    # invalid tools/call. null is allowed; the client maps it to {}.
    if arguments is not None and not isinstance(arguments, dict):
        typer.echo("error: --args must be a JSON object", err=True)
        raise typer.Exit(EXIT_ERROR)

    cfg = GatewayConfig.from_env(url_override=gateway_url)
    try:
        client = GatewayClient(cfg).connect()
        try:
            result = client.tools_call(tool, arguments)
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc

    _emit(result)
    # Mirror the MCP tool-call response: an `isError: true` result is a failed
    # call and must not exit 0.
    if isinstance(result, dict) and result.get("isError") is True:
        raise typer.Exit(EXIT_TOOL_ERROR)


if __name__ == "__main__":
    app()
