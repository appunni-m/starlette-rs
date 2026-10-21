//! Rust-owned path lookup and response selection for Starlette static files.

use std::ffi::{OsStr, OsString};
use std::fs::{self, Metadata};
use std::io;
use std::path::{Component, Path, PathBuf};

#[cfg(unix)]
use std::os::unix::ffi::{OsStrExt, OsStringExt};

use crate::{FileMetadata, FileResponse, FileResponseError, FileResponseOptions};

mod http_date;
pub use http_date::{is_not_modified_headers, not_modified_headers};

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

impl StaticFile {
    /// Creates a lookup result from an explicit filesystem stat result.
    ///
    /// The mode type bits use the values shared by POSIX `st_mode` and
    /// Python's `stat.S_IFMT` helpers.
    #[must_use]
    pub fn from_path_and_metadata(path: PathBuf, metadata: FileMetadata, mode: u32) -> Self {
        let file_type = mode & 0o170_000;
        Self {
            path,
            metadata,
            is_file: file_type == 0o100_000,
            is_directory: file_type == 0o040_000,
        }
    }
}

/// The response selected by the StaticFiles protocol policy.
// LINT EXCEPTION: Keep the public file payload by value because boxing would change this consumer API.
#[allow(clippy::large_enum_variant)]
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
        path: OsString,
    },
}

/// The next operation in an asynchronous static-file response flow.
// LINT EXCEPTION: Keep this public transition's response by value because boxing would change its API.
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StaticFilesResponseStep {
    /// Look up this path and resume the flow with its result.
    Lookup(OsString),
    /// Invoke the consumer's `StaticFiles.file_response` hook with this file.
    SelectFileResponse {
        /// Resolved file and response metadata.
        file: StaticFile,
        /// HTTP status selected for the file response.
        status_code: u16,
    },
    /// The Rust response policy has selected its final response.
    Complete(StaticFilesResponse),
}

