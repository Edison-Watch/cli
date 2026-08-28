//! Hand-rolled MCP client over Streamable HTTP.
//!
//! `sealg` speaks the small slice of MCP it needs — `initialize`, `tools/list`,
//! `tools/call` — directly to the gateway's `/mcp/{api_key}/` endpoint. No
//! `rmcp` dependency: the binary stays thin and cold-starts fast (see the
//! design doc §5A). Transport: MCP Streamable HTTP, protocol `2025-06-18`
//! (the version the gateway's FastMCP server accepts).
//! <https://modelcontextprotocol.io/specification/2025-06-18>

use super::config::{GatewayConfig, CONVERSATION_ID_HEADER, SECRET_KEY_HEADER};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

/// Protocol version `sealg` advertises in `initialize`. Must be a version the
/// gateway's MCP server (FastMCP) actually supports — it rejects unknown
/// versions with JSON-RPC -32600. `2025-06-18` is the current stable MCP spec.
pub const PROTOCOL_VERSION: &str = "2025-06-18";

/// A tool as advertised by the gateway's `tools/list`.
#[derive(Debug, Clone)]
pub struct ToolInfo {
    pub name: String,
    pub description: String,
    /// The tool's JSON Schema for arguments (`inputSchema`).
    pub input_schema: Value,
}

#[derive(Debug, thiserror::Error)]
pub enum GatewayError {
    #[error("config: {0}")]
    Config(String),
    #[error("network: {0}")]
    Network(String),
    #[error("timeout")]
    Timeout,
    /// A JSON-RPC error returned by the gateway. Mirrors the MCP error shape so
    /// callers map it to exit codes without a bespoke taxonomy (design §5, B3).
    #[error("rpc error {code}: {message}")]
    Rpc {
        code: i64,
        message: String,
        data: Value,
    },
    #[error("protocol: {0}")]
    Protocol(String),
}

/// A live connection to the gateway's per-user MCP endpoint.
pub struct GatewayClient {
    http: reqwest::Client,
    url: String,
    cfg: GatewayConfig,
    session_id: Option<String>,
    next_id: AtomicU64,
}

impl GatewayClient {
    /// Build the HTTP client (honoring `HTTPS_PROXY` via reqwest's system proxy,
    /// plus any MITM CA bundle named in the environment) and run the MCP
    /// `initialize` handshake.
    pub async fn connect(cfg: GatewayConfig, timeout: Duration) -> Result<Self, GatewayError> {
        let mut builder = reqwest::Client::builder().timeout(timeout);

        if let Some(path) = &cfg.ca_bundle {
            let pem = std::fs::read(path)
                .map_err(|e| GatewayError::Config(format!("read CA bundle {path}: {e}")))?;
            let certs = reqwest::Certificate::from_pem_bundle(&pem)
                .map_err(|e| GatewayError::Config(format!("parse CA bundle {path}: {e}")))?;
            for cert in certs {
                builder = builder.add_root_certificate(cert);
            }
        }

        let http = builder
            .build()
            .map_err(|e| GatewayError::Network(format!("build HTTP client: {e}")))?;

        let url = cfg.mcp_url();
        let mut client = Self {
            http,
            url,
            cfg,
            session_id: None,
            next_id: AtomicU64::new(1),
        };
        client.initialize().await?;
        Ok(client)
    }

    async fn initialize(&mut self) -> Result<(), GatewayError> {
        let params = json!({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": { "name": "sealg", "version": env!("CARGO_PKG_VERSION") },
        });
        // initialize is the one call that may hand back a session id (header).
        let (result, session_id) = self.rpc_capture_session("initialize", params).await?;
        let _ = result;
        self.session_id = session_id;
        // Best-effort readiness notification; stateless servers may ignore it.
        let _ = self.notify("notifications/initialized", json!({})).await;
        Ok(())
    }

