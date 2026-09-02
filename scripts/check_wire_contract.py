"""Fail if the SealGate wire contract drifts between the Python and Rust clients.

This repo ships two ``sealg`` clients for the same MCP-over-HTTP gateway endpoint:

1. The Rust binary (the canonical source of truth): ``crates/engine/src/gateway/
   config.rs``, ``.../client.rs``, and ``crates/cli/src/gateway_cmd.rs``.
2. The Python client in ``python/sealg/``, whose wire constants live in
   ``contract.py``.

If the two disagree about the protocol version, header names, env-var names, the
``/mcp/{key}/`` path shape, or the tool-error exit code, one client silently
talks to the gateway differently from the other. Because both live in this repo,
this guard reads both directly and always compares them - no cross-repo checkout.

Run: ``python3 scripts/check_wire_contract.py`` (also the ``wire-contract`` prek
hook and the python-cli CI workflow).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = REPO_ROOT / "python" / "sealg" / "contract.py"
CONFIG_RS = REPO_ROOT / "crates" / "engine" / "src" / "gateway" / "config.rs"
CLIENT_RS = REPO_ROOT / "crates" / "engine" / "src" / "gateway" / "client.rs"
GATEWAY_CMD_RS = REPO_ROOT / "crates" / "cli" / "src" / "gateway_cmd.rs"

# The canonical values, asserted against both clients. Editing a value here means
# the wire changed: update contract.py AND the Rust constant to match.
SNAPSHOT = {
    "PROTOCOL_VERSION": "2025-06-18",
    "SECRET_KEY_HEADER": "sealgate_secret_key",
    "CONVERSATION_ID_HEADER": "x-sealgate-conversation-id",
    "ACCEPT": "application/json, text/event-stream",
    "PROTOCOL_VERSION_HEADER": "MCP-Protocol-Version",
    "ENV_URL": "SEALGATE_URL",
    "ENV_API_KEY": "SEALGATE_API_KEY",
    "ENV_SECRET_KEY": "SEALGATE_SECRET_KEY",
    "ENV_CONVERSATION_ID": "SEALGATE_CONVERSATION_ID",
    "ENV_CONVERSATION_ID_FALLBACK": "CENTAUR_THREAD_KEY",
    "ENV_CA_BUNDLE": ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"),
    "DEFAULT_URL": "http://localhost:3000",
    "MCP_PATH_WITH_KEY": "/mcp/{key}/",
    "MCP_PATH_KEYLESS": "/mcp/",
    "EXIT_TOOL_ERROR": 6,
}


def _fail(lines: list[str]) -> None:
    print("sealg wire-contract drift check FAILED:\n", file=sys.stderr)
    for line in lines:
        print(f"  - {line}", file=sys.stderr)
    print(
        "\nThe Python client (python/sealg/contract.py) and the Rust client "
        "(crates/engine/src/gateway/) must agree. Update both, or fix the snapshot "
        "in this script if the wire genuinely changed.",
        file=sys.stderr,
    )
    sys.exit(1)


def _load_contract() -> dict[str, object]:
    # Exec the source text directly rather than importing it: SourceFileLoader
    # caches bytecode in __pycache__ keyed on 1-second mtime granularity, so two
    # edits within the same second can serve a stale .pyc and hide real drift.
    if not CONTRACT_PATH.is_file():
        _fail([f"cannot find {CONTRACT_PATH}"])
    namespace: dict[str, object] = {}
    exec(compile(CONTRACT_PATH.read_text(), str(CONTRACT_PATH), "exec"), namespace)  # noqa: S102
    missing = [k for k in SNAPSHOT if k not in namespace]
    if missing:
        _fail([f"contract.py is missing constant {k}" for k in missing])
    return {k: namespace[k] for k in SNAPSHOT}


def _check_python(contract: dict[str, object], problems: list[str]) -> None:
    for key, want in SNAPSHOT.items():
        got = contract.get(key)
        if got != want:
            problems.append(f"contract.py {key} = {got!r}, expected {want!r}")


def _rust_str_const(text: str, name: str) -> str | None:
    m = re.search(rf'const\s+{re.escape(name)}\s*:\s*&str\s*=\s*"([^"]*)"', text)
    return m.group(1) if m else None


def _rust_str_list(text: str, name: str) -> tuple[str, ...] | None:
    m = re.search(
        rf"const\s+{re.escape(name)}\s*:\s*&\[&str\]\s*=\s*&\[([^\]]*)\]", text
    )
    if not m:
        return None
    return tuple(re.findall(r'"([^"]*)"', m.group(1)))


def _rust_int_const(text: str, name: str) -> int | None:
    m = re.search(rf"const\s+{re.escape(name)}\s*:\s*i32\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def _rust_mcp_path_shapes(text: str) -> tuple[str | None, str | None]:
    """Extract the with-key and keyless path shapes from config.rs `mcp_url`.

    Rust builds them as ``format!("{}/mcp/{}/", base, key)`` and
    ``format!("{}/mcp/", base)``. Strip the leading ``{}`` (base_url) and
    normalize the key placeholder ``{}`` -> ``{key}`` so the shapes compare to
    the Python constants. The two clients hitting different URLs is the worst
    drift, so it gets an explicit extractor.
    """
    with_key = keyless = None
    for fmt in re.findall(r'format!\(\s*"([^"]*)"', text):
        if not fmt.startswith("{}/mcp/"):
            continue
        suffix = fmt[len("{}") :]
        if "{}" in suffix:
            with_key = suffix.replace("{}", "{key}")
        else:
            keyless = suffix
    return with_key, keyless


def _check_rust(problems: list[str]) -> None:
    for path in (CONFIG_RS, CLIENT_RS, GATEWAY_CMD_RS):
        if not path.is_file():
            _fail([f"cannot find Rust source {path} (repo layout moved)"])
    config = CONFIG_RS.read_text()
    client = CLIENT_RS.read_text()
    gateway_cmd = GATEWAY_CMD_RS.read_text()

    mcp_with_key, mcp_keyless = _rust_mcp_path_shapes(config)

    # (snapshot key, value parsed from Rust, human name of the Rust symbol)
    checks: list[tuple[str, object, str]] = [
        (
            "PROTOCOL_VERSION",
            _rust_str_const(client, "PROTOCOL_VERSION"),
            "PROTOCOL_VERSION",
        ),
        (
            "SECRET_KEY_HEADER",
            _rust_str_const(config, "SECRET_KEY_HEADER"),
            "SECRET_KEY_HEADER",
        ),
        (
            "CONVERSATION_ID_HEADER",
            _rust_str_const(config, "CONVERSATION_ID_HEADER"),
            "CONVERSATION_ID_HEADER",
        ),
        ("DEFAULT_URL", _rust_str_const(config, "DEFAULT_URL"), "DEFAULT_URL"),
        ("ENV_URL", _rust_str_const(config, "URL"), "env_keys::URL"),
        ("ENV_API_KEY", _rust_str_const(config, "API_KEY"), "env_keys::API_KEY"),
        (
            "ENV_SECRET_KEY",
            _rust_str_const(config, "SECRET_KEY"),
            "env_keys::SECRET_KEY",
        ),
        (
            "ENV_CONVERSATION_ID",
            _rust_str_const(config, "CONVERSATION_ID"),
            "env_keys::CONVERSATION_ID",
        ),
        (
            "ENV_CONVERSATION_ID_FALLBACK",
            _rust_str_const(config, "CENTAUR_THREAD_KEY"),
            "env_keys::CENTAUR_THREAD_KEY",
        ),
        ("ENV_CA_BUNDLE", _rust_str_list(config, "CA_BUNDLE"), "env_keys::CA_BUNDLE"),
        ("MCP_PATH_WITH_KEY", mcp_with_key, "mcp_url (with-key format!)"),
        ("MCP_PATH_KEYLESS", mcp_keyless, "mcp_url (keyless format!)"),
        (
            "EXIT_TOOL_ERROR",
            _rust_int_const(gateway_cmd, "EXIT_TOOL_ERROR"),
            "EXIT_TOOL_ERROR",
        ),
    ]
    for snap_key, got, rust_name in checks:
        want = SNAPSHOT[snap_key]
        if got is None:
            problems.append(f"could not find Rust {rust_name} (parser or source moved)")
        elif got != want:
            problems.append(
                f"Rust {rust_name} = {got!r}, expected {want!r} (contract.py {snap_key})"
            )

    # The Accept + protocol-version headers are string literals in client.rs's
    # request builder. Anchor to the `.header(...)` call so a stale copy of the
    # literal elsewhere (a comment, a test) can't satisfy the check.
    accept = re.escape(str(SNAPSHOT["ACCEPT"]))
    ver_header = re.escape(str(SNAPSHOT["PROTOCOL_VERSION_HEADER"]))
    header_checks = [
        ("ACCEPT", rf'\.header\(\s*[^,]*ACCEPT\s*,\s*"{accept}"'),
        ("PROTOCOL_VERSION_HEADER", rf'\.header\(\s*"{ver_header}"\s*,'),
    ]
    for snap_key, pattern in header_checks:
        if not re.search(pattern, client):
            problems.append(
                f"Rust client.rs request builder no longer sets {snap_key} = "
                f"{SNAPSHOT[snap_key]!r} (parser or request builder moved)"
            )


def main() -> None:
    problems: list[str] = []
    contract = _load_contract()
    _check_python(contract, problems)
    _check_rust(problems)
    if problems:
        _fail(problems)
    print(f"sealg wire-contract OK: {len(SNAPSHOT)} constants agree [Python + Rust]")


if __name__ == "__main__":
    main()
