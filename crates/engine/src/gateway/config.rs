//! Gateway connection config, resolved from the environment.
//!
//! `sealg` is a thin transport: it carries no policy, only the coordinates
//! needed to reach the SealGate gateway and let it enforce (see the gateway's
//! `dev-docs/architecture/multi-interface-design.md`). All of those coordinates
//! come from the environment so the binary stays stateless and drops cleanly
//! into any sandbox (Centaur injects them per pod).
//!
//! Resolution is written against a getter closure, not `std::env` directly, so
//! tests are deterministic (mirrors `AppContext::new` vs `::default`).

/// Env var names. Kept in one place so the doc and the code cannot drift.
pub mod env_keys {
    /// Gateway origin, e.g. `https://dashboard.sealgate.ai` or `http://localhost:3000`.
    pub const URL: &str = "SEALGATE_URL";
    /// SealGate API key. Optional: when absent, auth is expected to be injected
    /// upstream (Centaur iron-proxy attaches `Authorization`).
    pub const API_KEY: &str = "SEALGATE_API_KEY";
    /// Zero-knowledge secret key value; sent as the `sealgate_secret_key` header.
    pub const SECRET_KEY: &str = "SEALGATE_SECRET_KEY";
    /// Stable conversation id; sent as `x-sealgate-conversation-id`.
    pub const CONVERSATION_ID: &str = "SEALGATE_CONVERSATION_ID";
    /// Centaur's per-conversation key, used as a fallback for CONVERSATION_ID
    /// (`centaur-session-runtime` sets it on every tool pod).
    pub const CENTAUR_THREAD_KEY: &str = "CENTAUR_THREAD_KEY";
    /// CA bundle paths for a MITM egress proxy, tried in order. reqwest+rustls
    /// does not read these automatically, so we load them explicitly or TLS to
    /// the gateway fails behind an intercepting proxy (e.g. Centaur iron-proxy).
    pub const CA_BUNDLE: &[&str] = &["SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"];
}

/// The default gateway origin when `SEALGATE_URL` is unset. Deliberately the
/// dev endpoint, never a guessed prod host: prod deployments set the env var.
pub const DEFAULT_URL: &str = "http://localhost:3000";

/// The header carrying the zero-knowledge secret key (gateway contract).
pub const SECRET_KEY_HEADER: &str = "sealgate_secret_key";
/// The header carrying the stable conversation id (gateway contract:
/// `SEALGATE_CONVERSATION_ID_HEADER` in `src/middleware/session_tokens.py`).
pub const CONVERSATION_ID_HEADER: &str = "x-sealgate-conversation-id";

/// Everything `sealg` needs to reach the gateway. Resolved once at startup.
#[derive(Debug, Clone)]
pub struct GatewayConfig {
    /// Gateway origin with no trailing slash and no `/mcp` suffix.
    pub base_url: String,
    /// API key. `Some` → embedded in the MCP path (`/mcp/{key}/`). `None` →
    /// path is `/mcp/` and auth is expected from an upstream injecting proxy.
    pub api_key: Option<String>,
    /// Zero-knowledge secret key value, sent as the `sealgate_secret_key` header.
    pub secret_key: Option<String>,
    /// Stable conversation id, sent as `x-sealgate-conversation-id`.
    pub conversation_id: Option<String>,
    /// Path to a CA bundle to trust in addition to the built-in roots.
    pub ca_bundle: Option<String>,
}

impl GatewayConfig {
    /// Resolve from the process environment.
    pub fn from_env() -> Self {
        Self::from_getter(|k| std::env::var(k).ok().filter(|v| !v.trim().is_empty()))
    }

    /// Resolve from the environment, then override the gateway origin with
    /// `url` when it is `Some` and non-blank (the `--gateway-url` flag). A
    /// trailing `/` is trimmed to match [`from_env`](Self::from_env); a blank
    /// override is ignored so the env/default value stands.
    pub fn from_env_with_url_override(url: Option<String>) -> Self {
        let mut cfg = Self::from_env();
        if let Some(u) = url {
            let u = u.trim();
            if !u.is_empty() {
                cfg.base_url = u.trim_end_matches('/').to_string();
            }
        }
        cfg
    }

