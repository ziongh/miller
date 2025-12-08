//! Rust-native file watcher for Miller.
//!
//! This module provides a high-performance file watcher that replaces Python's watchdog.
//! Key benefits:
//! - Zero GIL contention: File monitoring runs entirely in Rust
//! - Hash-based change detection: Only notifies Python when content actually changes
//! - Efficient for 100k+ files: Uses notify crate (same as ripgrep)
//! - Cross-platform: Works on Linux (inotify), macOS (FSEvents), Windows (ReadDirectoryChangesW)

use anyhow::{Context, Result};
use dashmap::DashMap;
use ignore::gitignore::{Gitignore, GitignoreBuilder};
use notify::{Config, Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::Duration;
use tracing::{debug, error, info, warn};

/// File event types matching Python's FileEvent enum
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileEventKind {
    Created,
    Modified,
    Deleted,
}

impl FileEventKind {
    fn as_str(&self) -> &'static str {
        match self {
            FileEventKind::Created => "created",
            FileEventKind::Modified => "modified",
            FileEventKind::Deleted => "deleted",
        }
    }
}

/// A file change event with path and event type
#[derive(Debug, Clone)]
pub struct FileChange {
    pub path: PathBuf,
    pub kind: FileEventKind,
    pub new_hash: Option<String>,
}

/// Thread-safe hash storage for tracking file content changes
type HashStore = Arc<DashMap<PathBuf, String>>;

/// Internal message type for the watcher thread
enum WatcherMessage {
    Stop,
}

/// Rust-native file watcher exposed to Python.
///
/// This watcher monitors a workspace directory and calls back to Python
/// only when file content actually changes (verified by Blake3 hash).
#[pyclass]
pub struct PyFileWatcher {
    /// Root directory being watched
    workspace_path: PathBuf,
    /// Known file hashes (path -> blake3 hash)
    known_hashes: HashStore,
    /// Whether the watcher is currently running
    running: Arc<AtomicBool>,
    /// Channel to send stop signal to watcher thread
    stop_tx: Option<Sender<WatcherMessage>>,
    /// Handle to the watcher thread
    watcher_thread: Option<JoinHandle<()>>,
    /// Gitignore matcher for filtering files
    gitignore: Option<Gitignore>,
    /// Custom ignore patterns (from .julieignore)
    custom_ignores: Vec<String>,
}

