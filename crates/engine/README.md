# engine – Shared Backend Logic

The transport-agnostic service core of SealGate. `sealg` (`crates/cli`) is a thin
MCP client to the SealGate gateway; this crate holds the pieces it needs behind a
clean, transport-free API (no CLI, axum, or HTTP types).

## Design Principles

- **No transport dependency** – the engine never imports CLI or HTTP framework
  types, so it can run in any Rust context (CLI, tests, etc.).
- **Thin gateway client** – `sealg` speaks only the small slice of MCP it needs
  (`initialize`, `tools/list`, `tools/call`) directly to the gateway's per-user
  `/mcp/{api_key}/` endpoint. All policy and enforcement live in the gateway.
- **Structured results** – `doctor` returns a `CommandResult` with a stable JSON
  schema including `run_id`, `status`, `error`, `timing_ms`, and `env_summary`.

## Modules

| Module | Purpose |
|--------|---------|
| `gateway` | The SealGate gateway transport: `GatewayConfig` (env-resolved coordinates) and `GatewayClient` (hand-rolled MCP-over-HTTP client) |
| `doctor` | Environment diagnostics (OS, kernel, headless detection, proxy vars) |
| `types` | Output contract: `CommandResult`, `Status`, `ErrorCode`, `EnvSummary` |

## Usage

```rust
use engine::{GatewayClient, GatewayConfig};
use std::time::Duration;

// Coordinates come from the environment ($SEALGATE_URL, $SEALGATE_API_KEY, …).
let cfg = GatewayConfig::from_env();
let client = GatewayClient::connect(cfg, Duration::from_secs(30)).await?;

// Discover and call the user's policy-filtered gateway tools.
let tools = client.tools_list().await?;
let result = client.tools_call("some_tool", serde_json::json!({})).await?;
```
