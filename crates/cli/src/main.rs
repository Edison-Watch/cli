//! `sealg` – the SealGate command-line interface.
//!
//! A thin MCP client to the SealGate gateway. `list` and `call` forward
//! `tools/list` / `tools/call` to the per-user gateway endpoint (all policy and
//! enforcement live in the gateway). `doctor` reports local environment facts,
//! `init` onboards the template, and `mcp` is a stub for the future MCP
//! transport.

#[cfg(feature = "cli")]
mod diagnostics;
mod gateway_cmd;
mod init;
mod mcp;

use clap::{Parser, Subcommand};

#[cfg(feature = "cli")]
use std::path::PathBuf;

// CLI definition

#[derive(Parser)]
#[command(
    name = "sealg",
    version,
    about = "Command-line interface for SealGate, the agentic data firewall"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Onboard this template into a real project (rename, prune, .env).
    Init(init::InitArgs),

    /// (stub) Expose the gateway over a local MCP transport - not yet implemented.
    Mcp,

    /// Collect environment facts and emit an env summary.
    #[cfg(feature = "cli")]
    Doctor {
        /// Output as JSON instead of human-readable text.
        #[arg(long)]
        json: bool,
        /// Write result JSON to this path.
        #[arg(long)]
        out: Option<PathBuf>,
    },

    /// List the user's tools from the live SealGate gateway.
    List {
        /// Output as a JSON array of {name, description}.
        #[arg(long)]
        json: bool,
        /// Override the gateway base URL (default: $SEALGATE_URL or localhost).
        #[arg(long)]
        gateway_url: Option<String>,
    },

    /// Call a tool on the live SealGate gateway.
    Call {
        /// Tool name as advertised by `sealg list`.
        tool: String,
        /// JSON arguments object to pass to the tool.
        #[arg(long, default_value = "{}")]
        args: String,
        /// Override the gateway base URL (default: $SEALGATE_URL or localhost).
        #[arg(long)]
        gateway_url: Option<String>,
    },
}

// Main

#[tokio::main]
async fn main() {
    // Install ring as the rustls crypto provider (reqwest needs this with rustls-no-provider)
    let _ = rustls::crypto::ring::default_provider().install_default();

    // Initialise tracing for CLI (structured, no config dependency)
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .with_writer(std::io::stderr)
        .init();

    let cli = Cli::parse();

    match cli.command {
        Commands::Init(args) => {
            if let Err(e) = init::run(args) {
                eprintln!("error: {e:#}");
                std::process::exit(1);
            }
        }
        Commands::Mcp => mcp::run(),
        #[cfg(feature = "cli")]
        Commands::Doctor { json, out } => diagnostics::cmd_doctor(json, out).await,
        Commands::List { json, gateway_url } => gateway_cmd::cmd_list(json, gateway_url).await,
        Commands::Call {
            tool,
            args,
            gateway_url,
        } => gateway_cmd::cmd_call(&tool, &args, gateway_url).await,
    }
}