    /// `tools/list` → the gateway's per-user, policy-filtered tool set.
    pub async fn tools_list(&self) -> Result<Vec<ToolInfo>, GatewayError> {
        let result = self.rpc("tools/list", json!({})).await?;
        let tools = result
            .get("tools")
            .and_then(Value::as_array)
            .ok_or_else(|| GatewayError::Protocol("tools/list missing `tools` array".into()))?;
        Ok(tools.iter().map(tool_from_value).collect())
    }

    /// `tools/call` → the raw MCP result value (content blocks, `isError`).
    /// Returned verbatim so the caller mirrors the MCP response (design B3).
    pub async fn tools_call(&self, name: &str, arguments: Value) -> Result<Value, GatewayError> {
        let args = if arguments.is_null() {
            json!({})
        } else {
            arguments
        };
        self.rpc("tools/call", json!({ "name": name, "arguments": args }))
            .await
    }

    // --- transport ---------------------------------------------------------

    fn next_id(&self) -> u64 {
        self.next_id.fetch_add(1, Ordering::Relaxed)
    }

    async fn rpc(&self, method: &str, params: Value) -> Result<Value, GatewayError> {
        Ok(self.rpc_capture_session(method, params).await?.0)
    }

    /// Send a JSON-RPC request and return (`result`, any `Mcp-Session-Id`).
    async fn rpc_capture_session(
        &self,
        method: &str,
        params: Value,
    ) -> Result<(Value, Option<String>), GatewayError> {
        let id = self.next_id();
        let body = json!({ "jsonrpc": "2.0", "id": id, "method": method, "params": params });

        let resp = self
            .request(&body)
            .send()
            .await
            .map_err(|e| self.map_send_err(e))?;

        let session_id = resp
            .headers()
            .get("mcp-session-id")
            .and_then(|v| v.to_str().ok())
            .map(str::to_string);

        let status = resp.status();
        let content_type = resp
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_string();
        let text = resp
            .text()
            .await
            .map_err(|e| GatewayError::Network(format!("reading response body: {e}")))?;

        if !status.is_success() {
            // HTTP-level failure with no JSON-RPC envelope (auth, 404, 5xx).
            return Err(GatewayError::Network(format!(
                "gateway returned HTTP {}: {}",
                status.as_u16(),
                text.chars().take(512).collect::<String>()
            )));
        }

        let result = extract_rpc_result(&content_type, &text, id)?;
        Ok((result, session_id))
    }

    async fn notify(&self, method: &str, params: Value) -> Result<(), GatewayError> {
        // A notification has no `id` and expects no response body.
        let body = json!({ "jsonrpc": "2.0", "method": method, "params": params });
        self.request(&body)
            .send()
            .await
            .map_err(|e| self.map_send_err(e))?;
        Ok(())
    }

    /// Build a POST with the MCP + SealGate headers attached.
    fn request(&self, body: &Value) -> reqwest::RequestBuilder {
        let mut req = self
            .http
            .post(&self.url)
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .header(
                reqwest::header::ACCEPT,
                "application/json, text/event-stream",
            )
            .header("MCP-Protocol-Version", PROTOCOL_VERSION)
            .json(body);

        if let Some(sid) = &self.session_id {
            req = req.header("Mcp-Session-Id", sid);
        }
        if let Some(secret) = &self.cfg.secret_key {
            req = req.header(SECRET_KEY_HEADER, secret);
        }
        if let Some(conv) = &self.cfg.conversation_id {
            req = req.header(CONVERSATION_ID_HEADER, conv);
        }
        req
    }

    fn map_send_err(&self, e: reqwest::Error) -> GatewayError {
        if e.is_timeout() {
            GatewayError::Timeout
        } else {
            GatewayError::Network(format!("POST {}: {}", self.url, e))
        }
    }
}

fn tool_from_value(v: &Value) -> ToolInfo {
    ToolInfo {
        name: v
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        description: v
            .get("description")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        input_schema: v.get("inputSchema").cloned().unwrap_or(Value::Null),
    }
}

