# sealg – SealGate CLI

The `sealg` binary drives the shared `engine` command registry over the CLI
(`call` / `probe` / `doctor` / `run-scenario`). `new` scaffolds a command, and
`mcp` is a stub for the future MCP transport.

## Build

```bash
cargo build -p sealg
# Binary at target/debug/sealg (or target/release/sealg with --release)
```

## Commands

### doctor

Collect environment facts (OS, kernel, headless detection, proxy vars).

```bash
# Human-readable
sealg doctor

# JSON output
sealg doctor --json

# Write result to file
sealg doctor --json --out /tmp/env.json
```

### call

Invoke a backend command by name with JSON arguments.

```bash
# Ping (prove wiring works)
sealg call ping --json

# Read a file
sealg call read_file --args '{"path": "/etc/hostname"}' --json

# Write a file
sealg call write_file --args '{"path": "/tmp/test.txt", "content": "hello"}' --json

# With artifacts directory
sealg call ping --json --artifacts /tmp/artifacts
```

### probe

Targeted capability checks.

```bash
# Filesystem probe (create/read/write/delete in temp dir)
sealg probe filesystem --json

# Network probe (DNS resolve + HTTPS GET)
sealg probe network --json
```

### run-scenario

Execute a scripted scenario from a YAML file.

```yaml
# scenario.yaml
name: basic smoke test
steps:
  - call: "ping"
    args: {}
    expect_status: "pass"
  - call: "write_file"
    args:
      path: "/tmp/scenario_test.txt"
      content: "written by scenario"
    expect_status: "pass"
  - call: "read_file"
    args:
      path: "/tmp/scenario_test.txt"
    expect_status: "pass"
  - probe: "filesystem"
```

```bash
sealg run-scenario scenario.yaml --json
sealg run-scenario scenario.yaml --artifacts /tmp/artifacts
```

### mcp

Stub for the future MCP transport - prints a notice and exits (`EX_UNAVAILABLE`).

## Output Contract

The CLI wraps command output in a diagnostic envelope with this stable JSON
schema:

```json
{
  "run_id": "uuid",
  "command": "call|probe|doctor|run-scenario",
  "target": "<cmd or probe name>",
  "status": "pass|fail|skip|error",
  "error": { "code": "ERROR_CODE", "message": "..." },
  "timing_ms": { "total": 1234, "steps": { "init": 10, "work": 1200 } },
  "artifacts": [],
  "env_summary": { "os": "linux|macos", "arch": "x86_64|aarch64", "headless": true },
  "data": {}
}
```

Error codes: `INVALID_INPUT`, `UNSUPPORTED`, `UNIMPLEMENTED`, `DEPENDENCY_MISSING`,
`PERMISSION_DENIED`, `NETWORK_ERROR`, `IO_ERROR`, `TIMEOUT`, `EXTERNAL_INTERFERENCE`,
`INTERNAL_ERROR`.

## Artifacts

When `--artifacts <dir>` is provided, the CLI writes:

```
<dir>/<run_id>/
  result.json      # Full result object
  events.jsonl     # JSON Lines log of events
```

## Exit Codes

- `0` -- pass or skip
- `1` -- fail
- `2` -- error
