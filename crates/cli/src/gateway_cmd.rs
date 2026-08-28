//! Gateway-backed subcommands for `sealg`.
//!
//! `sealg` is a thin MCP client: these subcommands resolve the gateway
//! coordinates from the environment ([`GatewayConfig::from_env`]), run the MCP
//! `initialize` handshake, and forward `tools/list` / `tools/call` to the
//! per-user gateway endpoint. All policy and enforcement lives in the gateway.

use engine::{GatewayClient, GatewayConfig, GatewayError};
use serde_json::{json, Value};
use std::time::Duration;

/// Timeout for the connect + a single request round-trip.
const TIMEOUT: Duration = Duration::from_secs(30);

/// `sealg list [--json]` — list the user's gateway tools.
pub async fn cmd_list(json_out: bool) {
    if let Err(e) = run_list(json_out).await {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}

async fn run_list(json_out: bool) -> Result<(), GatewayError> {
    let cfg = GatewayConfig::from_env();
    let client = GatewayClient::connect(cfg, TIMEOUT).await?;
    let tools = client.tools_list().await?;

    if json_out {
        let arr: Vec<Value> = tools
            .iter()
            .map(|t| json!({ "name": t.name, "description": t.description }))
            .collect();
        println!(
            "{}",
            serde_json::to_string_pretty(&Value::Array(arr)).unwrap_or_else(|_| "[]".to_string())
        );
    } else {
        for t in &tools {
            println!("{}  —  {}", t.name, t.description);
        }
    }
    Ok(())
}

/// `sealg gw-call <tool> [--args '<json>'] [--json]` — call one gateway tool.
pub async fn cmd_call(tool: &str, args: &str) {
    match run_call(tool, args).await {
        Ok(exit_code) => std::process::exit(exit_code),
        Err(e) => {
            eprintln!("error: {e}");
            std::process::exit(1);
        }
    }
}

/// Returns the process exit code: `0` on a normal result, non-zero when the
/// gateway returns an MCP tool error (`isError: true`) — the result is still
/// printed so the caller sees the error content.
async fn run_call(tool: &str, args: &str) -> Result<i32, GatewayError> {
    let arguments: Value = serde_json::from_str(args)
        .map_err(|e| GatewayError::Config(format!("invalid --args JSON: {e}")))?;

    let cfg = GatewayConfig::from_env();
    let client = GatewayClient::connect(cfg, TIMEOUT).await?;
    let result = client.tools_call(tool, arguments).await?;

    println!(
        "{}",
        serde_json::to_string_pretty(&result).unwrap_or_else(|_| result.to_string())
    );

    // Mirror the MCP tool-call response: an `isError: true` result is a failed
    // call and must not exit 0.
    let is_error = result.get("isError").and_then(Value::as_bool) == Some(true);
    Ok(if is_error { 6 } else { 0 })
}
