//! Rust-owned parsing and display for Starlette's comma-separated strings.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

use unicode_general_category::{GeneralCategory, get_general_category};

/// A comma-separated string whose items use POSIX shell quoting rules.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CommaSeparatedStrings {
    items: Vec<String>,
}

/// A Python string sequence represented as Unicode code points.
///
/// This bridge representation includes Python's lone-surrogate code points,
/// which cannot be stored in Rust's UTF-8 `String`. It keeps parsing and
/// formatting decisions in Rust while allowing the PyO3 boundary to convert
/// values to and from Python strings losslessly.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PythonCodePointStrings {
    items: Vec<Vec<u32>>,
}

/// A malformed quoted, escaped, or code-point string.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CommaSeparatedStringsParseError {
    /// A single- or double-quoted item did not close.
    NoClosingQuotation,
    /// An escape character appeared at the end of the input.
    NoEscapedCharacter,
    /// A value greater than the Unicode maximum code point was supplied.
    InvalidCodePoint,
}

impl Display for CommaSeparatedStringsParseError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoClosingQuotation => formatter.write_str("No closing quotation"),
            Self::NoEscapedCharacter => formatter.write_str("No escaped character"),
            Self::InvalidCodePoint => formatter.write_str("Invalid Unicode code point"),
        }
    }
}

impl Error for CommaSeparatedStringsParseError {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum LexerState {
    Word,
    SingleQuoted,
    DoubleQuoted,
    Escaped,
    EscapedDoubleQuoted,
}

impl CommaSeparatedStrings {
    /// Parses a string with commas as separators and POSIX shell quoting.
    ///
    /// As in Starlette, each token is stripped after shell-style quote and
    /// escape processing. Empty unquoted fields are skipped; an explicitly
    /// quoted empty field is retained.
    pub fn parse(value: &str) -> Result<Self, CommaSeparatedStringsParseError> {
        let codepoints = value.chars().map(u32::from).collect::<Vec<_>>();
        let parsed = PythonCodePointStrings::parse(&codepoints)?;
        let items = parsed
            .items()
            .iter()
            .map(|item| codepoints_to_string(item))
            .collect();
        Ok(Self { items })
    }

    /// Creates a value from an existing sequence without trimming its items.
    #[must_use]
    pub fn from_items(items: impl IntoIterator<Item = String>) -> Self {
        Self {
            items: items.into_iter().collect(),
        }
    }

    /// Returns the parsed strings in their original sequence order.
    #[must_use]
    pub fn items(&self) -> &[String] {
        &self.items
    }

    /// Returns the item at `index`, with Python-style negative indexing.
    #[must_use]
    pub fn get(&self, index: isize) -> Option<&str> {
        let length = isize::try_from(self.items.len()).ok()?;
        let resolved = if index < 0 {
            length.checked_add(index)?
        } else {
            index
        };
        usize::try_from(resolved)
            .ok()
            .and_then(|resolved| self.items.get(resolved))
            .map(String::as_str)
    }

    /// Returns the number of items.
    #[must_use]
    pub fn len(&self) -> usize {
        self.items.len()
    }

    /// Returns whether this value has no items.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// Returns Starlette's comma-separated display form.
    #[must_use]
    pub fn as_string(&self) -> String {
        let items = self
            .items
            .iter()
            .map(|item| item.chars().map(u32::from).collect::<Vec<_>>())
            .collect::<Vec<_>>();
        codepoints_to_string(&PythonCodePointStrings { items }.as_string())
    }

    /// Joins item representations supplied by a foreign-language boundary.
    ///
    /// Python string subclasses may override `__repr__`; the Python binding
    /// computes those representations while Rust retains the join semantics.
    #[must_use]
    pub fn as_string_with_item_reprs(&self, item_reprs: &[String]) -> String {
        let codepoint_reprs = item_reprs
            .iter()
            .map(|item| item.chars().map(u32::from).collect::<Vec<_>>())
            .collect::<Vec<_>>();
        codepoints_to_string(&PythonCodePointStrings::join_item_reprs(&codepoint_reprs))
    }

    /// Returns Starlette's class representation using the supplied class name.
    #[must_use]
    pub fn repr(&self, class_name: &str) -> String {
        let items = self
            .items
            .iter()
            .map(|item| item.chars().map(u32::from).collect::<Vec<_>>())
            .collect::<Vec<_>>();
        codepoints_to_string(&PythonCodePointStrings { items }.repr(class_name))
    }

