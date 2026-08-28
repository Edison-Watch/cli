//! CLI `doctor` subcommand and its human/JSON output helpers.
//!
//! Split out of `main.rs` so the entrypoint stays focused on clap wiring. The
//! whole module is gated behind the `cli` feature, so a `server-only` prune
//! drops it wholesale.

use engine::types::{CommandResult, Status};
use std::path::PathBuf;

// Subcommand implementation

pub(crate) async fn cmd_doctor(json: bool, out: Option<PathBuf>) {
    let result = engine::doctor::run_doctor();
    if let Some(ref path) = out {
        write_result_file(path, &result);
    }
    output_result(&result, json);
}

// Output helpers

fn output_result(result: &CommandResult, json: bool) {
    if json {
        let j = serde_json::to_string_pretty(result).unwrap_or_default();
        println!("{}", j);
    } else {
        print_human(result);
    }

    // Exit with non-zero status on error/fail
    match result.status {
        Status::Pass | Status::Skip => {}
        Status::Fail => std::process::exit(1),
        Status::Error => std::process::exit(2),
    }
}

fn print_human(r: &CommandResult) {
    let status_icon = match r.status {
        Status::Pass => "PASS",
        Status::Fail => "FAIL",
        Status::Skip => "SKIP",
        Status::Error => "ERROR",
    };

    println!("[{}] {} {}", status_icon, r.command, r.target);
    println!("  run_id: {}", r.run_id);
    println!("  timing: {}ms", r.timing_ms.total);

    if !r.timing_ms.steps.is_empty() {
        for (step, ms) in &r.timing_ms.steps {
            println!("    {}: {}ms", step, ms);
        }
    }

    if let Some(ref err) = r.error {
        println!("  error:  {} – {}", err.code, err.message);
    }

    if let Some(ref data) = r.data {
        // Print compact data for human output
        if let Ok(s) = serde_json::to_string_pretty(data) {
            // Indent each line
            for line in s.lines() {
                println!("  {}", line);
            }
        }
    }

    println!(
        "  env: os={} arch={} headless={}",
        r.env_summary.os, r.env_summary.arch, r.env_summary.headless
    );
}

// Artifact helpers

fn write_result_file(path: &std::path::Path, result: &CommandResult) {
    let j = serde_json::to_string_pretty(result).unwrap_or_default();
    if let Err(e) = std::fs::write(path, &j) {
        eprintln!(
            "warning: failed to write result to {}: {}",
            path.display(),
            e
        );
    }
}
