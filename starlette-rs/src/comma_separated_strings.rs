//! Rust-owned parsing and display for Starlette's comma-separated strings.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

use unicode_general_category::{GeneralCategory, get_general_category};

/// A comma-separated string whose items use POSIX shell quoting rules.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CommaSeparatedStrings {
    items: Vec<String>,
}

/// A malformed quoted or escaped comma-separated string.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CommaSeparatedStringsParseError {
    /// A single- or double-quoted item did not close.
    NoClosingQuotation,
    /// An escape character appeared at the end of the input.
    NoEscapedCharacter,
}

impl Display for CommaSeparatedStringsParseError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoClosingQuotation => formatter.write_str("No closing quotation"),
            Self::NoEscapedCharacter => formatter.write_str("No escaped character"),
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
        let characters = value.chars().collect::<Vec<_>>();
        let mut items = Vec::new();
        let mut item = String::new();
        let mut item_started = false;
        let mut state = LexerState::Word;
        let mut index = 0;

        while index < characters.len() {
            let character = characters[index];
            index += 1;

            match state {
                LexerState::Word => match character {
                    ',' => push_item(&mut items, &mut item, &mut item_started),
                    '#' => {
                        push_item(&mut items, &mut item, &mut item_started);
                        while index < characters.len() && characters[index] != '\n' {
                            index += 1;
                        }
                        if index < characters.len() {
                            index += 1;
                        }
                    }
                    '\'' => {
                        item_started = true;
                        state = LexerState::SingleQuoted;
                    }
                    '"' => {
                        item_started = true;
                        state = LexerState::DoubleQuoted;
                    }
                    '\\' => {
                        item_started = true;
                        state = LexerState::Escaped;
                    }
                    _ => {
                        item.push(character);
                        item_started = true;
                    }
                },
                LexerState::SingleQuoted => {
                    if character == '\'' {
                        state = LexerState::Word;
                    } else {
                        item.push(character);
                    }
                }
                LexerState::DoubleQuoted => match character {
                    '"' => state = LexerState::Word,
                    '\\' => state = LexerState::EscapedDoubleQuoted,
                    _ => item.push(character),
                },
                LexerState::Escaped => {
                    item.push(character);
                    state = LexerState::Word;
                }
                LexerState::EscapedDoubleQuoted => {
                    if character != '"' && character != '\\' {
                        item.push('\\');
                    }
                    item.push(character);
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
        let reprs = self
            .items
            .iter()
            .map(|item| python_string_repr(item))
            .collect::<Vec<_>>();
        self.as_string_with_item_reprs(&reprs)
    }

    /// Joins item representations supplied by a foreign-language boundary.
    ///
    /// Python string subclasses may override `__repr__`; the Python binding
    /// computes those representations while Rust retains the join semantics.
    #[must_use]
    pub fn as_string_with_item_reprs(&self, item_reprs: &[String]) -> String {
        item_reprs.join(", ")
    }

    /// Returns Starlette's class representation using the supplied class name.
    #[must_use]
    pub fn repr(&self, class_name: &str) -> String {
        let reprs = self
            .items
            .iter()
            .map(|item| python_string_repr(item))
            .collect::<Vec<_>>();
        self.repr_with_item_reprs(class_name, &reprs)
    }

    /// Formats the class representation from item representations supplied by
    /// a foreign-language boundary.
    #[must_use]
    pub fn repr_with_item_reprs(&self, class_name: &str, item_reprs: &[String]) -> String {
        format!("{class_name}([{}])", item_reprs.join(", "))
    }
}

fn push_item(items: &mut Vec<String>, item: &mut String, item_started: &mut bool) {
    if *item_started {
        items.push(trim_python_whitespace(item).to_owned());
        item.clear();
        *item_started = false;
    }
}

fn trim_python_whitespace(value: &str) -> &str {
    value.trim_matches(|character: char| {
        matches!(
            get_general_category(character),
            GeneralCategory::SpaceSeparator
                | GeneralCategory::LineSeparator
                | GeneralCategory::ParagraphSeparator
        ) || matches!(u32::from(character), 0x0009..=0x000d | 0x001c..=0x0020 | 0x0085)
    })
}

fn python_string_repr(value: &str) -> String {
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut result = String::with_capacity(value.len() + 2);
    result.push(quote);

    for character in value.chars() {
        if character == quote || character == '\\' {
            result.push('\\');
            result.push(character);
        } else {
            match character {
                '\t' => result.push_str("\\t"),
                '\n' => result.push_str("\\n"),
                '\r' => result.push_str("\\r"),
                _ if is_non_printing(character) => {
                    let codepoint = u32::from(character);
                    if codepoint <= 0xff {
                        result.push_str(&format!("\\x{codepoint:02x}"));
                    } else if codepoint <= 0xffff {
                        result.push_str(&format!("\\u{codepoint:04x}"));
                    } else {
                        result.push_str(&format!("\\U{codepoint:08x}"));
                    }
                }
                _ => result.push(character),
            }
        }
    }

    result.push(quote);
    result
}

fn is_non_printing(character: char) -> bool {
    let category = get_general_category(character);
    matches!(
        category,
        GeneralCategory::Control
            | GeneralCategory::Format
            | GeneralCategory::LineSeparator
            | GeneralCategory::ParagraphSeparator
            | GeneralCategory::PrivateUse
            | GeneralCategory::Surrogate
            | GeneralCategory::Unassigned
    ) || (category == GeneralCategory::SpaceSeparator && character != ' ')
}