    /// Formats the class representation from item representations supplied by
    /// a foreign-language boundary.
    #[must_use]
    pub fn repr_with_item_reprs(&self, class_name: &str, item_reprs: &[String]) -> String {
        let codepoint_reprs = item_reprs
            .iter()
            .map(|item| item.chars().map(u32::from).collect::<Vec<_>>())
            .collect::<Vec<_>>();
        codepoints_to_string(&PythonCodePointStrings::repr_with_item_reprs(
            class_name,
            &codepoint_reprs,
        ))
    }
}

impl PythonCodePointStrings {
    /// Parses Python Unicode code points with POSIX shell quoting and comma
    /// separators. Values in the surrogate range are preserved.
    pub fn parse(value: &[u32]) -> Result<Self, CommaSeparatedStringsParseError> {
        if value.iter().any(|codepoint| *codepoint > 0x10ffff) {
            return Err(CommaSeparatedStringsParseError::InvalidCodePoint);
        }

        let mut items = Vec::new();
        let mut item = Vec::new();
        let mut item_started = false;
        let mut state = LexerState::Word;
        let mut index = 0;

        while index < value.len() {
            let codepoint = value[index];
            index += 1;

            match state {
                LexerState::Word => match codepoint {
                    0x2c => push_item(&mut items, &mut item, &mut item_started),
                    0x23 => {
                        push_item(&mut items, &mut item, &mut item_started);
                        while index < value.len() && value[index] != 0x0a {
                            index += 1;
                        }
                        if index < value.len() {
                            index += 1;
                        }
                    }
                    0x27 => {
                        item_started = true;
                        state = LexerState::SingleQuoted;
                    }
                    0x22 => {
                        item_started = true;
                        state = LexerState::DoubleQuoted;
                    }
                    0x5c => {
                        item_started = true;
                        state = LexerState::Escaped;
                    }
                    _ => {
                        item.push(codepoint);
                        item_started = true;
                    }
                },
                LexerState::SingleQuoted => {
                    if codepoint == 0x27 {
                        state = LexerState::Word;
                    } else {
                        item.push(codepoint);
                    }
                }
                LexerState::DoubleQuoted => match codepoint {
                    0x22 => state = LexerState::Word,
                    0x5c => state = LexerState::EscapedDoubleQuoted,
                    _ => item.push(codepoint),
                },
                LexerState::Escaped => {
                    item.push(codepoint);
                    state = LexerState::Word;
                }
                LexerState::EscapedDoubleQuoted => {
                    if codepoint != 0x22 && codepoint != 0x5c {
                        item.push(0x5c);
                    }
                    item.push(codepoint);
                    state = LexerState::DoubleQuoted;
                }
            }
        }

        match state {
            LexerState::SingleQuoted | LexerState::DoubleQuoted => {
                return Err(CommaSeparatedStringsParseError::NoClosingQuotation);
            }
            LexerState::Escaped | LexerState::EscapedDoubleQuoted => {
                return Err(CommaSeparatedStringsParseError::NoEscapedCharacter);
            }
            LexerState::Word => push_item(&mut items, &mut item, &mut item_started),
        }

        Ok(Self { items })
    }

    /// Creates a value from existing Unicode code-point sequences without
    /// trimming their items. Surrogates are accepted as Python string values.
    pub fn from_items(
        items: impl IntoIterator<Item = Vec<u32>>,
    ) -> Result<Self, CommaSeparatedStringsParseError> {
        let items = items.into_iter().collect::<Vec<_>>();
        if items
            .iter()
            .flatten()
            .any(|codepoint| *codepoint > 0x10ffff)
        {
            return Err(CommaSeparatedStringsParseError::InvalidCodePoint);
        }
        Ok(Self { items })
    }

    /// Returns the code-point sequences in their original order.
    #[must_use]
    pub fn items(&self) -> &[Vec<u32>] {
        &self.items
    }

    /// Returns the number of items.
    #[must_use]
    pub fn len(&self) -> usize {
        self.items.len()
    }

    /// Returns whether this value has no items.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// Returns Starlette's comma-separated display form as Python code points.
    #[must_use]
    pub fn as_string(&self) -> Vec<u32> {
        let reprs = self
            .items
            .iter()
            .map(|item| python_string_repr(item))
            .collect::<Vec<_>>();
        Self::join_item_reprs(&reprs)
    }

    /// Joins item representations, preserving all code points from Python
    /// `str` subclasses.
    #[must_use]
    pub fn as_string_with_item_reprs(&self, item_reprs: &[Vec<u32>]) -> Vec<u32> {
        Self::join_item_reprs(item_reprs)
    }