#[pymethods]
impl PyFileWatcher {
    /// Create a new file watcher.
    ///
    /// Args:
    ///     workspace_path: Root directory to watch
    ///     initial_hashes: Dict mapping file paths to their known hashes
    ///     ignore_patterns: List of gitignore-style patterns to exclude
    #[new]
    #[pyo3(signature = (workspace_path, initial_hashes=None, ignore_patterns=None))]
    fn new(
        workspace_path: String,
        initial_hashes: Option<HashMap<String, String>>,
        ignore_patterns: Option<Vec<String>>,
    ) -> PyResult<Self> {
        let workspace = PathBuf::from(&workspace_path);
        if !workspace.exists() {
            return Err(pyo3::exceptions::PyFileNotFoundError::new_err(format!(
                "Workspace path does not exist: {}",
                workspace_path
            )));
        }
        if !workspace.is_dir() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Workspace path is not a directory: {}",
                workspace_path
            )));
        }

        // Initialize hash store with known hashes
        let known_hashes: HashStore = Arc::new(DashMap::new());
        if let Some(hashes) = initial_hashes {
            for (path, hash) in hashes {
                known_hashes.insert(PathBuf::from(path), hash);
            }
            info!(
                "Initialized file watcher with {} known file hashes",
                known_hashes.len()
            );
        }

        // Build gitignore matcher from workspace .gitignore
        let gitignore = build_gitignore(&workspace);

        // Store custom ignore patterns
        let custom_ignores = ignore_patterns.unwrap_or_default();

        Ok(PyFileWatcher {
            workspace_path: workspace,
            known_hashes,
            running: Arc::new(AtomicBool::new(false)),
            stop_tx: None,
            watcher_thread: None,
            gitignore,
            custom_ignores,
        })
    }

    /// Start watching the workspace.
    ///
    /// Args:
    ///     callback: Python function to call when files change.
    ///               Signature: callback(events: list[tuple[str, str, str]]) -> None
    ///               Where each tuple is (event_type, file_path, new_hash)
    ///
    /// Raises:
    ///     RuntimeError: If already running
    fn start(&mut self, callback: Py<PyAny>) -> PyResult<()> {
        if self.running.load(Ordering::SeqCst) {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "FileWatcher is already running",
            ));
        }

        // Create stop channel
        let (stop_tx, stop_rx) = channel::<WatcherMessage>();
        self.stop_tx = Some(stop_tx);

        // Clone state for the background thread
        let workspace = self.workspace_path.clone();
        let known_hashes = Arc::clone(&self.known_hashes);
        let running = Arc::clone(&self.running);
        let gitignore = self.gitignore.clone();
        let custom_ignores = self.custom_ignores.clone();

        // Mark as running
        self.running.store(true, Ordering::SeqCst);

        info!("Starting Rust file watcher for: {:?}", workspace);

        // Spawn watcher thread
        let handle = thread::Builder::new()
            .name("miller-file-watcher".to_string())
            .spawn(move || {
                if let Err(e) = run_watcher(
                    workspace,
                    known_hashes,
                    running,
                    stop_rx,
                    callback,
                    gitignore,
                    custom_ignores,
                ) {
                    error!("File watcher error: {:?}", e);
                }
            })
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "Failed to spawn watcher thread: {}",
                    e
                ))
            })?;

        self.watcher_thread = Some(handle);

        Ok(())
    }

    /// Stop watching and clean up resources.
    fn stop(&mut self) -> PyResult<()> {
        if !self.running.load(Ordering::SeqCst) {
            return Ok(()); // Safe to call if not running
        }

        info!("Stopping Rust file watcher");

        // Signal stop
        self.running.store(false, Ordering::SeqCst);
        if let Some(tx) = self.stop_tx.take() {
            let _ = tx.send(WatcherMessage::Stop);
        }

        // Wait for thread to finish
        if let Some(handle) = self.watcher_thread.take() {
            let _ = handle.join();
        }

        info!("File watcher stopped");
        Ok(())
    }

    /// Check if watcher is currently running.
    fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    /// Get the current number of tracked files.
    fn tracked_file_count(&self) -> usize {
        self.known_hashes.len()
    }

    /// Update the hash for a file (called after successful indexing).
    fn update_hash(&self, file_path: String, hash: String) {
        self.known_hashes.insert(PathBuf::from(file_path), hash);
    }

    /// Remove a file from tracking (called after file deletion).
    fn remove_hash(&self, file_path: String) {
        self.known_hashes.remove(&PathBuf::from(file_path));
    }

    /// Get all currently tracked file paths.
    fn get_tracked_files(&self) -> Vec<String> {
        self.known_hashes
            .iter()
            .map(|entry| entry.key().to_string_lossy().to_string())
            .collect()
    }
}

/// Build a gitignore matcher from the workspace .gitignore file
fn build_gitignore(workspace: &Path) -> Option<Gitignore> {
    let gitignore_path = workspace.join(".gitignore");
    if !gitignore_path.exists() {
        return None;
    }

    let mut builder = GitignoreBuilder::new(workspace);

    // Add common default ignores
    let _ = builder.add_line(None, ".git/");
    let _ = builder.add_line(None, ".miller/");
    let _ = builder.add_line(None, "__pycache__/");
    let _ = builder.add_line(None, "*.pyc");
    let _ = builder.add_line(None, "node_modules/");
    let _ = builder.add_line(None, "target/");
    let _ = builder.add_line(None, ".venv/");
    let _ = builder.add_line(None, "venv/");

    // Add patterns from .gitignore
    if let Some(e) = builder.add(&gitignore_path) {
        warn!("Failed to parse .gitignore: {:?}", e);
    }

    match builder.build() {
        Ok(gi) => Some(gi),
        Err(e) => {
            warn!("Failed to build gitignore matcher: {:?}", e);
            None
        }
    }
}

/// Check if a path should be ignored
fn should_ignore(
    path: &Path,
    workspace: &Path,
    gitignore: &Option<Gitignore>,
    custom_ignores: &[String],
) -> bool {
    // Get relative path
    let rel_path = match path.strip_prefix(workspace) {
        Ok(p) => p,
        Err(_) => return true, // Outside workspace
    };

    // Check gitignore patterns
    // Use matched_path_or_any_parents to properly handle directory patterns like "build/"
    if let Some(gi) = gitignore {
        if gi
            .matched_path_or_any_parents(rel_path, path.is_dir())
            .is_ignore()
        {
            return true;
        }
    }

    // Check custom ignore patterns (reuse existing logic)
    if !custom_ignores.is_empty() {
        if crate::utils::ignore::is_ignored_by_pattern(path, custom_ignores) {
            return true;
        }
    }

    // Skip hidden files (except .gitignore itself)
    if let Some(name) = path.file_name() {
        let name_str = name.to_string_lossy();
        if name_str.starts_with('.') && name_str != ".gitignore" && name_str != ".julieignore" {
            return true;
        }
    }

    false
}

