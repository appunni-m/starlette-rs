//! Rust-owned path lookup and response selection for Starlette static files.

use std::fs::{self, Metadata};
use std::io;
use std::path::{Component, Path, PathBuf};

use crate::{FileMetadata, FileResponse, FileResponseError, FileResponseOptions};

/// Static-file configuration and the ordered set of asset roots.
#[derive(Clone, Debug)]
pub struct StaticFiles {
    directory: Option<PathBuf>,
    directories: Vec<PathBuf>,
    html: bool,
    follow_symlink: bool,
}

/// A path lookup result with the metadata used by the selected response.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StaticFile {
    /// The resolved filesystem path passed to `FileResponse`.
    pub path: PathBuf,
    /// File length and modification time used for validators and headers.
    pub metadata: FileMetadata,
    /// Whether the resolved path is a regular file.
    pub is_file: bool,
    /// Whether the resolved path is a directory.
    pub is_directory: bool,
}

/// The response selected by the StaticFiles protocol policy.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StaticFilesResponse {
    /// Stream a regular file with the given status.
    File {
        /// Resolved file and response metadata.
        file: StaticFile,
        /// HTTP status selected for the file response.
        status_code: u16,
    },
    /// Return a 304 with only the allowed cache validator headers.
    NotModified {
        /// Ordered response header bytes retained for a 304 response.
        headers: Vec<(Vec<u8>, Vec<u8>)>,
    },
    /// Redirect a directory URL to the corresponding slash-terminated path.
    Redirect {
        /// Original ASGI path with a trailing slash.
        path: String,
    },
}

/// A configuration, request, or filesystem failure while serving static files.
#[derive(Debug)]
pub enum StaticFilesError {
    /// The request method is not GET or HEAD.
    MethodNotAllowed,
    /// No configured root contains the requested file.
    NotFound,
    /// The operating system denied access to a configured file.
    PermissionDenied,
    /// The initial directory check failed.
    DirectoryConfiguration(String),
    /// A filesystem operation failed for another reason.
    Io(io::Error),
    /// A file response could not be constructed.
    FileResponse(FileResponseError),
}

impl StaticFiles {
    /// Creates a static-file handler from ordered roots.
    pub fn new(
        directory: Option<PathBuf>,
        directories: Vec<PathBuf>,
        html: bool,
        check_dir: bool,
        follow_symlink: bool,
    ) -> Result<Self, StaticFilesError> {
        if check_dir
            && let Some(directory) = directory.as_ref()
            && !fs::metadata(directory).is_ok_and(|metadata| metadata.is_dir())
        {
            return Err(StaticFilesError::DirectoryConfiguration(format!(
                "Directory '{}' does not exist",
                directory.display()
            )));
        }
        Ok(Self {
            directory,
            directories,
            html,
            follow_symlink,
        })
    }

    /// Returns the originally configured directory, if supplied.
    #[must_use]
    pub fn directory(&self) -> Option<&Path> {
        self.directory.as_deref()
    }

    /// Returns roots in their lookup order.
    #[must_use]
    pub fn directories(&self) -> &[PathBuf] {
        &self.directories
    }

    /// Returns whether HTML index and 404 assets are enabled.
    #[must_use]
    pub fn html(&self) -> bool {
        self.html
    }

    /// Returns whether symlink targets may be served outside a root.
    #[must_use]
    pub fn follow_symlink(&self) -> bool {
        self.follow_symlink
    }

    /// Validates the configured directory on first use.
    pub fn check_config(&self) -> Result<(), StaticFilesError> {
        let Some(directory) = self.directory.as_ref() else {
            return Ok(());
        };
        let metadata = fs::metadata(directory).map_err(|error| {
            if error.kind() == io::ErrorKind::NotFound {
                StaticFilesError::DirectoryConfiguration(format!(
                    "StaticFiles directory '{}' does not exist.",
                    directory.display()
                ))
            } else {
                StaticFilesError::Io(error)
            }
        })?;
        if !metadata.is_dir() {
            return Err(StaticFilesError::DirectoryConfiguration(format!(
                "StaticFiles path '{}' is not a directory.",
                directory.display()
            )));
        }
        Ok(())
    }

