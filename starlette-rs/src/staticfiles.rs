//! Rust-owned path lookup and response selection for Starlette static files.

use std::fs::{self, Metadata};
use std::io;
use std::path::{Component, Path, PathBuf};
use std::time::SystemTime;

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
        path: String,
    },
}

/// The next operation in an asynchronous static-file response flow.
// LINT EXCEPTION: Keep this public transition's response by value because boxing would change its API.
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StaticFilesResponseStep {
    /// Look up this path and resume the flow with its result.
    Lookup(String),
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
    path: String,
    scope_path: String,
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

    /// Derives the normalized relative path from an ASGI path and root path.
    #[must_use]
    pub fn get_path(path: &str, root_path: &str) -> String {
        let route_path = route_path(path, root_path);
        normalize_route_path(route_path)
    }

    /// Looks up a relative path while enforcing the configured-root boundary.
    pub fn lookup_path(&self, path: &str) -> Result<Option<StaticFile>, StaticFilesError> {
        self.lookup_path_with_directory(path, None)
    }

    /// Looks up a relative path using a directory value resolved at call time.
    ///
    /// The first path is joined with the relative request path. The second path
    /// is used as the root boundary. Keeping them separate preserves Python
    /// `PathLike` objects whose `__fspath__` result changes between calls.
    pub fn lookup_path_with_directory(
        &self,
        path: &str,
        directory: Option<(&Path, &Path)>,
    ) -> Result<Option<StaticFile>, StaticFilesError> {
        if path.starts_with('/') || path.starts_with('\\') {
            return Ok(None);
        }
        if path.contains('\0') {
            return Err(StaticFilesError::InvalidPath);
        }
        if let Some((joined_directory, boundary_directory)) = directory {
            if let Some(file) = lookup_in_directory(
                path,
                joined_directory,
                boundary_directory,
                self.follow_symlink,
            )? {
                return Ok(Some(file));
            }
        }
        let first_static_directory = usize::from(directory.is_some() && self.directory.is_some());
        for configured_directory in self.directories.iter().skip(first_static_directory) {
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
    pub fn get_response(
        &self,
        path: &str,
        scope_path: &str,
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

    /// Starts Rust response selection and returns the first filesystem lookup.
    ///
    /// The method check happens before the first lookup, matching
    /// [`Self::get_response`]. Each subsequent lookup is requested by
    /// [`StaticFilesResponseFlow::resume_lookup`].
    pub fn start_response_flow(
        &self,
        path: &str,
        scope_path: &str,
        method: &str,
        _request_headers: &[(Vec<u8>, Vec<u8>)],
    ) -> Result<(StaticFilesResponseFlow, StaticFilesResponseStep), StaticFilesError> {
        if method != "GET" && method != "HEAD" {
            return Err(StaticFilesError::MethodNotAllowed);
        }

        Ok((
            StaticFilesResponseFlow {
                path: path.to_owned(),
                scope_path: scope_path.to_owned(),
                phase: ResponseFlowPhase::InitialLookup,
            },
            StaticFilesResponseStep::Lookup(path.to_owned()),
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
                    "index.html",
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
            if self.scope_path.ends_with('/') {
                self.phase = ResponseFlowPhase::Complete;
                return Ok(StaticFilesResponseStep::SelectFileResponse {
                    file: index,
                    status_code: 200,
                });
            } else {
                let response = StaticFilesResponse::Redirect {
                    path: format!("{}/", self.scope_path),
                };
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
            Ok(StaticFilesResponseStep::Lookup("404.html".to_owned()))
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

fn lookup_in_directory(
    path: &str,
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
                    || error.kind() == io::ErrorKind::NotADirectory
                    || error.kind() == io::ErrorKind::InvalidInput =>
            {
                return Ok(None);
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
        Err(error) if error.kind() == io::ErrorKind::InvalidInput => Ok(None),
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

/// Returns whether the response validators satisfy the request headers.
#[must_use]
pub fn is_not_modified_headers(
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
        parse_http_date_ignoring_weekday(&if_modified_since),
        parse_http_date_ignoring_weekday(&last_modified),
    ) {
        (Some(request_time), Some(modified_time)) => request_time >= modified_time,
        _ => false,
    }
}

/// Selects the response headers retained by a 304 Not Modified response.
#[must_use]
pub fn not_modified_headers(headers: &[(Vec<u8>, Vec<u8>)]) -> Vec<(Vec<u8>, Vec<u8>)> {
    headers
        .iter()
        .filter(|(name, _)| {
            matches!(
                name.as_slice(),
                b"cache-control" | b"content-location" | b"date" | b"etag" | b"expires" | b"vary"
            )
        })
        .cloned()
        .collect()
}

fn parse_http_date_ignoring_weekday(value: &str) -> Option<SystemTime> {
    const ABBREVIATED_WEEKDAYS: [&str; 7] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const FULL_WEEKDAYS: [&str; 7] = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ];

    let value = strip_trailing_email_comments(value.trim());
    let normalized_timezone = normalize_email_timezone(value);
    let value = normalized_timezone.as_deref().unwrap_or(value);
    let normalized_month = normalize_email_month(value);
    let value = normalized_month.as_deref().unwrap_or(value);
    if let Ok(timestamp) = httpdate::parse_http_date(value) {
        return Some(timestamp);
    }

    let (weekday, rest, comma_separated) = if let Some((weekday, rest)) = value.split_once(',') {
        (weekday, rest, true)
    } else {
        let (weekday, rest) = value.split_once(char::is_whitespace)?;
        (weekday, rest, false)
    };
    let replacements = if ABBREVIATED_WEEKDAYS
        .iter()
        .any(|candidate| candidate.eq_ignore_ascii_case(weekday))
    {
        &ABBREVIATED_WEEKDAYS[..]
    } else if FULL_WEEKDAYS
        .iter()
        .any(|candidate| candidate.eq_ignore_ascii_case(weekday))
    {
        &FULL_WEEKDAYS[..]
    } else {
        // `email.utils.parsedate` also accepts RFC-2822-style dates without a
        // weekday. Try each weekday so `httpdate` can validate the remaining
        // date fields while retaining Starlette's weekday-agnostic comparison.
        return ABBREVIATED_WEEKDAYS.iter().find_map(|replacement| {
            let normalized = format!("{replacement}, {value}");
            httpdate::parse_http_date(&normalized)
                .ok()
                .or_else(|| httpdate::parse_http_date(&format!("{normalized} GMT")).ok())
        });
    };

    replacements.iter().find_map(|replacement| {
        let normalized = if comma_separated {
            format!("{replacement},{rest}")
        } else {
            format!("{replacement}{rest}")
        };
        httpdate::parse_http_date(&normalized)
            .ok()
            .or_else(|| httpdate::parse_http_date(&format!("{normalized} GMT")).ok())
    })
}

/// Normalizes Python email-date month tokens to the abbreviated form accepted
/// by `httpdate`. `email.utils.parsedate` accepts full and mixed-case English
/// month names in `If-Modified-Since` values.
fn normalize_email_month(value: &str) -> Option<String> {
    let mut normalized = String::with_capacity(value.len());
    let mut changed = false;
    let mut token_start = None;

    for (index, character) in value.char_indices() {
        if character.is_ascii_alphabetic() {
            token_start.get_or_insert(index);
        } else {
            if let Some(start) = token_start.take() {
                changed |= push_email_month(&mut normalized, &value[start..index]);
            }
            normalized.push(character);
        }
    }
    if let Some(start) = token_start {
        changed |= push_email_month(&mut normalized, &value[start..]);
    }

    changed.then_some(normalized)
}

fn push_email_month(normalized: &mut String, token: &str) -> bool {
    if let Some(abbreviation) = email_month_abbreviation(token) {
        normalized.push_str(abbreviation);
        true
    } else {
        normalized.push_str(token);
        false
    }
}

fn email_month_abbreviation(value: &str) -> Option<&'static str> {
    const MONTHS: [(&str, &str); 12] = [
        ("January", "Jan"),
        ("February", "Feb"),
        ("March", "Mar"),
        ("April", "Apr"),
        ("May", "May"),
        ("June", "Jun"),
        ("July", "Jul"),
        ("August", "Aug"),
        ("September", "Sep"),
        ("October", "Oct"),
        ("November", "Nov"),
        ("December", "Dec"),
    ];

    MONTHS.iter().find_map(|(full, abbreviated)| {
        (value.eq_ignore_ascii_case(full) || value.eq_ignore_ascii_case(abbreviated))
            .then_some(*abbreviated)
    })
}

/// Removes terminal RFC date comments accepted by `email.utils.parsedate`.
fn strip_trailing_email_comments(mut value: &str) -> &str {
    value = value.trim_end();
    loop {
        if !value.ends_with(')') {
            return value;
        }

        let mut depth = 0_usize;
        let mut escaped = false;
        let mut opening = None;
        let mut terminal_comment_start = None;
        for (index, byte) in value.bytes().enumerate() {
            if escaped {
                escaped = false;
                continue;
            }
            if byte == b'\\' && depth > 0 {
                escaped = true;
                continue;
            }
            match byte {
                b'(' => {
                    if depth == 0 {
                        opening = Some(index);
                    }
                    depth += 1;
                }
                b')' if depth > 0 => {
                    depth -= 1;
                    if depth == 0 && index + 1 == value.len() {
                        terminal_comment_start = opening;
                        break;
                    }
                }
                _ => {}
            }
        }
        let Some(opening) = terminal_comment_start else {
            return value;
        };
        value = value[..opening].trim_end();
    }
}

fn normalize_email_timezone(value: &str) -> Option<String> {
    let (date, timezone) = value.rsplit_once(' ')?;
    let timezone = timezone.as_bytes();
    let numeric_offset = timezone.len() == 5
        && matches!(timezone[0], b'+' | b'-')
        && timezone[1..].iter().all(u8::is_ascii_digit);
    let named_timezone = !timezone.is_empty() && timezone.iter().all(u8::is_ascii_alphabetic);
    if !numeric_offset && !named_timezone {
        return None;
    }

    // Starlette's email.utils.parsedate discards the parsed timezone from its
    // returned tuple, so the compatibility comparison uses the date fields as
    // written rather than converting the timestamp to UTC. The source parser
    // also accepts an omitted timezone and treats its date fields the same as
    // GMT. It accepts both numeric offsets and named timezone tokens, including
    // names outside its known offset table, and discards them for comparison.
    Some(format!("{date} GMT"))
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
    #[cfg(windows)]
    {
        return normalize_windows_route_path(path);
    }

    #[cfg(not(windows))]
    {
        normalize_posix_route_path(path)
    }
}

#[cfg(not(windows))]
fn normalize_posix_route_path(path: &str) -> String {
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

#[cfg(windows)]
fn normalize_windows_route_path(path: &str) -> String {
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
        ".".to_owned()
    } else {
        normalized.to_string_lossy().into_owned()
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
