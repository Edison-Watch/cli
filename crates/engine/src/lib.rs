//! Engine crate – the shared service core for SealGate.
//!
//! `sealg` is a thin MCP client to the SealGate gateway. This crate holds the
//! transport-agnostic pieces it needs: the gateway client/config
//! ([`gateway`]), the environment diagnostics behind `doctor`, and the shared
//! result contract in [`types`]. It carries no CLI or HTTP types.

pub mod doctor;
mod env;
pub mod gateway;
pub mod types;

// Re-exports for convenience
pub use gateway::{GatewayClient, GatewayConfig, GatewayError, ToolInfo};
pub use types::{CommandResult, ErrorCode, ErrorInfo, Status};
