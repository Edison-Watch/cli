//! The SealGate gateway transport.
//!
//! `sealg` is a thin client: it forwards tool calls to the per-user MCP endpoint
//! (`/mcp/{api_key}/`), where the gateway applies all policy, trifecta, and PII
//! enforcement. This module is the whole of that transport — config resolved
//! from the environment ([`config`]) and a hand-rolled MCP client ([`client`]).
//!
//! It deliberately does **not** live in the [`commands`](crate::commands)
//! registry: gateway tools are dynamic and per-user (discovered at runtime via
//! `tools/list`), the opposite of the registry's static, compile-time commands.

pub mod client;
pub mod config;

pub use client::{GatewayClient, GatewayError, ToolInfo, PROTOCOL_VERSION};
pub use config::{GatewayConfig, CONVERSATION_ID_HEADER, DEFAULT_URL, SECRET_KEY_HEADER};