    /// Derives the normalized relative path from an ASGI path and root path.
    #[must_use]
    pub fn get_path(path: &str, root_path: &str) -> String {
        let route_path = route_path(path, root_path);
        normalize_route_path(route_path)
    }

    /// Looks up a relative path while enforcing the configured-root boundary.
    pub fn lookup_path(&self, path: &str) -> Result<Option<StaticFile>, StaticFilesError> {
        if path.starts_with('/') || path.starts_with('\\') {
            return Ok(None);
        }
        for directory in &self.directories {
            let joined_path = directory.join(path);
            let (full_path, root_path) = if self.follow_symlink {
                (absolute_path(&joined_path)?, absolute_path(directory)?)
            } else {
                let full_path = match fs::canonicalize(&joined_path) {
                    Ok(path) => path,
                    Err(error) if error.kind() == io::ErrorKind::PermissionDenied => {
                        return Err(StaticFilesError::PermissionDenied);
                    }
                    Err(error)
                        if error.kind() == io::ErrorKind::NotFound
                            || error.kind() == io::ErrorKind::NotADirectory
                            || error.kind() == io::ErrorKind::InvalidInput
                            || is_name_too_long(&error) =>
                    {
                        continue;
                    }
                    Err(error) => return Err(StaticFilesError::Io(error)),
                };
                let root_path = match fs::canonicalize(directory) {
                    Ok(path) => path,
                    Err(error) if error.kind() == io::ErrorKind::PermissionDenied => {
                        return Err(StaticFilesError::PermissionDenied);
                    }
                    Err(error)
                        if error.kind() == io::ErrorKind::NotFound
                            || error.kind() == io::ErrorKind::NotADirectory =>
                    {
                        continue;
                    }
                    Err(error) => return Err(StaticFilesError::Io(error)),
                };
                (full_path, root_path)
            };
            if !full_path.starts_with(&root_path) {
                continue;
            }
            match fs::metadata(&full_path) {
                Ok(metadata) => {
                    return Ok(Some(static_file(full_path, &metadata)?));
                }
                Err(error)
                    if error.kind() == io::ErrorKind::NotFound
                        || error.kind() == io::ErrorKind::NotADirectory =>
                {
                    continue;
                }
                Err(error)
                    if is_name_too_long(&error) || error.kind() == io::ErrorKind::InvalidInput =>
                {
                    return Ok(None);
                }
                Err(error) if error.kind() == io::ErrorKind::PermissionDenied => {
                    return Err(StaticFilesError::PermissionDenied);
                }
                Err(error) => return Err(StaticFilesError::Io(error)),
            }
        }
        Ok(None)
    }

    /// Selects the StaticFiles response for one request.
    pub fn get_response(
        &self,
        path: &str,
        scope_path: &str,
        method: &str,
        request_headers: &[(Vec<u8>, Vec<u8>)],
    ) -> Result<StaticFilesResponse, StaticFilesError> {
        if method != "GET" && method != "HEAD" {
            return Err(StaticFilesError::MethodNotAllowed);
        }

        if let Some(file) = self.lookup_path(path)? {
            if file.is_file {
                return self.file_response(file, 200, request_headers, true);
            }
            if file.is_directory && self.html {
                let index_path = join_relative(path, "index.html");
                if let Some(index) = self.lookup_path(&index_path)?
                    && index.is_file
                {
                    if !scope_path.ends_with('/') {
                        return Ok(StaticFilesResponse::Redirect {
                            path: format!("{scope_path}/"),
                        });
                    }
                    return self.file_response(index, 200, request_headers, true);
                }
            }
        }

        if self.html
            && let Some(not_found) = self.lookup_path("404.html")?
            && not_found.is_file
        {
            return Ok(StaticFilesResponse::File {
                file: not_found,
                status_code: 404,
            });
        }
        Err(StaticFilesError::NotFound)
    }

