//! Rust-native ordered HTTP header collections.
//!
//! Header names are stored exactly as supplied. Lookups and mutations expect
//! the caller to pass the normalized name bytes (Starlette normalizes names by
//! lowercasing and Latin-1 encoding the Python string at its boundary).

use std::ops::Deref;

type RawHeader = (Vec<u8>, Vec<u8>);

/// An immutable snapshot of ordered raw HTTP headers.
///
/// Duplicate fields and their original bytes are retained. Mapping-style
/// snapshots preserve pair order and include duplicate names. Name lookup is
/// exact over the supplied byte sequence; callers should normalize names
/// before looking them up.
#[derive(Clone, Debug, Default)]
pub struct Headers {
    raw: Vec<RawHeader>,
}

/// An ordered HTTP header collection with Starlette-style mutations.
///
/// It dereferences to [`Headers`] for read-only lookup and snapshot methods.
/// Header names passed to mutations must already be normalized by the caller.
#[derive(Clone, Debug, Default)]
pub struct MutableHeaders {
    inner: Headers,
}

impl Headers {
    /// Creates an empty header collection.
    #[must_use]
    pub const fn new() -> Self {
        Self { raw: Vec::new() }
    }

    /// Creates a collection from raw header pairs, preserving order and bytes.
    #[must_use]
    pub fn from_raw(raw: Vec<(Vec<u8>, Vec<u8>)>) -> Self {
        Self { raw }
    }

    /// Borrows the ordered raw header pairs.
    #[must_use]
    pub fn raw_pairs(&self) -> &[(Vec<u8>, Vec<u8>)] {
        &self.raw
    }

    /// Returns the first exact-byte match for a normalized header name.
    #[must_use]
    pub fn get(&self, name: &[u8]) -> Option<&[u8]> {
        self.raw
            .iter()
            .find(|(header_name, _)| header_name.as_slice() == name)
            .map(|(_, value)| value.as_slice())
    }

    /// Returns every exact-byte match for a normalized header name in order.
    #[must_use]
    pub fn get_list(&self, name: &[u8]) -> Vec<&[u8]> {
        self.raw
            .iter()
            .filter(|(header_name, _)| header_name.as_slice() == name)
            .map(|(_, value)| value.as_slice())
            .collect()
    }

    /// Returns whether a normalized header name has an exact-byte match.
    #[must_use]
    pub fn contains_key(&self, name: &[u8]) -> bool {
        self.raw
            .iter()
            .any(|(header_name, _)| header_name.as_slice() == name)
    }

    /// Returns header names decoded as Latin-1, including duplicate names.
    #[must_use]
    pub fn keys(&self) -> Vec<String> {
        self.raw
            .iter()
            .map(|(name, _)| decode_latin1(name))
            .collect()
    }

    /// Returns header values decoded as Latin-1, including duplicate values.
    #[must_use]
    pub fn values(&self) -> Vec<String> {
        self.raw
            .iter()
            .map(|(_, value)| decode_latin1(value))
            .collect()
    }

    /// Returns ordered name/value snapshots decoded as Latin-1.
    #[must_use]
    pub fn items(&self) -> Vec<(String, String)> {
        self.raw
            .iter()
            .map(|(name, value)| (decode_latin1(name), decode_latin1(value)))
            .collect()
    }

    /// Returns the number of raw header pairs, counting duplicates.
    #[must_use]
    pub fn len(&self) -> usize {
        self.raw.len()
    }

    /// Returns whether this collection has no raw header pairs.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.raw.is_empty()
    }

    /// Clones this collection into a mutable header collection.
    #[must_use]
    pub fn mutablecopy(&self) -> MutableHeaders {
        MutableHeaders {
            inner: self.clone(),
        }
    }
}