/// Compute Blake3 hash of file content
fn compute_hash(path: &Path) -> Result<String> {
    let content = fs::read(path).context("Failed to read file")?;
    let hash = blake3::hash(&content);
    Ok(hash.to_hex().to_string())
}

/// Main watcher loop running in background thread
fn run_watcher(
    workspace: PathBuf,
    known_hashes: HashStore,
    running: Arc<AtomicBool>,
    stop_rx: Receiver<WatcherMessage>,
    callback: Py<PyAny>,
    gitignore: Option<Gitignore>,
    custom_ignores: Vec<String>,
) -> Result<()> {
    // Create channel for notify events
    let (event_tx, event_rx) = channel::<notify::Result<Event>>();

    // Use RecommendedWatcher (inotify on Linux, FSEvents on macOS, etc.)
    // This works well on native filesystems including native Linux paths in WSL2
    // For Windows-mounted paths in WSL2 (/mnt/c/, etc.), Python falls back to watchdog
    let event_tx_clone = event_tx.clone();
    let mut watcher = RecommendedWatcher::new(
        move |res: notify::Result<Event>| {
            let _ = event_tx_clone.send(res);
        },
        Config::default(),
    )?;

    // Start watching
    watcher.watch(&workspace, RecursiveMode::Recursive)?;
    info!(
        "Rust file watcher active on {:?} ({} files tracked)",
        workspace,
        known_hashes.len()
    );

    // Batch changes for efficiency
    let mut pending_changes: Vec<FileChange> = Vec::new();
    let batch_timeout = Duration::from_millis(200); // Debounce window

    while running.load(Ordering::SeqCst) {
        // Check for stop signal (non-blocking)
        if stop_rx.try_recv().is_ok() {
            break;
        }

        // Process events with timeout
        match event_rx.recv_timeout(batch_timeout) {
            Ok(Ok(event)) => {
                // Process file system event
                for path in event.paths.iter() {
                    // Skip directories
                    if path.is_dir() {
                        continue;
                    }

                    // Skip ignored files
                    if should_ignore(path, &workspace, &gitignore, &custom_ignores) {
                        continue;
                    }

                    // Determine event kind and process
                    if let Some(change) =
                        process_event(path, &event.kind, &known_hashes, &workspace)
                    {
                        pending_changes.push(change);
                    }
                }
            }
            Ok(Err(e)) => {
                warn!("Watch error: {:?}", e);
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                // Batch timeout - flush pending changes to Python
                if !pending_changes.is_empty() {
                    flush_changes_to_python(&mut pending_changes, &callback, &known_hashes);
                }
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                break;
            }
        }
    }

    // Final flush
    if !pending_changes.is_empty() {
        flush_changes_to_python(&mut pending_changes, &callback, &known_hashes);
    }

    Ok(())
}

/// Process a single file system event and return a FileChange if content changed
fn process_event(
    path: &Path,
    event_kind: &EventKind,
    known_hashes: &HashStore,
    workspace: &Path,
) -> Option<FileChange> {
    let rel_path = path.strip_prefix(workspace).ok()?;

    match event_kind {
        EventKind::Create(_) => {
            // New file - compute hash
            if !path.exists() || !path.is_file() {
                return None;
            }

            match compute_hash(path) {
                Ok(hash) => Some(FileChange {
                    path: rel_path.to_path_buf(),
                    kind: FileEventKind::Created,
                    new_hash: Some(hash),
                }),
                Err(e) => {
                    debug!("Failed to hash new file {:?}: {:?}", path, e);
                    None
                }
            }
        }

        EventKind::Modify(_) => {
            // Modified file - check if content actually changed
            if !path.exists() || !path.is_file() {
                return None;
            }

            match compute_hash(path) {
                Ok(new_hash) => {
                    // Check if hash changed
                    let old_hash = known_hashes.get(path);
                    if old_hash.as_deref().map(|h| h.as_str()) == Some(new_hash.as_str()) {
                        // Content unchanged (e.g., just touched, or save without edits)
                        debug!("File touched but content unchanged: {:?}", rel_path);
                        return None;
                    }

                    Some(FileChange {
                        path: rel_path.to_path_buf(),
                        kind: FileEventKind::Modified,
                        new_hash: Some(new_hash),
                    })
                }
                Err(e) => {
                    debug!("Failed to hash modified file {:?}: {:?}", path, e);
                    None
                }
            }
        }

        EventKind::Remove(_) => {
            // File deleted
            Some(FileChange {
                path: rel_path.to_path_buf(),
                kind: FileEventKind::Deleted,
                new_hash: None,
            })
        }

        _ => None, // Ignore other events (access, etc.)
    }
}

