# sealg – SealGate CLI

`sealg` is a thin MCP client to the SealGate gateway. `list` and `call` forward
`tools/list` / `tools/call` to the per-user gateway endpoint, where the gateway
applies all policy and enforcement. `doctor` reports local environment facts,
and `mcp` is a stub for the future MCP transport.

## Build

```bash
cargo build -p sealg
# Binary at target/debug/sealg (or target/release/sealg with --release)
```

## Gateway configuration

The gateway coordinates come from the environment so the binary stays stateless:

- `SEALGATE_URL` – gateway origin (default `http://localhost:3000`). Overridable
  per-invocation with `--gateway-url`.
- `SEALGATE_API_KEY` – API key; embedded in the `/mcp/{key}/` path when set,
  otherwise auth is expected from an upstream injecting proxy.
- `SEALGATE_SECRET_KEY` – zero-knowledge secret key, sent as the
  `sealgate_secret_key` header.
- `SEALGATE_CONVERSATION_ID` (or `CENTAUR_THREAD_KEY`) – stable conversation id.

## Commands

### list

List the user's tools from the live gateway (`tools/list`).

```bash
sealg list
sealg list --json
sealg list --gateway-url https://dashboard.sealgate.ai
```

### call

Call a tool on the live gateway (`tools/call`). The MCP result is pretty-printed;
a result with `isError: true` exits with code `6`.

```bash
sealg call some_tool
sealg call some_tool --args '{"query": "hello"}'
sealg call some_tool --args '{...}' --gateway-url https://dashboard.sealgate.ai
```

### doctor

Collect local environment facts (OS, kernel, headless detection, proxy vars).

```bash
# Human-readable
sealg doctor

# JSON output
sealg doctor --json

# Write result to file
sealg doctor --json --out /tmp/env.json
```

### mcp

Stub for the future MCP transport - prints a notice and exits (`EX_UNAVAILABLE`).

## Exit Codes

- `0` -- success
- `1` -- client/transport failure (bad args, connection error)
- `2` -- clap usage error
- `6` -- the gateway tool call returned an MCP error (`isError: true`)
