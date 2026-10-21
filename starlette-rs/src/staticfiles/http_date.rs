//! HTTP validator date parsing and 304 response-header selection.

use std::time::SystemTime;

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
        _ => parse_email_date_fields(&if_modified_since)
            .zip(parse_email_date_fields(&last_modified))
            .is_some_and(|(request_date, modified_date)| request_date >= modified_date),
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
    let normalized_comments = strip_email_comments_after_time(value);
    let value = normalized_comments.as_deref().unwrap_or(value);
    let normalized_timezone = normalize_email_timezone(value);
    let value = normalized_timezone.as_deref().unwrap_or(value);
    let normalized_month = normalize_email_month(value);
    let value = normalized_month.as_deref().unwrap_or(value);
    let normalized_day = normalize_email_day(value);
    let value = normalized_day.as_deref().unwrap_or(value);
    let normalized_time = normalize_email_time(value);
    let value = normalized_time.as_deref().unwrap_or(value);
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

// The pinned `email.utils.parsedate` returns its date tuple without validating
// calendar or clock ranges, so retain that comparison when `httpdate` rejects
// an otherwise parseable field sequence.
fn parse_email_date_fields(value: &str) -> Option<(i64, i64, i64, i64, i64, i64)> {
    let value = strip_trailing_email_comments(value.trim());
    let normalized_comments = strip_email_comments_after_time(value);
    let mut normalized = normalized_comments.as_deref().unwrap_or(value).to_owned();

    if let Some(timezone) = normalize_email_timezone(&normalized) {
        normalized = timezone;
    }
    if let Some(month) = normalize_email_month(&normalized) {
        normalized = month;
    }
    if let Some(day) = normalize_email_day(&normalized) {
        normalized = day;
    }
    if let Some(time) = normalize_email_time(&normalized) {
        normalized = time;
    }

    let date = normalized
        .split_once(',')
        .map_or(normalized.as_str(), |(_, date)| date)
        .trim();
    let date = if date.split_whitespace().next().is_some_and(is_email_weekday) {
        date.split_once(char::is_whitespace)?.1.trim_start()
    } else {
        date
    };
    let mut fields = date.split_whitespace();
    let first = fields.next()?;
    let second = fields.next()?;
    let third = fields.next()?;
    let fourth = fields.next();

    let (year, month, day, time) = if let Some(month) = email_month_number(first) {
        // The asctime form writes month, day, time, year.
        (fourth?, month, second, third)
    } else if first.contains('-') {
        // The RFC 850 form writes day-month-year as one field.
        // CPython expands it only when exactly three fields follow the weekday.
        if fourth.is_some() {
            return None;
        }
        let mut date_fields = first.split('-');
        let day = date_fields.next()?;
        let month_name = date_fields.next()?;
        let year = date_fields.next()?;
        if date_fields.next().is_some() {
            return None;
        }
        (year, email_month_number(month_name)?, day, second)
    } else {
        // The RFC 822/1123 form writes day, month, year, time.
        (third, email_month_number(second)?, first, fourth?)
    };

    let year = year.parse::<i64>().ok()?;
    let year = match year {
        0..=68 => year.checked_add(2000)?,
        69..=99 => year.checked_add(1900)?,
        _ => year,
    };
    let day = day.parse::<i64>().ok()?;
    let mut time_fields = time.split(':');
    let hour = time_fields.next()?.parse::<i64>().ok()?;
    let minute = time_fields.next()?.parse::<i64>().ok()?;
    let second = time_fields.next().unwrap_or("0").parse::<i64>().ok()?;
    if time_fields.next().is_some() {
        return None;
    }

    Some((year, month, day, hour, minute, second))
}

fn email_month_number(value: &str) -> Option<i64> {
    const MONTHS: [(&str, i64); 12] = [
        ("January", 1),
        ("February", 2),
        ("March", 3),
        ("April", 4),
        ("May", 5),
        ("June", 6),
        ("July", 7),
        ("August", 8),
        ("September", 9),
        ("October", 10),
        ("November", 11),
        ("December", 12),
    ];

    MONTHS.iter().find_map(|(full, number)| {
        (value.eq_ignore_ascii_case(full) || value.eq_ignore_ascii_case(&full[..3]))
            .then_some(*number)
    })
}

