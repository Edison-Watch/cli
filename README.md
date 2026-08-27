# SealGate

<p align="center">
  <img src="media/banner.png" alt="banner" width="400">
</p>

<p align="center">
<b>Command-line interface for SealGate, the agentic data firewall</b>
</p>

<p align="center">
  <a href="#key-features">Key Features</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#agent-skills">Agent Skills</a> •
  <a href="#credits">Credits</a>
</p>

<p align="center">
  <img alt="Rust Version" src="https://img.shields.io/badge/rust-1.75%2B-blue?logo=rust">
  <img alt="GitHub repo size" src="https://img.shields.io/github/repo-size/Edison-Watch/cli">
  <img alt="GitHub Actions Workflow Status" src="https://img.shields.io/github/actions/workflow/status/Edison-Watch/cli/rust_checks.yaml?branch=main">
</p>

---

## Key Features

Business logic is written **once** as a typed async `Command` in the `engine`
crate and exposed through the `sealg` binary (with an MCP transport planned).

| Feature | Tech Stack |
|---------|:----------:|
| **Core** | `engine` crate - typed async `Command` registry (no transport deps) |
| **CLI** | `sealg` binary - `call` / `doctor` / `probe` / `run-scenario` |
| **Contract** | `schemars` JSON Schema shared across the CLI and future MCP |
| **Config** | `app-config` crate (YAML + `APP__` env overrides + sanitizer) |
| **Logging** | `tracing` + redaction layer |
| **Packaging** | `cargo-dist` (binaries + installers) |
| **Package Manager** | Bun |
| **Formatting** | Biome + `cargo fmt` |

## Architecture

```
        ┌─────────────────────────────────────────────────────────┐
        │  TRANSPORT  (crates/cli - one binary `sealg`)            │
        │                                                         │
        │   sealg call <cmd> --args '{...}'   one-shot JSON I/O   │
        │   sealg doctor | probe | run-scenario                  │
        │   sealg mcp                          (stub - planned)   │
        └───────────────────────────┬─────────────────────────────┘
                                     │  same registry + typed contract
        ┌────────────────────────────▼─────────────────────────────┐
        │  crates/engine  - the service core (no transport deps)    │
        │    Command trait:  Input: JsonSchema + Deserialize        │
        │                    Output: JsonSchema + Serialize         │
        │    CommandRegistry (inventory self-registration)          │
        │    Ctx (per-request): fs / network capabilities           │
        └───────────────────────────┬─────────────────────────────┘
                                     │
        ┌────────────────────────────▼─────────────────────────────┐
        │  crates/config (app-config) - AppConfig / FrontendConfig  │
        │                 YAML + APP__ env overrides + sanitizer    │
        └───────────────────────────────────────────────────────────┘
```

- `crates/engine/` - all real logic; a typed, async `Command` registry with
  self-registration (`inventory`). No transport dependency.
- `crates/cli/` - the `sealg` binary. The `cli` surface is a cargo feature.
- `crates/config/` - `AppConfig` (with secrets) vs the sanitized
  `FrontendConfig`. The sanitizer is a security boundary.
- `crates/assetgen/` - `asset-gen` binary for `make banner` / `make logo`.

## Quick Start

```bash
# 1. Build + test the workspace
cargo build --workspace
cargo test --workspace

# 2. Call a command headlessly
cargo run -p sealg -- call ping --json
cargo run -p sealg -- call read_file --args '{"path": "/etc/hostname"}' --json
```

Scaffold a new command with `make new name=fetch_url` (or `sealg new
fetch_url`) - it self-registers, so it's immediately callable over the CLI.

## Configuration

Configuration is handled in Rust.

- `app_config::get_config()` (full) / `app_config::get_frontend_config()` (sanitized).

### Environment Variables
Prefix variables with `APP__` to override YAML settings (e.g.,
`APP__MODEL_NAME=gpt-4`). Point a deployed binary at its config file with
`APP_CONFIG_PATH`.

## Agent Skills

Claude Code skills live in `.claude/skills/`. Invoke them with `/skill-name`
(run `/onboarding`, `/update-backend`, `/code-quality`, `/cleanup`, and more).

## Credits

This software uses the following tools:
- [Bun](https://bun.sh/)
- [Biome](https://biomejs.dev/)
- [Rust](https://www.rust-lang.org/)

## About the Core Contributors

<a href="https://github.com/Edison-Watch/cli/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Edison-Watch/cli" />
</a>

Made with [contrib.rocks](https://contrib.rocks).
