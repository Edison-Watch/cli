//! `sealg mcp` - placeholder for a future local MCP transport.
//!
//! Planned: expose the SealGate gateway over a local (stdio) MCP server so an
//! MCP client (Claude Desktop, Cursor, ...) can point at `sealg mcp` and reach
//! the user's gateway through the same `/mcp/{api_key}/` endpoint that `list`
//! and `call` use. Not built yet; this stub keeps the subcommand surface stable.

/// Print the "not implemented" notice and exit with `EX_UNAVAILABLE` (69).
pub fn run() -> ! {
    eprintln!(
        "sealg mcp is not implemented yet.\n\
         \n\
         Planned: a local MCP transport that bridges an MCP client (e.g. Claude\n\
         Desktop, Cursor) to the SealGate gateway over stdio, forwarding\n\
         tools/list and tools/call to the same per-user endpoint that\n\
         `sealg list` and `sealg call` already use.\n\
         \n\
         For now use `sealg list` and `sealg call <tool>`."
    );
    std::process::exit(69);
}
