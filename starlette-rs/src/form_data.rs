//! Rust-owned form values and URL-encoded form parsing.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

use crate::QueryParams;

/// Immutable ordered form items with last-value mapping lookup semantics.
///
/// Repeated keys and their wire order are retained by [`multi_items`](Self::multi_items),
/// while scalar lookup returns the last value for a key, as Starlette's
/// `ImmutableMultiDict` does. This native slice stores text fields; file uploads
/// are outside its supported form parser surface.
#[derive(Clone, Debug, Default)]
pub struct FormData {
    items: Vec<(String, String)>,
}

impl FormData {
    /// Creates form data from ordered text key/value pairs.
    #[must_use]
    pub fn from_pairs(items: impl IntoIterator<Item = (String, String)>) -> Self {
        Self {
            items: items.into_iter().collect(),
        }
    }

    /// Parses a URL-encoded request body using Starlette's query-string
    /// decoding rules and form field limits.
    pub fn parse_urlencoded(
        body: &[u8],
        max_fields: f64,
        max_part_size: i64,
    ) -> Result<Self, FormDataParseError> {
        let fields = body
            .split(|byte| *byte == b'&')
            .filter(|field| !field.is_empty());
        let mut field_count = 0usize;
        for field in fields {
            field_count += 1;
            let size = field.len() - usize::from(field.contains(&b'='));
            if size as i128 > i128::from(max_part_size) {
                return Err(FormDataParseError::FieldTooLarge {
                    max_part_size_kb: max_part_size / 1024,
                });
            }
            if field_count as f64 > max_fields {
                return Err(FormDataParseError::TooManyFields);
            }
        }

        Ok(Self::from_pairs(
            QueryParams::parse(body).multi_items().iter().cloned(),
        ))
    }

    /// Returns the last value for `key`, or `None` when it is absent.
    #[must_use]
    pub fn get(&self, key: &str) -> Option<&str> {
        self.items
            .iter()
            .rev()
            .find(|(item_key, _)| item_key == key)
            .map(|(_, value)| value.as_str())
    }

    /// Returns every value for `key` in form order.
    #[must_use]
    pub fn get_list(&self, key: &str) -> Vec<&str> {
        self.items
            .iter()
            .filter(|(item_key, _)| item_key == key)
            .map(|(_, value)| value.as_str())
            .collect()
    }

    /// Returns every pair, retaining repeated keys and original order.
    #[must_use]
    pub fn multi_items(&self) -> &[(String, String)] {
        &self.items
    }

    /// Returns distinct keys in first-occurrence order.
    #[must_use]
    pub fn keys(&self) -> Vec<&str> {
        self.items
            .iter()
            .enumerate()
            .filter(|(index, (key, _))| {
                !self.items[..*index]
                    .iter()
                    .any(|(prior_key, _)| prior_key == key)
            })
            .map(|(_, (key, _))| key.as_str())
            .collect()
    }

    /// Returns the final value for each key in first-occurrence key order.
    #[must_use]
    pub fn values(&self) -> Vec<&str> {
        self.keys()
            .into_iter()
            .filter_map(|key| self.get(key))
            .collect()
    }

    /// Returns one final-value pair per key in first-occurrence key order.
    #[must_use]
    pub fn items(&self) -> Vec<(&str, &str)> {
        self.keys()
            .into_iter()
            .filter_map(|key| self.get(key).map(|value| (key, value)))
            .collect()
    }

    /// Returns the number of distinct keys.
    #[must_use]
    pub fn len(&self) -> usize {
        self.keys().len()
    }

    /// Returns whether no form pairs are present.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }
}

impl PartialEq for FormData {
    fn eq(&self, other: &Self) -> bool {
        let mut left = self.items.clone();
        let mut right = other.items.clone();
        left.sort_unstable();
        right.sort_unstable();
        left == right
    }
}

impl Eq for FormData {}

/// A URL-encoded form parse failure caused by configured field limits.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FormDataParseError {
    /// The number of non-empty form fields exceeded `max_fields`.
    TooManyFields,
    /// A raw encoded field exceeded `max_part_size`.
    FieldTooLarge {
        /// The configured part size converted to the parser's displayed KB value.
        max_part_size_kb: i64,
    },
}

impl Display for FormDataParseError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::TooManyFields => formatter.write_str("Too many fields"),
            Self::FieldTooLarge { max_part_size_kb } => write!(
                formatter,
                "Field exceeded maximum size of {max_part_size_kb}KB."
            ),
        }
    }
}

impl Error for FormDataParseError {}