fn is_email_weekday(value: &str) -> bool {
    [
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
        "Sun",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    .iter()
    .any(|weekday| value.eq_ignore_ascii_case(weekday))
}

/// Removes balanced RFC comments after the time token, where `email.utils.parsedate`
/// treats the next token as an ignored timezone field.
fn strip_email_comments_after_time(value: &str) -> Option<String> {
    let mut cursor: usize = 0;
    for field in value.split_whitespace() {
        let start = cursor.checked_add(value.get(cursor..)?.find(field)?)?;
        let end = start.checked_add(field.len())?;
        cursor = end;
        if !is_email_time_field(field) {
            continue;
        }

        let suffix = &value[end..];
        let stripped_suffix = remove_email_comments(suffix)?;
        if stripped_suffix == suffix {
            return None;
        }
        return Some(
            format!("{}{}", &value[..end], stripped_suffix)
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" "),
        );
    }
    None
}

fn is_email_time_field(value: &str) -> bool {
    let fields = value.split(':').collect::<Vec<_>>();
    matches!(fields.len(), 2 | 3)
        && fields
            .iter()
            .all(|field| !field.is_empty() && field.bytes().all(|byte| byte.is_ascii_digit()))
}

fn remove_email_comments(value: &str) -> Option<String> {
    let mut result = String::with_capacity(value.len());
    let mut depth = 0_usize;
    let mut escaped = false;
    let mut removed = false;

    for character in value.chars() {
        if depth > 0 {
            if escaped {
                escaped = false;
            } else if character == '\\' {
                escaped = true;
            } else if character == '(' {
                depth = depth.checked_add(1)?;
            } else if character == ')' {
                depth = depth.checked_sub(1)?;
            }
        } else if character == '(' {
            depth = 1;
            removed = true;
        } else {
            result.push(character);
        }
    }

    (depth == 0 && removed).then_some(result)
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

/// Pads the single-digit day fields accepted by `email.utils.parsedate` to the
/// fixed-width form required by `httpdate`.
fn normalize_email_day(value: &str) -> Option<String> {
    let (prefix, rest) = value
        .split_once(',')
        .map_or((None, value), |(prefix, rest)| (Some(prefix), rest));
    let whitespace_len = rest.len().checked_sub(rest.trim_start().len())?;
    let date_and_suffix = &rest[whitespace_len..];
    let token_len = date_and_suffix
        .find(char::is_whitespace)
        .unwrap_or(date_and_suffix.len());
    let date_token = &date_and_suffix[..token_len];
    let day_end = date_token.find('-').unwrap_or(date_token.len());
    let day = &date_token[..day_end];
    if day.len() != 1 || !day.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }

    let normalized_token = format!("0{day}{}", &date_token[day_end..]);
    let normalized_rest = format!(
        "{}{}{}",
        &rest[..whitespace_len],
        normalized_token,
        &date_and_suffix[token_len..]
    );
    Some(match prefix {
        Some(prefix) => format!("{prefix},{normalized_rest}"),
        None => normalized_rest,
    })
}

/// Pads single-digit time fields accepted by `email.utils.parsedate` to the
/// fixed-width form required by `httpdate`.
fn normalize_email_time(value: &str) -> Option<String> {
    let mut cursor: usize = 0;
    for field in value.split_whitespace() {
        let start = cursor.checked_add(value.get(cursor..)?.find(field)?)?;
        let end = start.checked_add(field.len())?;
        cursor = end;

        let parts = field.split(':').collect::<Vec<_>>();
        if !(2..=3).contains(&parts.len())
            || !parts.iter().all(|part| {
                !part.is_empty()
                    && part.len() <= 2
                    && part.bytes().all(|byte| byte.is_ascii_digit())
            })
        {
            continue;
        }

        let capacity = field.len().checked_add(3)?;
        let mut normalized = String::with_capacity(capacity);
        for (index, part) in parts.iter().enumerate() {
            if index > 0 {
                normalized.push(':');
            }
            if part.len() == 1 {
                normalized.push('0');
            }
            normalized.push_str(part);
        }
        if parts.len() == 2 {
            normalized.push_str(":00");
        }
        if normalized == field {
            return None;
        }
        return Some(format!(
            "{}{}{}",
            &value[..start],
            normalized,
            &value[end..]
        ));
    }
    None
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
                    let Some(next_depth) = depth.checked_add(1) else {
                        return value;
                    };
                    depth = next_depth;
                }
                b')' if depth > 0 => {
                    let Some(next_depth) = depth.checked_sub(1) else {
                        return value;
                    };
                    depth = next_depth;
                    if depth == 0 && index.checked_add(1) == Some(value.len()) {
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