/// Flush pending changes to Python callback
fn flush_changes_to_python(
    changes: &mut Vec<FileChange>,
    callback: &Py<PyAny>,
    known_hashes: &HashStore,
) {
    if changes.is_empty() {
        return;
    }

    debug!("Flushing {} file changes to Python", changes.len());

    // Acquire GIL and call Python
    Python::with_gil(|py| {  // Note: with_gil is deprecated but attach is not stable yet
        // Convert changes to Python list of tuples: [(event_type, path, hash), ...]
        let events: Vec<(String, String, Option<String>)> = changes
            .iter()
            .map(|c| {
                (
                    c.kind.as_str().to_string(),
                    c.path.to_string_lossy().to_string(),
                    c.new_hash.clone(),
                )
            })
            .collect();

        // Update known hashes for non-deleted files
        for change in changes.iter() {
            let full_path = change.path.clone();
            match change.kind {
                FileEventKind::Deleted => {
                    known_hashes.remove(&full_path);
                }
                _ => {
                    if let Some(ref hash) = change.new_hash {
                        known_hashes.insert(full_path, hash.clone());
                    }
                }
            }
        }

        // Call Python callback
        if let Err(e) = callback.call1(py, (events,)) {
            error!("Failed to call Python callback: {:?}", e);
        }
    });

    changes.clear();
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_compute_hash() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test.txt");
        fs::write(&file_path, "hello world").unwrap();

        let hash = compute_hash(&file_path).unwrap();
        assert!(!hash.is_empty());
        assert_eq!(hash.len(), 64); // Blake3 hex is 64 chars
    }

    #[test]
    fn test_hash_changes_with_content() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test.txt");

        fs::write(&file_path, "content v1").unwrap();
        let hash1 = compute_hash(&file_path).unwrap();

        fs::write(&file_path, "content v2").unwrap();
        let hash2 = compute_hash(&file_path).unwrap();

        assert_ne!(hash1, hash2);
    }

    #[test]
    fn test_hash_same_for_same_content() {
        let temp_dir = TempDir::new().unwrap();
        let file1 = temp_dir.path().join("file1.txt");
        let file2 = temp_dir.path().join("file2.txt");

        fs::write(&file1, "same content").unwrap();
        fs::write(&file2, "same content").unwrap();

        let hash1 = compute_hash(&file1).unwrap();
        let hash2 = compute_hash(&file2).unwrap();

        assert_eq!(hash1, hash2);
    }

    #[test]
    fn test_should_ignore_gitignore_patterns() {
        let temp_dir = TempDir::new().unwrap();
        let workspace = temp_dir.path();

        // Create .gitignore
        fs::write(workspace.join(".gitignore"), "*.log\nbuild/\n").unwrap();

        // Create actual files for testing (gitignore crate needs real paths)
        fs::write(workspace.join("debug.log"), "log content").unwrap();
        fs::create_dir(workspace.join("build")).unwrap();
        fs::write(workspace.join("build/output.txt"), "build output").unwrap();
        fs::create_dir(workspace.join("src")).unwrap();
        fs::write(workspace.join("src/main.rs"), "fn main() {}").unwrap();

        let gitignore = build_gitignore(workspace);

        // Should ignore (matches *.log pattern)
        assert!(should_ignore(
            &workspace.join("debug.log"),
            workspace,
            &gitignore,
            &[]
        ));
        // Should ignore (matches build/ directory pattern)
        assert!(should_ignore(
            &workspace.join("build/output.txt"),
            workspace,
            &gitignore,
            &[]
        ));

        // Should NOT ignore
        assert!(!should_ignore(
            &workspace.join("src/main.rs"),
            workspace,
            &gitignore,
            &[]
        ));
    }

    #[test]
    fn test_should_ignore_hidden_files() {
        let temp_dir = TempDir::new().unwrap();
        let workspace = temp_dir.path();

        // Hidden files should be ignored (except .gitignore)
        assert!(should_ignore(
            &workspace.join(".hidden"),
            workspace,
            &None,
            &[]
        ));
        assert!(should_ignore(
            &workspace.join(".env"),
            workspace,
            &None,
            &[]
        ));

        // .gitignore and .julieignore should NOT be ignored
        assert!(!should_ignore(
            &workspace.join(".gitignore"),
            workspace,
            &None,
            &[]
        ));
        assert!(!should_ignore(
            &workspace.join(".julieignore"),
            workspace,
            &None,
            &[]
        ));
    }
}
