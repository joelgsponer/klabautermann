use std::process::Command;

fn main() {
    // Prefer GIT_HASH env var (set by Docker build arg), fall back to git
    let hash = std::env::var("GIT_HASH")
        .ok()
        .filter(|v| !v.is_empty() && v != "unknown")
        .unwrap_or_else(|| {
            Command::new("git")
                .args(["rev-parse", "--short", "HEAD"])
                .output()
                .ok()
                .filter(|o| o.status.success())
                .and_then(|o| String::from_utf8(o.stdout).ok())
                .map(|s| s.trim().to_string())
                .unwrap_or_else(|| "dev".into())
        });

    println!("cargo:rustc-env=GIT_HASH={}", hash);
    println!("cargo:rerun-if-env-changed=GIT_HASH");
    println!("cargo:rerun-if-changed=.git/HEAD");
    println!("cargo:rerun-if-changed=.git/refs/heads/");
}