/// Extract the JSON-RPC `result` for `want_id` from a response body that is
/// either `application/json` (one response object) or `text/event-stream` (SSE
/// frames, each `data:` line a JSON-RPC message). Pure, so it is unit-tested.
pub fn extract_rpc_result(
    content_type: &str,
    body: &str,
    want_id: u64,
) -> Result<Value, GatewayError> {
    let msg = if content_type.contains("text/event-stream") {
        sse_find_response(body, want_id)
            .ok_or_else(|| GatewayError::Protocol("no JSON-RPC response in SSE stream".into()))?
    } else {
        serde_json::from_str::<Value>(body.trim())
            .map_err(|e| GatewayError::Protocol(format!("invalid JSON response: {e}")))?
    };
    rpc_message_to_result(&msg)
}

/// Turn one JSON-RPC response object into `Ok(result)` / `Err(Rpc)`.
fn rpc_message_to_result(msg: &Value) -> Result<Value, GatewayError> {
    if let Some(err) = msg.get("error") {
        return Err(GatewayError::Rpc {
            code: err.get("code").and_then(Value::as_i64).unwrap_or(0),
            message: err
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or("unknown error")
                .to_string(),
            data: err.get("data").cloned().unwrap_or(Value::Null),
        });
    }
    msg.get("result").cloned().ok_or_else(|| {
        GatewayError::Protocol("JSON-RPC response had neither result nor error".into())
    })
}

/// Scan SSE frames for the JSON-RPC response matching `want_id`.
fn sse_find_response(body: &str, want_id: u64) -> Option<Value> {
    let mut fallback: Option<Value> = None;
    for line in body.lines() {
        let line = line.trim_start();
        let Some(data) = line.strip_prefix("data:") else {
            continue;
        };
        let Ok(v) = serde_json::from_str::<Value>(data.trim()) else {
            continue;
        };
        // Only responses carry result/error.
        if v.get("result").is_none() && v.get("error").is_none() {
            continue;
        }
        if v.get("id").and_then(Value::as_u64) == Some(want_id) {
            return Some(v);
        }
        fallback.get_or_insert(v);
    }
    fallback
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_json_result() {
        let body = r#"{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}"#;
        let r = extract_rpc_result("application/json", body, 1).unwrap();
        assert!(r.get("tools").unwrap().as_array().unwrap().is_empty());
    }

    #[test]
    fn json_rpc_error_maps_to_rpc_variant() {
        let body = r#"{"jsonrpc":"2.0","id":2,"error":{"code":-32000,"message":"blocked by policy","data":{"rule":"trifecta"}}}"#;
        let err = extract_rpc_result("application/json", body, 2).unwrap_err();
        match err {
            GatewayError::Rpc {
                code,
                message,
                data,
            } => {
                assert_eq!(code, -32000);
                assert_eq!(message, "blocked by policy");
                assert_eq!(data["rule"], "trifecta");
            }
            other => panic!("expected Rpc, got {other:?}"),
        }
    }

    #[test]
    fn sse_stream_picks_matching_id() {
        let body =
            "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":7,\"result\":{\"ok\":true}}\n\n";
        let r = extract_rpc_result("text/event-stream; charset=utf-8", body, 7).unwrap();
        assert_eq!(r["ok"], true);
    }

    #[test]
    fn sse_skips_notifications_and_finds_response() {
        let body =
            "data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/message\",\"params\":{}}\n\
                    data: {\"jsonrpc\":\"2.0\",\"id\":3,\"result\":{\"done\":1}}\n";
        let r = extract_rpc_result("text/event-stream", body, 3).unwrap();
        assert_eq!(r["done"], 1);
    }

    #[test]
    fn invalid_json_is_protocol_error() {
        let err = extract_rpc_result("application/json", "not json", 1).unwrap_err();
        assert!(matches!(err, GatewayError::Protocol(_)));
    }
}