impl MutableHeaders {
    /// Creates an empty mutable header collection.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            inner: Headers::new(),
        }
    }

    /// Creates a mutable collection from raw pairs, preserving order and bytes.
    #[must_use]
    pub fn from_raw(raw: Vec<(Vec<u8>, Vec<u8>)>) -> Self {
        Self {
            inner: Headers::from_raw(raw),
        }
    }

    /// Borrows this collection's ordered raw header pairs.
    #[must_use]
    pub fn raw_pairs(&self) -> &[(Vec<u8>, Vec<u8>)] {
        self.inner.raw_pairs()
    }

    /// Mutably borrows the raw pairs for boundary synchronization.
    ///
    /// Direct edits bypass header normalization and duplicate handling. Use
    /// [`set`](Self::set), [`delete`](Self::delete), or [`append`](Self::append)
    /// for Starlette-style mutations.
    pub fn raw_pairs_mut(&mut self) -> &mut Vec<(Vec<u8>, Vec<u8>)> {
        &mut self.inner.raw
    }

    /// Borrows the immutable view of this collection.
    #[must_use]
    pub const fn as_headers(&self) -> &Headers {
        &self.inner
    }

    /// Consumes this collection and returns its raw pairs.
    #[must_use]
    pub fn into_raw(self) -> Vec<(Vec<u8>, Vec<u8>)> {
        self.inner.raw
    }

    /// Replaces the first exact-byte match and removes later duplicates.
    ///
    /// If no pair matches, the new pair is appended. The name must already be
    /// normalized by the caller.
    pub fn set(&mut self, name: &[u8], value: &[u8]) {
        let mut found = false;
        self.inner.raw.retain_mut(|(header_name, header_value)| {
            if header_name.as_slice() != name {
                return true;
            }
            if found {
                return false;
            }
            *header_value = value.to_vec();
            found = true;
            true
        });
        if !found {
            self.inner.raw.push((name.to_vec(), value.to_vec()));
        }
    }

    /// Removes every exact-byte match for a normalized header name.
    pub fn delete(&mut self, name: &[u8]) {
        self.inner
            .raw
            .retain(|(header_name, _)| header_name.as_slice() != name);
    }

    /// Returns the first value or appends and returns `value` when absent.
    ///
    /// Existing duplicate pairs are left untouched. The name must already be
    /// normalized by the caller.
    pub fn setdefault(&mut self, name: &[u8], value: &[u8]) -> Vec<u8> {
        if let Some(existing) = self.inner.get(name) {
            return existing.to_vec();
        }
        self.inner.raw.push((name.to_vec(), value.to_vec()));
        value.to_vec()
    }

    /// Appends a pair without removing existing matches.
    ///
    /// The name must already be normalized by the caller.
    pub fn append(&mut self, name: &[u8], value: &[u8]) {
        self.inner.raw.push((name.to_vec(), value.to_vec()));
    }

    /// Applies ordered replacements for the supplied raw header pairs.
    ///
    /// Each name must already be normalized by the caller.
    pub fn update(&mut self, headers: impl IntoIterator<Item = (Vec<u8>, Vec<u8>)>) {
        for (name, value) in headers {
            self.set(&name, &value);
        }
    }
}

impl Deref for MutableHeaders {
    type Target = Headers;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

impl PartialEq for Headers {
    fn eq(&self, other: &Self) -> bool {
        unordered_raw_pairs_equal(&self.raw, &other.raw)
    }
}

impl Eq for Headers {}

impl PartialEq for MutableHeaders {
    fn eq(&self, other: &Self) -> bool {
        self.inner == other.inner
    }
}

impl Eq for MutableHeaders {}

impl PartialEq<MutableHeaders> for Headers {
    fn eq(&self, other: &MutableHeaders) -> bool {
        unordered_raw_pairs_equal(&self.raw, other.raw_pairs())
    }
}

impl PartialEq<Headers> for MutableHeaders {
    fn eq(&self, other: &Headers) -> bool {
        unordered_raw_pairs_equal(self.raw_pairs(), other.raw_pairs())
    }
}

fn unordered_raw_pairs_equal(left: &[RawHeader], right: &[RawHeader]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut left_pairs: Vec<_> = left.iter().collect();
    let mut right_pairs: Vec<_> = right.iter().collect();
    left_pairs.sort_unstable();
    right_pairs.sort_unstable();
    left_pairs == right_pairs
}

fn decode_latin1(value: &[u8]) -> String {
    value.iter().copied().map(char::from).collect()
}
