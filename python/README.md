# sealg (Python)

A Python client for the SealGate gateway, exposing the same `sealg` CLI as the
Rust binary in this repo. It is a thin MCP-over-HTTP client: `sealg list` /
`sealg call` forward `tools/list` / `tools/call` to your per-user gateway
endpoint, where all policy and enforcement live. It carries no policy of its own.

It exists alongside the Rust `sealg` because a `uvx`-installable Python package
drops into environments that reach for `uvx`/`pip` rather than a native binary.
The two clients are kept from drifting by `scripts/check_wire_contract.py` (a
pre-commit + CI check): every shared wire constant lives once in
`sealg/contract.py` and is checked against the Rust source in `crates/`.

## Install and run

```
uvx --from python/ sealg doctor                    # from a checkout
uvx --from 'git+https://github.com/Edison-Watch/cli#subdirectory=python' sealg list
```

Or `pip install ./python` into a virtualenv, then run `sealg`.

## Commands

```
sealg doctor                     # resolved gateway env + reachability probe
sealg list [--json]              # tools your org has authorized
sealg call <tool> [--args '{}']  # invoke one tool
```

Exit codes mirror the Rust CLI: `0` ok, `1` client/transport error, `6` the
gateway returned an MCP tool error (`isError: true`).

## Configuration

All from the environment (see `.env.example`): `SEALGATE_URL`,
`SEALGATE_API_KEY` (optional - keyless when auth is injected upstream by a
proxy), `SEALGATE_SECRET_KEY`, `SEALGATE_CONVERSATION_ID` (with a
`CENTAUR_THREAD_KEY` fallback that some agent runtimes set automatically), and a
CA bundle via `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `NODE_EXTRA_CA_CERTS` for
a MITM egress proxy.