/// Rust-owned state for response selection when filesystem lookups are supplied
/// asynchronously by a caller such as the Python AnyIO boundary.
#[derive(Debug)]
pub struct StaticFilesResponseFlow {
    path: OsString,
    scope_path: OsString,
    phase: ResponseFlowPhase,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ResponseFlowPhase {
    InitialLookup,
    IndexLookup,
    NotFoundLookup,
    Complete,
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
    /// The lookup path contains a character that the operating system cannot represent.
    InvalidPath,
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
        let directory_error = match (check_dir, directory.as_ref()) {
            (true, Some(directory))
                if !fs::metadata(directory).is_ok_and(|metadata| metadata.is_dir()) =>
            {
                Some(StaticFilesError::DirectoryConfiguration(format!(
                    "Directory '{}' does not exist",
                    directory.display()
                )))
            }
            _ => None,
        };
        if let Some(error) = directory_error {
            return Err(error);
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
        Self::check_config_path(directory)
    }

    /// Validates a directory supplied by a compatibility boundary at call time.
    pub fn check_config_path(directory: &Path) -> Result<(), StaticFilesError> {
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

    /// Derives the normalized native relative path from an ASGI path and root path.
    ///
    /// Native OS strings retain filesystem bytes that cannot be represented in
    /// UTF-8, including Python's Unix surrogateescape values.
    #[must_use]
    pub fn get_path<P: AsRef<OsStr>, R: AsRef<OsStr>>(path: P, root_path: R) -> OsString {
        let route_path = route_path(path.as_ref(), root_path.as_ref());
        normalize_route_path(&route_path)
    }

    /// Normalizes components returned by the Python compatibility boundary's
    /// `route_path.split("/")` call.
    ///
    /// `PathBuf::push` supplies the platform path-join behavior, while this
    /// type retains ownership of the final OS-specific normalization.
    #[doc(hidden)]
    #[must_use]
    pub fn get_path_from_components<P, I>(components: I) -> OsString
    where
        P: AsRef<Path>,
        I: IntoIterator<Item = P>,
    {
        let mut joined_path = PathBuf::new();
        for component in components {
            joined_path.push(component);
        }
        normalize_joined_path(joined_path.as_os_str())
    }

    /// Looks up a relative native path while enforcing the configured-root boundary.
    pub fn lookup_path<P: AsRef<OsStr>>(
        &self,
        path: P,
    ) -> Result<Option<StaticFile>, StaticFilesError> {
        self.lookup_path_in_order(path, None, false, None)
    }

    /// Looks up a path using an absolute-path decision supplied by a Python
    /// compatibility boundary.
    ///
    /// Python `str` subclasses can override `startswith`, which Starlette uses
    /// to reject absolute paths. The binding evaluates that method while the
    /// GIL is held and passes its truth value here so the filesystem lookup
    /// remains native without replacing the source protocol decision.
    #[doc(hidden)]
    pub fn lookup_path_with_absolute_path_result<P: AsRef<OsStr>>(
        &self,
        path: P,
        is_absolute: bool,
    ) -> Result<Option<StaticFile>, StaticFilesError> {
        self.lookup_path_in_order(path, None, false, Some(is_absolute))
    }

    /// Looks up a relative path using a directory value resolved at call time.
    ///
    /// The first path is joined with the relative request path. The second path
    /// is used as the root boundary. Keeping them separate preserves Python
    /// `PathLike` objects whose `__fspath__` result changes between calls.
    pub fn lookup_path_with_directory<P: AsRef<OsStr>>(
        &self,
        path: P,
        directory: Option<(&Path, &Path)>,
    ) -> Result<Option<StaticFile>, StaticFilesError> {
        let skip_first_static_directory = directory.is_some() && self.directory.is_some();
        self.lookup_path_in_order(
            path,
            directory.map(|(joined, boundary)| (0, joined, boundary)),
            skip_first_static_directory,
            None,
        )
    }

    /// Looks up a relative path with a dynamic directory inserted after the
    /// requested number of configured roots.
    ///
    /// `directory_index` counts the static roots that precede the dynamic
    /// directory. This keeps Python `PathLike` roots in the order returned by
    /// `StaticFiles.get_directories`, including subclass overrides.
    pub fn lookup_path_with_directory_at<P: AsRef<OsStr>>(
        &self,
        path: P,
        directory_index: usize,
        joined_directory: &Path,
        boundary_directory: &Path,
    ) -> Result<Option<StaticFile>, StaticFilesError> {
        self.lookup_path_in_order(
            path,
            Some((directory_index, joined_directory, boundary_directory)),
            false,
            None,
        )
    }

    /// Looks up a path using a source-provided absolute-path decision and a
    /// directory inserted into the configured lookup order.
    #[doc(hidden)]
    pub fn lookup_path_with_directory_at_and_absolute_path_result<P: AsRef<OsStr>>(
        &self,
        path: P,
        directory_index: usize,
        joined_directory: &Path,
        boundary_directory: &Path,
        is_absolute: bool,
    ) -> Result<Option<StaticFile>, StaticFilesError> {
        self.lookup_path_in_order(
            path,
            Some((directory_index, joined_directory, boundary_directory)),
            false,
            Some(is_absolute),
        )
    }

    fn lookup_path_in_order<P: AsRef<OsStr>>(
        &self,
        path: P,
        directory: Option<(usize, &Path, &Path)>,
        mut skip_first_static_directory: bool,
        is_absolute: Option<bool>,
    ) -> Result<Option<StaticFile>, StaticFilesError> {
        let path = path.as_ref();
        if is_absolute.unwrap_or_else(|| is_absolute_lookup_path(path)) {
            return Ok(None);
        }
        // Starlette reaches os.stat only while trying a configured root. With
        // no roots, an embedded NUL path is never passed to the OS and is not
        // an error.
        if (directory.is_some() || !self.directories.is_empty()) && contains_nul(path) {
            return Err(StaticFilesError::InvalidPath);
        }
        if let Some((directory_index, joined_directory, boundary_directory)) = directory {
            // The dynamic directory is inserted at its original position
            // among the roots returned by `get_directories`.
            for (static_directories_before, configured_directory) in
                self.directories.iter().enumerate()
            {
                if directory_index == static_directories_before {
                    if let Some(file) = lookup_in_directory(
                        path,
                        joined_directory,
                        boundary_directory,
                        self.follow_symlink,
                    )? {
                        return Ok(Some(file));
                    }
                }
                if skip_first_static_directory {
                    skip_first_static_directory = false;
                } else if let Some(file) = lookup_in_directory(
                    path,
                    configured_directory,
                    configured_directory,
                    self.follow_symlink,
                )? {
                    return Ok(Some(file));
                }
            }
            if directory_index == self.directories.len() {
                return lookup_in_directory(
                    path,
                    joined_directory,
                    boundary_directory,
                    self.follow_symlink,
                );
            }
            return Ok(None);
        }
        for configured_directory in &self.directories {
            if skip_first_static_directory {
                skip_first_static_directory = false;
                continue;
            }
            if let Some(file) = lookup_in_directory(
                path,
                configured_directory,
                configured_directory,
                self.follow_symlink,
            )? {
                return Ok(Some(file));
            }
        }
        Ok(None)
    }

    /// Selects the StaticFiles response for one request.
    pub fn get_response<P: AsRef<OsStr>, S: AsRef<OsStr>>(
        &self,
        path: P,
        scope_path: S,
        method: &str,
        request_headers: &[(Vec<u8>, Vec<u8>)],
    ) -> Result<StaticFilesResponse, StaticFilesError> {
        let (mut flow, mut step) =
            self.start_response_flow(path, scope_path, method, request_headers)?;
        loop {
            match step {
                StaticFilesResponseStep::Lookup(path) => {
                    step = flow.resume_lookup(self, self.lookup_path(&path))?;
                }
                StaticFilesResponseStep::SelectFileResponse { file, status_code } => {
                    return self.file_response(file, status_code, request_headers, true);
                }
                StaticFilesResponseStep::Complete(response) => return Ok(response),
            }
        }
    }

    /// Validates the request method accepted by StaticFiles response selection.
    ///
    /// Python compatibility callers use this before reading any request-scope
    /// values that Starlette only accesses after the method check.
    pub fn validate_response_method(method: &str) -> Result<(), StaticFilesError> {
        if method == "GET" || method == "HEAD" {
            Ok(())
        } else {
            Err(StaticFilesError::MethodNotAllowed)
        }
    }

    /// Starts Rust response selection and returns the first filesystem lookup.
    ///
    /// The method check happens before the first lookup, matching
    /// [`Self::get_response`]. Each subsequent lookup is requested by
    /// [`StaticFilesResponseFlow::resume_lookup`].
    pub fn start_response_flow<P: AsRef<OsStr>, S: AsRef<OsStr>>(
        &self,
        path: P,
        scope_path: S,
        method: &str,
        _request_headers: &[(Vec<u8>, Vec<u8>)],
    ) -> Result<(StaticFilesResponseFlow, StaticFilesResponseStep), StaticFilesError> {
        Self::validate_response_method(method)?;

        Ok((
            StaticFilesResponseFlow {
                path: path.as_ref().to_os_string(),
                scope_path: scope_path.as_ref().to_os_string(),
                phase: ResponseFlowPhase::InitialLookup,
            },
            StaticFilesResponseStep::Lookup(path.as_ref().to_os_string()),
        ))
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
            if is_not_modified_headers(response.headers(), request_headers) {
                let headers = not_modified_headers(response.headers());
                return Ok(StaticFilesResponse::NotModified { headers });
            }
        }
        Ok(StaticFilesResponse::File { file, status_code })
    }
}

impl StaticFilesResponseFlow {
    /// Returns whether the flow has reached the HTML index-file lookup phase.
    ///
    /// A Python compatibility caller needs the request scope path only when
    /// this lookup finds a file, matching Starlette's deferred `scope["path"]`
    /// access for directory redirects.
    #[must_use]
    pub fn needs_scope_path(&self) -> bool {
        self.phase == ResponseFlowPhase::IndexLookup
    }

