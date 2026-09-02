"""A thin MCP-over-HTTP client to the SealGate gateway.

A faithful Python port of the Rust ``sealg`` transport in this repo
(``crates/engine/src/gateway/``). It speaks the small slice of MCP it needs -
``initialize``, ``tools/list``, ``tools/call`` - directly to the gateway's
``/mcp/{api_key}/`` endpoint. It carries no policy: the gateway enforces access
control, lethal-trifecta blocking, and audit. All the wire constants come from
:mod:`contract` so this client and the Rust one cannot drift (the pre-commit
guard verifies it).

Config resolves purely from the environment (matching the Rust binary), so the
CLI stays stateless and drops cleanly into any shell, CI job, or agent sandbox.
"""

from __future__ import annotations

import contextlib
import json
import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Self

import httpx

from .contract import (
    ACCEPT,
    CONVERSATION_ID_HEADER,
    DEFAULT_URL,
    ENV_API_KEY,
    ENV_CA_BUNDLE,
    ENV_CONVERSATION_ID,
    ENV_CONVERSATION_ID_FALLBACK,
    ENV_SECRET_KEY,
    ENV_URL,
    MCP_PATH_KEYLESS,
    MCP_PATH_WITH_KEY,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_HEADER,
    SECRET_KEY_HEADER,
)

DEFAULT_TIMEOUT = 30.0


class GatewayError(Exception):
    """Any failure reaching or talking to the gateway."""


class RpcError(GatewayError):
    """A JSON-RPC error returned by the gateway (mirrors the MCP error shape)."""

    def __init__(self, code: int, message: str, data: object = None) -> None:
        super().__init__(f"rpc error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


@dataclass
class ToolInfo:
    name: str
    description: str
    input_schema: object


@dataclass
class GatewayConfig:
    """Everything needed to reach the gateway, resolved once from the env."""

    base_url: str
    api_key: str | None
    secret_key: str | None
    conversation_id: str | None
    ca_bundle: str | None

    @staticmethod
    def _get(env: Mapping[str, str], key: str) -> str | None:
        """Return the raw env value if non-blank, else None. strip() is only the
        blank test - the value itself is returned unmodified, matching the Rust
        client (`.filter(|v| !v.trim().is_empty())`), so a padded key or id is
        sent identically by both clients."""
        val = env.get(key)
        if val is None or not val.strip():
            return None
        return val

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, url_override: str | None = None
    ) -> GatewayConfig:
        env = os.environ if env is None else env

        base_url = (cls._get(env, ENV_URL) or DEFAULT_URL).rstrip("/")
        if url_override is not None:
            trimmed = url_override.strip().rstrip("/")
            if trimmed:
                base_url = trimmed

        conversation_id = cls._get(env, ENV_CONVERSATION_ID) or cls._get(
            env, ENV_CONVERSATION_ID_FALLBACK
        )
        ca_bundle = next((v for k in ENV_CA_BUNDLE if (v := cls._get(env, k))), None)

        return cls(
            base_url=base_url,
            api_key=cls._get(env, ENV_API_KEY),
            secret_key=cls._get(env, ENV_SECRET_KEY),
            conversation_id=conversation_id,
            ca_bundle=ca_bundle,
        )

    def mcp_url(self) -> str:
        """``{base}/mcp/{key}/`` with a key, else ``{base}/mcp/`` (auth injected).

        The path shapes come from :mod:`contract` (``MCP_PATH_*``) so the drift
        guard can compare them against the Rust ``mcp_url``.
        """
        if self.api_key:
            return self.base_url + MCP_PATH_WITH_KEY.format(key=self.api_key)
        return self.base_url + MCP_PATH_KEYLESS

    def auth_mode(self) -> str:
        return "env-key" if self.api_key else "proxy-injected"


def redact_url(url: str, api_key: str | None) -> str:
    """Replace the ``/{key}/`` path segment with ``/***/`` so errors don't leak
    the key (it rides in the ``/mcp/{key}/`` path). Only the delimited segment
    is replaced, never a blanket substring swap."""
    if api_key:
        return url.replace(f"/{api_key}/", "/***/")
    return url


def _extract_rpc_result(content_type: str, body: str, want_id: int) -> Any:
    """Extract the JSON-RPC ``result`` for ``want_id`` from a JSON or SSE body.

    Raises :class:`RpcError` on a JSON-RPC error, :class:`GatewayError` on a
    protocol problem. Pure, so it is unit-tested directly.
    """
    if "text/event-stream" in content_type:
        msg = _sse_find_response(body, want_id)
        if msg is None:
            raise GatewayError("no JSON-RPC response in SSE stream")
    else:
        try:
            msg = json.loads(body.strip())
        except json.JSONDecodeError as e:
            raise GatewayError(f"invalid JSON response: {e}") from e
    return _rpc_message_to_result(msg)


def _rpc_message_to_result(msg: object) -> Any:
    # A valid-JSON scalar (e.g. `5`) is a protocol error, not a crash.
    if not isinstance(msg, dict):
        raise GatewayError("JSON-RPC response was not an object")
    if "error" in msg and msg["error"] is not None:
        err = msg["error"]
        if not isinstance(err, dict):
            raise GatewayError("JSON-RPC error was not an object")
        raise RpcError(
            code=int(err.get("code", 0)),
            message=str(err.get("message", "unknown error")),
            data=err.get("data"),
        )
    if "result" in msg:
        return msg["result"]
    raise GatewayError("JSON-RPC response had neither result nor error")


