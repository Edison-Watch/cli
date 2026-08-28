This file provides guidance to AI agents working with code in this repository.

## Project Overview

SealGate's command-line interface. `sealg` is a thin MCP client to the SealGate
gateway: `list` and `call` forward `tools/list` / `tools/call` to the per-user
gateway endpoint, where all policy and enforcement live. The `engine` core holds
the gateway client/config plus local `doctor` diagnostics and has no transport
dependency.
**Before any other work in this repo, enable prek:** `bun add -g prek && prek install`. Hooks are defined in `prek.toml`.

## Common Commands

```bash
cargo test --workspace  # Run Rust tests
cargo clippy --workspace --all-targets -- -D warnings
sealg list              # List the user's tools from the gateway
sealg call <tool> --args '{...}'  # Call a gateway tool via tools/call
```

## Architecture

- **crates/engine/** - `GatewayConfig` (env-resolved coordinates) + `GatewayClient`
  (hand-rolled MCP-over-HTTP client), plus `doctor` env facts. No transport deps.
- **crates/cli/** - the `sealg` binary; the `cli` surface is a cargo feature.
- **crates/config/** - crate `app-config`; `AppConfig` (secrets) vs sanitized
  `FrontendConfig`. The sanitizer is a security boundary.

> **Making backend changes?** Use the `update-backend` skill for architecture details, command patterns, trait implementations, config access, and `sealg` testing workflows.

## Code Style

Enforced by Biome (TS) and `cargo fmt` + Clippy (Rust). See `biome.json`.

## Configuration Pattern

Configuration is handled in Rust. Source of truth:
`crates/config/global_config.yaml` (`.env` / `APP__`-prefixed env overrides;
`APP_CONFIG_PATH` for a deployed binary).

```rust
let config = app_config::get_config();
println!("Model: {}", config.default_llm.default_model);
```

## Commit Message Convention

Use emoji prefixes indicating change type and magnitude (multiple emojis = 5+ files):
- 🏗️ initial implementation
- 🔨 feature changes
- 🐛 bugfix
- ✨ formatting/linting only
- ✅ feature complete with E2E tests
- ⚙️ config changes
- 💽 DB schema/migrations

## Long-Running Code Pattern

Structure as: `init()` → `continue(id)` → `cleanup(id)`
- Keep state serializable
- Use descriptive IDs (runId, taskId)
- Handle rate limits, timeouts, retries at system boundaries

## Subagents

- Folder-size CI failure → spawn subagent `.claude/agents/folder-refactor-advisor.md`.

## Dual-tool config (Claude + Codex)

Skills and subagents are shared with Codex CLI. Shared skills live in
`.agents/skills/<name>/SKILL.md` (symlinked into `.claude/skills/`); subagents
in `.claude/agents/<name>.md` are the source of truth and generate
`.codex/agents/<name>.toml`. After editing anything under `.claude/skills/`,
`.claude/agents/`, `.agents/skills/`, or `.codex/agents/`, run
`make sync-agent-config` (prek enforces zero drift). See the `manage-agent-config`
skill and `.claude/rules/codex-claude-sync.md`.

## Git Workflow
- **Protected Branch**: `main` is protected. Do not push directly to `main`. Use PRs.
- **Merge Strategy**: Squash and merge.
- **Pre-commit CI gate**: Always run `make ci` before committing any changes. Ensure it passes with zero errors. Do not commit if `make ci` fails - fix all issues first, then commit.
- **Prek hooks**: Always run `prek install` before starting work on a new PR to ensure Git hooks are active.