    /// Supplies the request path when an HTML index lookup needs redirect
    /// selection.
    pub fn set_scope_path<P: AsRef<OsStr>>(&mut self, scope_path: P) {
        self.scope_path = scope_path.as_ref().to_os_string();
    }

    /// Supplies one lookup result and advances Rust response selection.
    ///
    /// Resume this flow once for each [`StaticFilesResponseStep::Lookup`]. A
    /// filesystem error terminates the flow and is returned unchanged, except
    /// that `InvalidPath` and `ENAMETOOLONG` from the initial lookup map to not
    /// found. Resuming a completed flow returns an invalid-input I/O error.
    pub fn resume_lookup(
        &mut self,
        static_files: &StaticFiles,
        result: Result<Option<StaticFile>, StaticFilesError>,
    ) -> Result<StaticFilesResponseStep, StaticFilesError> {
        if self.phase == ResponseFlowPhase::Complete {
            return Err(invalid_response_flow());
        }

        let lookup = match result {
            Ok(lookup) => lookup,
            Err(StaticFilesError::InvalidPath)
                if self.phase == ResponseFlowPhase::InitialLookup =>
            {
                self.phase = ResponseFlowPhase::Complete;
                return Err(StaticFilesError::NotFound);
            }
            Err(StaticFilesError::Io(error))
                if self.phase == ResponseFlowPhase::InitialLookup && is_name_too_long(&error) =>
            {
                self.phase = ResponseFlowPhase::Complete;
                return Err(StaticFilesError::NotFound);
            }
            Err(error) => {
                self.phase = ResponseFlowPhase::Complete;
                return Err(error);
            }
        };

        match self.phase {
            ResponseFlowPhase::InitialLookup => self.resume_initial_lookup(static_files, lookup),
            ResponseFlowPhase::IndexLookup => self.resume_index_lookup(static_files, lookup),
            ResponseFlowPhase::NotFoundLookup => self.resume_not_found_lookup(lookup),
            ResponseFlowPhase::Complete => Err(invalid_response_flow()),
        }
    }

