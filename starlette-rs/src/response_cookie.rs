pub(crate) fn is_cookie_token(value: &str) -> bool {
    !value.is_empty()
        && value.chars().all(|character| {
            character.is_ascii_alphanumeric()
                || matches!(
                    character,
                    '_' | '!'
                        | '#'
                        | '$'
                        | '%'
                        | '&'
                        | '\''
                        | '*'
                        | '+'
                        | '-'
                        | '.'
                        | '^'
                        | '`'
                        | '|'
                        | '~'
                        | ':'
                )
        })
}

pub(crate) fn is_cookie_name(value: &str) -> bool {
    // Match Morsel's reserved attribute names across supported Python versions.
    const RESERVED_ATTRIBUTES: &[&str] = &[
        "comment", "domain", "expires", "httponly", "max-age", "path", "samesite", "secure",
        "version",
    ];

    is_cookie_token(value)
        && !RESERVED_ATTRIBUTES
            .iter()
            .any(|reserved| value.eq_ignore_ascii_case(reserved))
}
