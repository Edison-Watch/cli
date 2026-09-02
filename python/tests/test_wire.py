"""Unit tests for the SealGate Python client's wire behavior.

Ported from the Rust client's tests (``crates/engine/src/gateway/config.rs`` and
``client.rs``) so the two implementations behave identically on the parts that
matter: config resolution, key-in-path, conversation-id fallback, CA-bundle
precedence, JSON/SSE result extraction, redirect/status handling, and URL
redaction. The wire *constants* are covered separately by
``scripts/check_wire_contract.py``; these cover the *logic*.

Run: ``uv run --with httpx --with pytest pytest python/tests``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

# Import the package straight from the source dir (no install needed).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sealg import client  # noqa: E402
from sealg.client import GatewayConfig, GatewayError, RpcError, redact_url  # noqa: E402

_extract = client._extract_rpc_result


# --- config resolution (ports config.rs tests) -----------------------------


def test_defaults_when_unset():
    c = GatewayConfig.from_env(env={})
    assert c.base_url == "http://localhost:3000"
    assert c.api_key is None
    assert c.mcp_url() == "http://localhost:3000/mcp/"
    assert c.auth_mode() == "proxy-injected"


def test_key_goes_in_the_path_and_trailing_slash_is_trimmed():
    c = GatewayConfig.from_env(
        env={
            "SEALGATE_URL": "https://dashboard.sealgate.ai/",
            "SEALGATE_API_KEY": "ew_live_abc",
        }
    )
    assert c.base_url == "https://dashboard.sealgate.ai"
    assert c.mcp_url() == "https://dashboard.sealgate.ai/mcp/ew_live_abc/"
    assert c.auth_mode() == "env-key"


def test_conversation_id_falls_back():
    c = GatewayConfig.from_env(env={"CENTAUR_THREAD_KEY": "slack:C123:171.45"})
    assert c.conversation_id == "slack:C123:171.45"
    c = GatewayConfig.from_env(
        env={"SEALGATE_CONVERSATION_ID": "explicit", "CENTAUR_THREAD_KEY": "fallback"}
    )
    assert c.conversation_id == "explicit"


def test_ca_bundle_tries_paths_in_order():
    c = GatewayConfig.from_env(env={"REQUESTS_CA_BUNDLE": "/certs/ca.pem"})
    assert c.ca_bundle == "/certs/ca.pem"
    c = GatewayConfig.from_env(
        env={"SSL_CERT_FILE": "/a.pem", "REQUESTS_CA_BUNDLE": "/b.pem"}
    )
    assert c.ca_bundle == "/a.pem"


def test_url_override_trims_and_ignores_blank():
    c = GatewayConfig.from_env(env={}, url_override="https://gw.example.com/")
    assert c.base_url == "https://gw.example.com"
    for degenerate in ("   ", "/", "///", "  //  "):
        c = GatewayConfig.from_env(
            env={"SEALGATE_URL": "https://keep.example"}, url_override=degenerate
        )
        assert c.base_url == "https://keep.example"


def test_blank_values_treated_as_unset():
    c = GatewayConfig.from_env(env={"SEALGATE_URL": "   ", "SEALGATE_API_KEY": ""})
    assert c.base_url == "http://localhost:3000"
    assert c.api_key is None


# --- result extraction (ports client.rs tests) -----------------------------


def test_plain_json_result():
    r = _extract(
        "application/json", '{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}', 1
    )
    assert r["tools"] == []


def test_json_rpc_error_maps_to_rpc_error():
    body = '{"jsonrpc":"2.0","id":2,"error":{"code":-32000,"message":"blocked by policy","data":{"rule":"trifecta"}}}'
    with pytest.raises(RpcError) as ei:
        _extract("application/json", body, 2)
    assert ei.value.code == -32000
    assert ei.value.message == "blocked by policy"
    assert ei.value.data == {"rule": "trifecta"}


def test_sse_stream_picks_matching_id():
    body = 'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"ok":true}}\n\n'
    assert _extract("text/event-stream; charset=utf-8", body, 7)["ok"] is True


def test_sse_skips_notifications_and_finds_response():
    body = (
        'data: {"jsonrpc":"2.0","method":"notifications/message","params":{}}\n'
        'data: {"jsonrpc":"2.0","id":3,"result":{"done":1}}\n'
    )
    assert _extract("text/event-stream", body, 3)["done"] == 1


def test_invalid_json_is_protocol_error():
    with pytest.raises(GatewayError):
        _extract("application/json", "not json", 1)


# --- redaction (ports client.rs redact test) -------------------------------


def test_redact_url_hides_the_api_key():
    out = redact_url("https://gw.example/mcp/ew_live_SECRET/", "ew_live_SECRET")
    assert "ew_live_SECRET" not in out
    assert out == "https://gw.example/mcp/***/"
    assert redact_url("https://gw.example/mcp/", None) == "https://gw.example/mcp/"
    assert (
        redact_url("https://abc.example/mcp/abc/", "abc")
        == "https://abc.example/mcp/***/"
    )


# --- HTTP status / redirect handling (match reqwest) -----------------------


def _mock_client(handler):
    cfg = GatewayConfig.from_env(
        env={"SEALGATE_URL": "https://gw.test", "SEALGATE_API_KEY": "k"}
    )
    gc = client.GatewayClient(cfg)
    gc._http = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    return gc


def test_client_follows_redirects_by_default():
    cfg = GatewayConfig.from_env(env={"SEALGATE_URL": "https://gw.test"})
    gc = client.GatewayClient(cfg)
    try:
        assert gc._http.follow_redirects is True
    finally:
        gc.close()


def test_non_2xx_is_http_error_not_parse_error():
    gc = _mock_client(lambda request: httpx.Response(500, text="boom"))
    try:
        with pytest.raises(GatewayError) as ei:
            gc._rpc("tools/list", {})
        assert "HTTP 500" in str(ei.value)
    finally:
        gc.close()


def test_3xx_is_followed_to_the_result():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/mcp/k/":
            return httpx.Response(307, headers={"location": "https://gw.test/mcp/k2/"})
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        )

    gc = _mock_client(handler)
    try:
        assert gc._rpc("tools/list", {}) == {"tools": []}
    finally:
        gc.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