    fn resume_initial_lookup(
        &mut self,
        static_files: &StaticFiles,
        lookup: Option<StaticFile>,
    ) -> Result<StaticFilesResponseStep, StaticFilesError> {
        if let Some(file) = lookup {
            if file.is_file {
                self.phase = ResponseFlowPhase::Complete;
                return Ok(StaticFilesResponseStep::SelectFileResponse {
                    file,
                    status_code: 200,
                });
            }
            if file.is_directory && static_files.html {
                self.phase = ResponseFlowPhase::IndexLookup;
                return Ok(StaticFilesResponseStep::Lookup(join_relative(
                    &self.path,
                    OsStr::new("index.html"),
                )));
            }
        }

        self.start_not_found_lookup(static_files)
    }

    fn resume_index_lookup(
        &mut self,
        static_files: &StaticFiles,
        lookup: Option<StaticFile>,
    ) -> Result<StaticFilesResponseStep, StaticFilesError> {
        if let Some(index) = lookup.filter(|file| file.is_file) {
            if ends_with_slash(&self.scope_path) {
                self.phase = ResponseFlowPhase::Complete;
                return Ok(StaticFilesResponseStep::SelectFileResponse {
                    file: index,
                    status_code: 200,
                });
            } else {
                let mut path = self.scope_path.clone();
                path.push("/");
                let response = StaticFilesResponse::Redirect { path };
                self.phase = ResponseFlowPhase::Complete;
                return Ok(StaticFilesResponseStep::Complete(response));
            }
        }

        self.start_not_found_lookup(static_files)
    }

    fn start_not_found_lookup(
        &mut self,
        static_files: &StaticFiles,
    ) -> Result<StaticFilesResponseStep, StaticFilesError> {
        if static_files.html {
            self.phase = ResponseFlowPhase::NotFoundLookup;
            Ok(StaticFilesResponseStep::Lookup(OsString::from("404.html")))
        } else {
            self.phase = ResponseFlowPhase::Complete;
            Err(StaticFilesError::NotFound)
        }
    }