def _sse_find_response(body: str, want_id: int) -> dict | None:
    """Scan SSE ``data:`` frames for the JSON-RPC response matching ``want_id``."""
    fallback: dict | None = None
    for line in body.splitlines():
        line = line.lstrip()
        if not line.startswith("data:"):
            continue
        try:
            v = json.loads(line[len("data:") :].strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(v, dict) or ("result" not in v and "error" not in v):
            continue  # notifications carry neither
        if v.get("id") == want_id:
            return v
        if fallback is None:
            fallback = v
    return fallback


class GatewayClient:
    """A live connection to the gateway's per-user MCP endpoint."""

    def __init__(self, cfg: GatewayConfig, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.cfg = cfg
        self.url = cfg.mcp_url()
        _u = httpx.URL(self.url)
        self._origin = (_u.scheme, _u.host, _u.port)
        self._session_id: str | None = None
        self._next_id = 0
        # verify: add the MITM CA to the system trust store (additive, matching
        # the Rust client's add_root_certificate) rather than replacing it. A
        # missing/invalid bundle surfaces as GatewayError, not a raw ssl/OSError.
        verify: ssl.SSLContext | bool = True
        if cfg.ca_bundle:
            ctx = ssl.create_default_context()
            try:
                ctx.load_verify_locations(cafile=cfg.ca_bundle)
            except (OSError, ssl.SSLError) as e:
                raise GatewayError(f"CA bundle {cfg.ca_bundle}: {e}") from e
            verify = ctx
        # trust_env=True (default) honors HTTPS_PROXY/HTTP_PROXY. follow_redirects
        # mirrors reqwest (the Rust client follows up to 10; cap it the same so
        # redirect-exhaustion behavior matches). The request hook strips the
        # credential headers on any cross-origin redirect so a redirect to a
        # different host can't carry sealg's secret key or session id off the
        # configured gateway origin.
        self._http = httpx.Client(
            timeout=timeout,
            verify=verify,
            follow_redirects=True,
            max_redirects=10,
            event_hooks={"request": [self._strip_creds_off_origin]},
        )

    def _strip_creds_off_origin(self, request: httpx.Request) -> None:
        origin = (request.url.scheme, request.url.host, request.url.port)
        if origin != self._origin:
            for header in (SECRET_KEY_HEADER, CONVERSATION_ID_HEADER, "Mcp-Session-Id"):
                request.headers.pop(header, None)

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def connect(self) -> GatewayClient:
        """Run the MCP ``initialize`` handshake and capture any session id."""
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "sealg", "version": _version()},
        }
        _, session_id = self._rpc_capture_session("initialize", params)
        self._session_id = session_id
        # Best-effort readiness notification; stateless servers may ignore it.
        with contextlib.suppress(GatewayError):
            self._notify("notifications/initialized", {})
        return self

    def tools_list(self) -> list[ToolInfo]:
        result = self._rpc("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise GatewayError("tools/list missing `tools` array")
        return [
            ToolInfo(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema"),
            )
            for t in tools
        ]

    def tools_call(self, name: str, arguments: object) -> Any:
        # Mirror the Rust client: only a null/None arguments becomes {}.
        args = {} if arguments is None else arguments
        return self._rpc("tools/call", {"name": name, "arguments": args})

    # --- transport ---------------------------------------------------------

    def _bump_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": ACCEPT,
            PROTOCOL_VERSION_HEADER: PROTOCOL_VERSION,
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        if self.cfg.secret_key:
            h[SECRET_KEY_HEADER] = self.cfg.secret_key
        if self.cfg.conversation_id:
            h[CONVERSATION_ID_HEADER] = self.cfg.conversation_id
        return h

    def _rpc(self, method: str, params: object) -> Any:
        return self._rpc_capture_session(method, params)[0]

    def _rpc_capture_session(
        self, method: str, params: object
    ) -> tuple[Any, str | None]:
        rpc_id = self._bump_id()
        body = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        try:
            resp = self._http.post(self.url, headers=self._headers(), json=body)
        except httpx.TimeoutException as e:
            raise GatewayError("timeout") from e
        except httpx.HTTPError as e:
            raise GatewayError(
                f"POST {redact_url(self.url, self.cfg.api_key)}: {e}"
            ) from e

        session_id = resp.headers.get("mcp-session-id")
        # Mirror reqwest's is_success(): only 2xx carries a JSON-RPC envelope.
        # Anything else (an un-followed 3xx after redirect exhaustion, an auth
        # 401) is an HTTP-level failure, not a body for the JSON-RPC parser.
        if not (200 <= resp.status_code < 300):
            # The body may echo the /mcp/{key}/ request URL, so redact the key
            # before it reaches stderr/logs.
            body = redact_url(resp.text[:512], self.cfg.api_key)
            raise GatewayError(f"gateway returned HTTP {resp.status_code}: {body}")
        result = _extract_rpc_result(
            resp.headers.get("content-type", ""), resp.text, rpc_id
        )
        return result, session_id

    def _notify(self, method: str, params: object) -> None:
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            self._http.post(self.url, headers=self._headers(), json=body)
        except httpx.HTTPError as e:
            raise GatewayError(str(e)) from e


def _version() -> str:
    try:
        return version("sealg")
    except PackageNotFoundError:
        return "0.0.0"