    fn file_response(
        &self,
        file: StaticFile,
        status_code: u16,
        request_headers: &[(Vec<u8>, Vec<u8>)],
        conditional: bool,
    ) -> Result<StaticFilesResponse, StaticFilesError> {
        if conditional {
            let response = FileResponse::new(
                file.path.clone(),
                file.path.display().to_string(),
                status_code,
                &[],
                FileResponseOptions {
                    stat_override: Some(file.metadata.clone()),
                    ..FileResponseOptions::default()
                },
            )
            .map_err(StaticFilesError::FileResponse)?;
            if is_not_modified(response.headers(), request_headers) {
                let headers = response
                    .headers()
                    .iter()
                    .filter(|(name, _)| {
                        matches!(
                            name.as_slice(),
                            b"cache-control"
                                | b"content-location"
                                | b"date"
                                | b"etag"
                                | b"expires"
                                | b"vary"
                        )
                    })
                    .cloned()
                    .collect();
                return Ok(StaticFilesResponse::NotModified { headers });
            }
        }
        Ok(StaticFilesResponse::File { file, status_code })
    }
}

fn static_file(path: PathBuf, metadata: &Metadata) -> Result<StaticFile, StaticFilesError> {
    let is_file = metadata.is_file();
    let is_directory = metadata.is_dir();
    let metadata = FileMetadata::from_metadata(metadata).map_err(StaticFilesError::FileResponse)?;
    Ok(StaticFile {
        path,
        metadata,
        is_file,
        is_directory,
    })
}

fn is_not_modified(
    response_headers: &[(Vec<u8>, Vec<u8>)],
    request_headers: &[(Vec<u8>, Vec<u8>)],
) -> bool {
    let etag = header(response_headers, b"etag");
    if let Some(if_none_match) =
        header(request_headers, b"if-none-match").filter(|value| !value.is_empty())
    {
        return etag.is_some_and(|etag| {
            if_none_match
                .split(',')
                .map(str::trim)
                .map(|tag| tag.strip_prefix("W/").unwrap_or(tag))
                .any(|tag| tag == etag)
        });
    }
    let (Some(if_modified_since), Some(last_modified)) = (
        header(request_headers, b"if-modified-since"),
        header(response_headers, b"last-modified"),
    ) else {
        return false;
    };
    match (
        httpdate::parse_http_date(if_modified_since.trim()),
        httpdate::parse_http_date(last_modified.trim()),
    ) {
        (Ok(request_time), Ok(modified_time)) => request_time >= modified_time,
        _ => false,
    }
}

fn header(headers: &[(Vec<u8>, Vec<u8>)], name: &[u8]) -> Option<String> {
    headers
        .iter()
        .find(|(header_name, _)| header_name.eq_ignore_ascii_case(name))
        .map(|(_, value)| value.iter().map(|byte| char::from(*byte)).collect())
}

fn route_path<'a>(path: &'a str, root_path: &str) -> &'a str {
    if root_path.is_empty() || !path.starts_with(root_path) || path == root_path {
        return if path == root_path && !root_path.is_empty() {
            ""
        } else {
            path
        };
    }
    path.strip_prefix(root_path)
        .filter(|route_path| route_path.starts_with('/'))
        .unwrap_or(path)
}

fn normalize_route_path(path: &str) -> String {
    let mut components = Vec::new();
    for component in path.split('/') {
        match component {
            "" | "." => {}
            ".." if components.last().is_some_and(|part| *part != "..") => {
                components.pop();
            }
            ".." => components.push(".."),
            other => components.push(other),
        }
    }
    if components.is_empty() {
        ".".to_owned()
    } else {
        components.join("/")
    }
}

fn join_relative(path: &str, child: &str) -> String {
    if path.is_empty() {
        child.to_owned()
    } else {
        format!("{path}/{child}")
    }
}

fn absolute_path(path: &Path) -> Result<PathBuf, StaticFilesError> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(StaticFilesError::Io)?
            .join(path)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    Ok(normalized)
}

fn is_name_too_long(error: &io::Error) -> bool {
    matches!(error.raw_os_error(), Some(36 | 63))
}
