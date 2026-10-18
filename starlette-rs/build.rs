//! Capture adapter identity metadata in the compiled executable.

use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{self, Command};

fn main() {
    if let Err(error) = emit_identity() {
        eprintln!("cannot prepare native adapter build identity: {error}");
        process::exit(1);
    }
}

fn emit_identity() -> Result<(), String> {
    let crate_root = PathBuf::from(
        env::var_os("CARGO_MANIFEST_DIR")
            .ok_or_else(|| String::from("Cargo did not provide CARGO_MANIFEST_DIR"))?,
    );
    let parent_root = crate_root
        .parent()
        .ok_or_else(|| String::from("crate manifest has no workspace parent"))?;
    let is_workspace_checkout =
        parent_root.join("Cargo.toml").is_file() && parent_root.join("Cargo.lock").is_file();
    let identity_root = if is_workspace_checkout {
        parent_root
    } else {
        crate_root.as_path()
    };
    let lock_path = if is_workspace_checkout {
        parent_root.join("Cargo.lock")
    } else {
        crate_root.join("Cargo.lock")
    };
    let mut source_files = if is_workspace_checkout {
        let mut files = vec![
            parent_root.join("Cargo.toml"),
            lock_path.clone(),
            crate_root.join("Cargo.toml"),
            crate_root.join("build.rs"),
        ];
        let toolchain = parent_root.join("rust-toolchain.toml");
        if toolchain.is_file() {
            files.push(toolchain);
        }
        files
    } else {
        vec![
            crate_root.join("Cargo.toml"),
            lock_path.clone(),
            crate_root.join("build.rs"),
        ]
    };
    collect_files(&crate_root.join("src"), &mut source_files)?;
    source_files.sort();
    source_files.dedup();

    let source_fingerprint = source_fingerprint(identity_root, &source_files)?;
    for path in &source_files {
        println!("cargo:rerun-if-changed={}", path.display());
    }
    for path in git_identity_watch_paths(identity_root) {
        println!("cargo:rerun-if-changed={}", path.display());
    }
    println!("cargo:rerun-if-env-changed=RUSTC");

    let head = git_output(identity_root, &["rev-parse", "--verify", "HEAD"]);
    let status = git_output(
        identity_root,
        &[
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "starlette-rs",
            "Cargo.toml",
            "Cargo.lock",
            "rust-toolchain.toml",
        ],
    );
    let dirty = head.is_none() || status.as_deref().is_none_or(|value| !value.is_empty());
    let base_revision = head.unwrap_or_else(|| String::from("uncommitted"));
    let revision = format!("{base_revision}+source-fnv1a64-{source_fingerprint:016x}");

    let lock_bytes = fs::read(&lock_path).map_err(|error| {
        format!(
            "cannot read workspace dependency lock {}: {error}",
            lock_path.display()
        )
    })?;
    let dependency_lock_sha256 = lower_hex(&Sha256::digest(&lock_bytes));
    let runtime = format!(
        "{} ({} {})",
        rustc_version(),
        required_cargo_env("CARGO_CFG_TARGET_OS")?,
        required_cargo_env("CARGO_CFG_TARGET_ARCH")?
    );

    println!("cargo:rustc-env=STARLETTE_PARITY_BUILD_REVISION={revision}");
    println!("cargo:rustc-env=STARLETTE_PARITY_BUILD_DIRTY={dirty}");
    println!("cargo:rustc-env=STARLETTE_PARITY_BUILD_RUNTIME={runtime}");
    println!(
        "cargo:rustc-env=STARLETTE_PARITY_BUILD_OS={}",
        required_cargo_env("CARGO_CFG_TARGET_OS")?
    );
    println!(
        "cargo:rustc-env=STARLETTE_PARITY_BUILD_ARCHITECTURE={}",
        required_cargo_env("CARGO_CFG_TARGET_ARCH")?
    );
    println!(
        "cargo:rustc-env=STARLETTE_PARITY_BUILD_DEPENDENCY_LOCK_SHA256={dependency_lock_sha256}"
    );
    Ok(())
}

/// Returns the Git files whose changes can alter the embedded revision.
///
/// Cargo does not otherwise know that `HEAD` or its referenced branch moved,
/// so a clean checkout could keep an adapter binary with an obsolete identity.
fn git_identity_watch_paths(root: &Path) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Some(head) = git_output(root, &["rev-parse", "--git-path", "HEAD"]) {
        paths.push(resolve_git_path(root, &head));
    }
    if let Some(reference) = git_output(root, &["symbolic-ref", "--quiet", "HEAD"]) {
        if let Some(path) = git_output(root, &["rev-parse", "--git-path", &reference]) {
            paths.push(resolve_git_path(root, &path));
        }
    }
    if let Some(common_dir) = git_output(root, &["rev-parse", "--git-common-dir"]) {
        let common_dir = resolve_git_path(root, &common_dir);
        paths.push(common_dir.join("refs").join("heads"));
        paths.push(common_dir.join("packed-refs"));
    }
    paths.sort();
    paths.dedup();
    paths
}

fn resolve_git_path(root: &Path, path: &str) -> PathBuf {
    let path = PathBuf::from(path);
    if path.is_absolute() {
        path
    } else {
        root.join(path)
    }
}

fn required_cargo_env(name: &str) -> Result<String, String> {
    env::var(name).map_err(|error| format!("Cargo did not provide {name}: {error}"))
}

fn rustc_version() -> String {
    let rustc = env::var_os("RUSTC").unwrap_or_else(|| "rustc".into());
    match Command::new(rustc).arg("--version").output() {
        Ok(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).trim().to_owned()
        }
        _ => String::from("rustc version unavailable"),
    }
}

fn git_output(root: &Path, arguments: &[&str]) -> Option<String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(arguments)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn source_fingerprint(workspace_root: &Path, files: &[PathBuf]) -> Result<u64, String> {
    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for path in files {
        let relative = path
            .strip_prefix(workspace_root)
            .map_err(|error| error.to_string())?;
        hash_bytes(&mut hash, relative.to_string_lossy().as_bytes());
        hash_byte(&mut hash, 0);
        let contents = fs::read(path)
            .map_err(|error| format!("cannot read identity source {}: {error}", path.display()))?;
        hash_bytes(&mut hash, &contents);
        hash_byte(&mut hash, 0xff);
    }
    Ok(hash)
}

fn collect_files(directory: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    println!("cargo:rerun-if-changed={}", directory.display());
    let entries = fs::read_dir(directory).map_err(|error| {
        format!(
            "cannot list identity source {}: {error}",
            directory.display()
        )
    })?;
    for entry in entries {
        let entry = entry.map_err(|error| error.to_string())?;
        let path = entry.path();
        let file_type = entry.file_type().map_err(|error| error.to_string())?;
        if file_type.is_dir() {
            collect_files(&path, files)?;
        } else if file_type.is_file() {
            files.push(path);
        }
    }
    Ok(())
}

fn lower_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len().saturating_mul(2));
    for &byte in bytes {
        output.push(char::from(HEX[(byte >> 4) as usize]));
        output.push(char::from(HEX[(byte & 0x0f) as usize]));
    }
    output
}

fn hash_bytes(hash: &mut u64, bytes: &[u8]) {
    for byte in bytes {
        hash_byte(hash, *byte);
    }
}

fn hash_byte(hash: &mut u64, byte: u8) {
    *hash ^= u64::from(byte);
    *hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
}