    /// Returns the class representation using the supplied class name.
    pub fn repr(&self, class_name: &str) -> Vec<u32> {
        let reprs = self
            .items
            .iter()
            .map(|item| python_string_repr(item))
            .collect::<Vec<_>>();
        Self::repr_with_item_reprs(class_name, &reprs)
    }

    /// Formats the class representation from item representations supplied by
    /// a foreign-language boundary.
    #[must_use]
    pub fn repr_with_item_reprs(class_name: &str, item_reprs: &[Vec<u32>]) -> Vec<u32> {
        let mut result = class_name.chars().map(u32::from).collect::<Vec<_>>();
        result.extend([0x28, 0x5b]);
        result.extend(Self::join_item_reprs(item_reprs));
        result.extend([0x5d, 0x29]);
        result
    }

    /// Joins a list of Python `repr` results with Starlette's delimiter.
    #[must_use]
    pub fn join_item_reprs(item_reprs: &[Vec<u32>]) -> Vec<u32> {
        let mut result = Vec::new();
        for (index, item_repr) in item_reprs.iter().enumerate() {
            if index > 0 {
                result.extend([0x2c, 0x20]);
            }
            result.extend(item_repr);
        }
        result
    }
}

fn push_item(items: &mut Vec<Vec<u32>>, item: &mut Vec<u32>, item_started: &mut bool) {
    if *item_started {
        items.push(trim_python_whitespace(item).to_vec());
        item.clear();
        *item_started = false;
    }
}

fn trim_python_whitespace(value: &[u32]) -> &[u32] {
    let is_whitespace = |codepoint: u32| {
        matches!(codepoint, 0x0009..=0x000d | 0x001c..=0x0020 | 0x0085)
            || char::from_u32(codepoint).is_some_and(|character| {
                matches!(
                    get_general_category(character),
                    GeneralCategory::SpaceSeparator
                        | GeneralCategory::LineSeparator
                        | GeneralCategory::ParagraphSeparator
                )
            })
    };
    let start = value
        .iter()
        .position(|codepoint| !is_whitespace(*codepoint))
        .unwrap_or(value.len());
    let end = value
        .iter()
        .rposition(|codepoint| !is_whitespace(*codepoint))
        .map_or(start, |index| index + 1);
    &value[start..end]
}

fn python_string_repr(value: &[u32]) -> Vec<u32> {
    let single_quote = 0x27;
    let double_quote = 0x22;
    let quote = if value.contains(&single_quote) && !value.contains(&double_quote) {
        double_quote
    } else {
        single_quote
    };
    let mut result = vec![quote];

    for codepoint in value {
        if *codepoint == quote || *codepoint == 0x5c {
            result.push(0x5c);
            result.push(*codepoint);
        } else {
            match *codepoint {
                0x09 => result.extend("\\t".chars().map(u32::from)),
                0x0a => result.extend("\\n".chars().map(u32::from)),
                0x0d => result.extend("\\r".chars().map(u32::from)),
                _ if is_non_printing(*codepoint) => {
                    let escaped = if *codepoint <= 0xff {
                        format!("\\x{codepoint:02x}")
                    } else if *codepoint <= 0xffff {
                        format!("\\u{codepoint:04x}")
                    } else {
                        format!("\\U{codepoint:08x}")
                    };
                    result.extend(escaped.chars().map(u32::from));
                }
                _ => result.push(*codepoint),
            }
        }
    }

    result.push(quote);
    result
}

fn is_non_printing(codepoint: u32) -> bool {
    char::from_u32(codepoint).is_none_or(|character| {
        matches!(
            get_general_category(character),
            GeneralCategory::Control
                | GeneralCategory::Format
                | GeneralCategory::LineSeparator
                | GeneralCategory::ParagraphSeparator
                | GeneralCategory::PrivateUse
                | GeneralCategory::Unassigned
        ) || (get_general_category(character) == GeneralCategory::SpaceSeparator
            && character != ' ')
    })
}

fn codepoints_to_string(value: &[u32]) -> String {
    let mut result = String::new();
    for codepoint in value {
        if let Some(character) = char::from_u32(*codepoint) {
            result.push(character);
        } else if *codepoint <= 0xffff {
            result.push_str(&format!("\\u{codepoint:04x}"));
        } else {
            result.push_str(&format!("\\U{codepoint:08x}"));
        }
    }
    result
}