    /// Resolve from an arbitrary getter (the test seam).
    pub fn from_getter(get: impl Fn(&str) -> Option<String>) -> Self {
        let base_url = get(env_keys::URL)
            .unwrap_or_else(|| DEFAULT_URL.to_string())
            .trim_end_matches('/')
            .to_string();

        let conversation_id =
            get(env_keys::CONVERSATION_ID).or_else(|| get(env_keys::CENTAUR_THREAD_KEY));

        let ca_bundle = env_keys::CA_BUNDLE.iter().find_map(|k| get(k));

        Self {
            base_url,
            api_key: get(env_keys::API_KEY),
            secret_key: get(env_keys::SECRET_KEY),
            conversation_id,
            ca_bundle,
        }
    }

    /// The MCP endpoint URL: `{base}/mcp/{key}/`, or `{base}/mcp/` when no key
    /// is present (auth injected upstream).
    pub fn mcp_url(&self) -> String {
        match &self.api_key {
            Some(key) => format!("{}/mcp/{}/", self.base_url, key),
            None => format!("{}/mcp/", self.base_url),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn getter(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        move |k: &str| map.get(k).cloned()
    }

    #[test]
    fn defaults_when_unset() {
        let c = GatewayConfig::from_getter(getter(&[]));
        assert_eq!(c.base_url, DEFAULT_URL);
        assert!(c.api_key.is_none());
        // No key → keyless path, auth injected upstream.
        assert_eq!(c.mcp_url(), "http://localhost:3000/mcp/");
    }

    #[test]
    fn key_goes_in_the_path_and_trailing_slash_is_trimmed() {
        let c = GatewayConfig::from_getter(getter(&[
            (env_keys::URL, "https://dashboard.sealgate.ai/"),
            (env_keys::API_KEY, "ew_live_abc"),
        ]));
        assert_eq!(c.base_url, "https://dashboard.sealgate.ai");
        assert_eq!(
            c.mcp_url(),
            "https://dashboard.sealgate.ai/mcp/ew_live_abc/"
        );
    }

    #[test]
    fn conversation_id_falls_back_to_centaur_thread_key() {
        let c = GatewayConfig::from_getter(getter(&[(
            env_keys::CENTAUR_THREAD_KEY,
            "slack:C123:171.45",
        )]));
        assert_eq!(c.conversation_id.as_deref(), Some("slack:C123:171.45"));

        // Explicit SEALGATE_CONVERSATION_ID wins over the Centaur fallback.
        let c = GatewayConfig::from_getter(getter(&[
            (env_keys::CONVERSATION_ID, "explicit"),
            (env_keys::CENTAUR_THREAD_KEY, "fallback"),
        ]));
        assert_eq!(c.conversation_id.as_deref(), Some("explicit"));
    }

    #[test]
    fn ca_bundle_tries_paths_in_order() {
        let c = GatewayConfig::from_getter(getter(&[("REQUESTS_CA_BUNDLE", "/certs/ca.pem")]));
        assert_eq!(c.ca_bundle.as_deref(), Some("/certs/ca.pem"));

        // SSL_CERT_FILE has priority over REQUESTS_CA_BUNDLE.
        let c = GatewayConfig::from_getter(getter(&[
            ("SSL_CERT_FILE", "/a.pem"),
            ("REQUESTS_CA_BUNDLE", "/b.pem"),
        ]));
        assert_eq!(c.ca_bundle.as_deref(), Some("/a.pem"));
    }

    #[test]
    fn url_override_trims_trailing_slash_and_ignores_blank() {
        // A non-blank override replaces base_url and drops the trailing slash.
        let cfg =
            GatewayConfig::from_env_with_url_override(Some("https://gw.example.com/".to_string()));
        assert_eq!(cfg.base_url, "https://gw.example.com");

        // A blank / whitespace-only override is ignored, leaving the resolved
        // base_url identical to plain `from_env` (deterministic regardless of
        // ambient SEALGATE_URL).
        let base = GatewayConfig::from_env().base_url;
        let cfg = GatewayConfig::from_env_with_url_override(Some("   ".to_string()));
        assert_eq!(cfg.base_url, base);
        let cfg = GatewayConfig::from_env_with_url_override(None);
        assert_eq!(cfg.base_url, base);
    }

    #[test]
    fn blank_values_are_treated_as_unset_via_from_env_filter() {
        // from_getter itself does not filter, but from_env filters blanks; emulate.
        let get = |k: &str| -> Option<String> {
            let raw: Option<&str> = match k {
                "SEALGATE_URL" => Some("   "),
                _ => None,
            };
            raw.map(|s| s.to_string()).filter(|v| !v.trim().is_empty())
        };
        let c = GatewayConfig::from_getter(get);
        assert_eq!(c.base_url, DEFAULT_URL);
    }
}
