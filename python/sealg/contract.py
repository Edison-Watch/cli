"""Single source of truth for the SealGate gateway wire contract.

This Python client and the Rust ``sealg`` binary in this repo talk to the same
MCP-over-HTTP gateway endpoint, so everything the two must agree on lives here
as plain literals. The drift guard (``scripts/check_wire_contract.py``, run on
pre-commit and in CI) loads this module in isolation and compares it against
the Rust source of truth in ``crates/engine/src/gateway/config.rs`` and
``.../client.rs``.

Keep this module import-free and side-effect-free: the guard imports it
directly from its file path, so a stray relative import would break the check.
Do not edit a value here without changing the Rust constant it mirrors (or the
guard fails), and vice versa.
"""

from __future__ import annotations

# --- protocol (mirrors client.rs::PROTOCOL_VERSION) ------------------------
# The MCP Streamable HTTP protocol version advertised in ``initialize``. Must be
# a version the gateway's MCP server accepts; it rejects unknown versions with
# JSON-RPC -32600.
PROTOCOL_VERSION = "2025-06-18"

# --- headers (mirror config.rs SECRET_KEY_HEADER / CONVERSATION_ID_HEADER) --
# Carries the zero-knowledge secret key value.
SECRET_KEY_HEADER = "sealgate_secret_key"
# Carries the stable conversation id (gateway: SEALGATE_CONVERSATION_ID_HEADER
# in src/middleware/session_tokens.py).
CONVERSATION_ID_HEADER = "x-sealgate-conversation-id"
# Advertises the protocol version on every request.
PROTOCOL_VERSION_HEADER = "MCP-Protocol-Version"
# The Accept value that lets the gateway answer with either a single JSON
# object or an SSE stream.
ACCEPT = "application/json, text/event-stream"

# --- environment keys (mirror config.rs::env_keys) -------------------------
ENV_URL = "SEALGATE_URL"
ENV_API_KEY = "SEALGATE_API_KEY"
ENV_SECRET_KEY = "SEALGATE_SECRET_KEY"
ENV_CONVERSATION_ID = "SEALGATE_CONVERSATION_ID"
# Fallback conversation-id source, set automatically by some agent runtimes.
# The Rust client honors it too; kept here for wire parity.
ENV_CONVERSATION_ID_FALLBACK = "CENTAUR_THREAD_KEY"
# CA bundle paths for a MITM egress proxy, tried in order (first set wins).
ENV_CA_BUNDLE = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")

# --- defaults & path shape (mirror config.rs::DEFAULT_URL / mcp_url) --------
# Default gateway origin when SEALGATE_URL is unset: the dev endpoint, never a
# guessed prod host. Prod deployments set the env var.
DEFAULT_URL = "http://localhost:3000"
# The MCP endpoint path. With a key it rides in the path; keyless when auth is
# injected upstream by a proxy.
MCP_PATH_WITH_KEY = "/mcp/{key}/"
MCP_PATH_KEYLESS = "/mcp/"

# --- exit codes (mirror gateway_cmd.rs) ------------------------------------
# Client/transport failure (bad config, network, protocol). A normal result is
# the framework default (0) and needs no constant.
EXIT_ERROR = 1
# The gateway returned an MCP tool error (``isError: true``); kept distinct
# from EXIT_ERROR so a caller can tell a failed tool call from a connection
# failure.
EXIT_TOOL_ERROR = 6