    fn resume_not_found_lookup(
        &mut self,
        lookup: Option<StaticFile>,
    ) -> Result<StaticFilesResponseStep, StaticFilesError> {
        self.phase = ResponseFlowPhase::Complete;
        match lookup.filter(|file| file.is_file) {
            Some(file) => Ok(StaticFilesResponseStep::Complete(
                StaticFilesResponse::File {
                    file,
                    status_code: 404,
                },
            )),
            None => Err(StaticFilesError::NotFound),
        }
    }
}

fn invalid_response_flow() -> StaticFilesError {
    StaticFilesError::Io(io::Error::new(
        io::ErrorKind::InvalidInput,
        "static-file response flow has already completed",
    ))
}

fn is_absolute_lookup_path(path: &OsStr) -> bool {
    #[cfg(unix)]
    {
        path.as_bytes()
            .first()
            .is_some_and(|byte| *byte == b'/' || *byte == b'\\')
    }
    #[cfg(not(unix))]
    {
        path.to_str()
            .is_some_and(|value| value.starts_with('/') || value.starts_with('\\'))
    }
}

fn contains_nul(path: &OsStr) -> bool {
    #[cfg(unix)]
    {
        path.as_bytes().contains(&0)
    }
    #[cfg(not(unix))]
    {
        path.to_str().is_some_and(|value| value.contains('\0'))
    }
}

fn lookup_in_directory(
    path: &OsStr,
    joined_directory: &Path,
    boundary_directory: &Path,
    follow_symlink: bool,
) -> Result<Option<StaticFile>, StaticFilesError> {
    let joined_path = joined_directory.join(path);
    let (full_path, root_path) = if follow_symlink {
        (
            absolute_path(&joined_path)?,
            absolute_path(boundary_directory)?,
        )
    } else {
        let full_path = match fs::canonicalize(&joined_path) {
            Ok(path) => path,
            Err(error) if error.kind() == io::ErrorKind::PermissionDenied => {
                return Err(StaticFilesError::PermissionDenied);
            }
            Err(error) if is_name_too_long(&error) => {
                return Err(StaticFilesError::Io(error));
            }
            Err(error)
                if error.kind() == io::ErrorKind::NotFound
                    || error.kind() == io::ErrorKind::NotADirectory =>
            {
                // Python's non-strict `realpath` can return the normalized
                // missing path, after which Starlette's `stat` reports
                // ENAMETOOLONG. `canonicalize` may stop at the first missing
                // component instead, so probe `stat` to preserve an overflow
                // that would otherwise let lookup continue into a later root.
                return match fs::metadata(&joined_path) {
                    Err(stat_error) if is_name_too_long(&stat_error) => {
                        Err(StaticFilesError::Io(stat_error))
                    }
                    _ => Ok(None),
                };
            }
            Err(error) => return Err(StaticFilesError::Io(error)),
        };
        let root_path = match fs::canonicalize(boundary_directory) {
            Ok(path) => path,
            Err(error) if error.kind() == io::ErrorKind::PermissionDenied => {
                return Err(StaticFilesError::PermissionDenied);
            }
            Err(error)
                if error.kind() == io::ErrorKind::NotFound
                    || error.kind() == io::ErrorKind::NotADirectory =>
            {
                return Ok(None);
            }
            Err(error) => return Err(StaticFilesError::Io(error)),
        };
        (full_path, root_path)
    };
    if !full_path.starts_with(&root_path) {
        return Ok(None);
    }
    match fs::metadata(&full_path) {
        Ok(metadata) => Ok(Some(static_file(full_path, &metadata)?)),
        Err(error)
            if error.kind() == io::ErrorKind::NotFound
                || error.kind() == io::ErrorKind::NotADirectory =>
        {
            Ok(None)
        }
        Err(error) if is_name_too_long(&error) => Err(StaticFilesError::Io(error)),
        Err(error) if error.kind() == io::ErrorKind::PermissionDenied => {
            Err(StaticFilesError::PermissionDenied)
        }
        Err(error) => Err(StaticFilesError::Io(error)),
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

fn route_path(path: &OsStr, root_path: &OsStr) -> OsString {
    #[cfg(unix)]
    {
        let path_bytes = path.as_bytes();
        let root_bytes = root_path.as_bytes();
        if root_bytes.is_empty() || !path_bytes.starts_with(root_bytes) {
            return path.to_os_string();
        }
        if path_bytes == root_bytes {
            return OsString::new();
        }
        let route_path = &path_bytes[root_bytes.len()..];
        if route_path.starts_with(b"/") {
            OsString::from_vec(route_path.to_vec())
        } else {
            path.to_os_string()
        }
    }
    #[cfg(not(unix))]
    {
        let (Some(path_string), Some(root_string)) = (path.to_str(), root_path.to_str()) else {
            return path.to_os_string();
        };
        if root_string.is_empty() || !path_string.starts_with(root_string) {
            return path.to_os_string();
        }
        if path_string == root_string {
            return OsString::new();
        }
        path_string
            .strip_prefix(root_string)
            .filter(|route_path| route_path.starts_with('/'))
            .map_or_else(|| path.to_os_string(), OsString::from)
    }
}

fn normalize_route_path(path: &OsStr) -> OsString {
    #[cfg(windows)]
    {
        normalize_windows_route_path(path)
    }

    #[cfg(not(windows))]
    {
        normalize_posix_route_path(path)
    }
}

fn normalize_joined_path(path: &OsStr) -> OsString {
    #[cfg(windows)]
    {
        normalize_windows_route_path(path)
    }

    #[cfg(not(windows))]
    {
        normalize_posix_route_path_with_root(path, true)
    }
}

#[cfg(not(windows))]
fn normalize_posix_route_path(path: &OsStr) -> OsString {
    normalize_posix_route_path_with_root(path, false)
}

#[cfg(not(windows))]
fn normalize_posix_route_path_with_root(path: &OsStr, preserve_root: bool) -> OsString {
    #[cfg(unix)]
    {
        let path_bytes = path.as_bytes();
        let leading_slashes = path_bytes.iter().take_while(|byte| **byte == b'/').count();
        let root_prefix = if preserve_root && leading_slashes > 0 {
            if leading_slashes == 2 && path_bytes.get(2) != Some(&b'/') {
                b"//".as_slice()
            } else {
                b"/".as_slice()
            }
        } else {
            b"".as_slice()
        };
        let mut components: Vec<&[u8]> = Vec::new();
        for component in path_bytes.split(|byte| *byte == b'/') {
            match component {
                b"" | b"." => {}
                b".." if components.last().is_some_and(|part| *part != b"..") => {
                    components.pop();
                }
                b".." => components.push(component),
                other => components.push(other),
            }
        }
        if components.is_empty() {
            return if root_prefix.is_empty() {
                OsString::from(".")
            } else {
                OsString::from_vec(root_prefix.to_vec())
            };
        }
        let mut normalized = Vec::new();
        normalized.extend_from_slice(root_prefix);
        for (index, component) in components.into_iter().enumerate() {
            if index > 0 {
                normalized.push(b'/');
            }
            normalized.extend_from_slice(component);
        }
        OsString::from_vec(normalized)
    }
    #[cfg(not(unix))]
    {
        let Some(path) = path.to_str() else {
            return path.to_os_string();
        };
        let root_prefix = if preserve_root && path.starts_with('/') {
            if path.starts_with("//") && !path.starts_with("///") {
                "//"
            } else {
                "/"
            }
        } else {
            ""
        };
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
            if root_prefix.is_empty() {
                OsString::from(".")
            } else {
                OsString::from(root_prefix)
            }
        } else {
            OsString::from(format!("{root_prefix}{}", components.join("/")))
        }
    }
}

#[cfg(windows)]
fn normalize_windows_route_path(path: &OsStr) -> OsString {
    let Some(path) = path.to_str() else {
        return path.to_os_string();
    };
    let mut joined = PathBuf::new();
    for component in path.split('/') {
        joined.push(component);
    }

    let mut normalized = PathBuf::new();
    for component in joined.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => match normalized.components().next_back() {
                Some(Component::Normal(_)) => {
                    normalized.pop();
                }
                Some(Component::ParentDir) | None if !normalized.has_root() => {
                    normalized.push("..");
                }
                Some(Component::Prefix(_)) | Some(Component::RootDir) | _ => {}
            },
            other => normalized.push(other.as_os_str()),
        }
    }

    if normalized.as_os_str().is_empty() {
        OsString::from(".")
    } else {
        normalized.into_os_string()
    }
}

fn join_relative(path: &OsStr, child: &OsStr) -> OsString {
    if path.is_empty() {
        child.to_os_string()
    } else {
        let mut joined = PathBuf::from(path);
        joined.push(child);
        joined.into_os_string()
    }
}

fn ends_with_slash(path: &OsStr) -> bool {
    #[cfg(unix)]
    {
        path.as_bytes().ends_with(b"/")
    }
    #[cfg(not(unix))]
    {
        path.to_str().is_some_and(|value| value.ends_with('/'))
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
