//! Python-compatible formatting for floating-point values shared by APIs.

pub(crate) fn python_float_string(value: f64) -> String {
    if value.is_nan() {
        return String::from("nan");
    }
    if value.is_infinite() {
        return if value.is_sign_negative() {
            String::from("-inf")
        } else {
            String::from("inf")
        };
    }
    if value == 0.0 {
        return if value.is_sign_negative() {
            String::from("-0.0")
        } else {
            String::from("0.0")
        };
    }

    let rendered = value.to_string();
    let (sign, rendered) = rendered
        .strip_prefix('-')
        .map_or(("", rendered.as_str()), |magnitude| ("-", magnitude));
    let (mantissa, explicit_exponent) = rendered
        .split_once(['e', 'E'])
        .map_or((rendered, 0), |(mantissa, exponent)| {
            (mantissa, exponent.parse::<i32>().unwrap_or(0))
        });
    let decimal_position = mantissa.find('.').unwrap_or(mantissa.len());
    let mut digits = mantissa
        .bytes()
        .filter(|byte| *byte != b'.')
        .map(char::from)
        .collect::<String>();
    let leading_zeroes = digits.bytes().take_while(|digit| *digit == b'0').count();
    if leading_zeroes == digits.len() {
        return format!("{sign}0.0");
    }
    digits.drain(..leading_zeroes);
    // Rust's shortest finite-f64 representation keeps these decimal positions
    // and digit counts far inside the i32 range.
    let decimal_position = i32::try_from(decimal_position)
        .unwrap_or(i32::MAX)
        .checked_add(explicit_exponent)
        .and_then(|position| {
            position.checked_sub(i32::try_from(leading_zeroes).unwrap_or(i32::MAX))
        })
        .unwrap_or(0);
    while digits.len() > 1 && digits.ends_with('0') {
        digits.pop();
    }

    let exponent = decimal_position.saturating_sub(1);
    if !(-4..16).contains(&exponent) {
        let fraction = &digits[1..];
        let significand = if fraction.is_empty() {
            String::from(&digits[..1])
        } else {
            format!("{}.{}", &digits[..1], fraction)
        };
        format!("{sign}{significand}e{exponent:+03}")
    } else if decimal_position <= 0 {
        let zeroes = usize::try_from(decimal_position.unsigned_abs()).unwrap_or(usize::MAX);
        format!("{sign}0.{}{digits}", "0".repeat(zeroes))
    } else {
        let decimal_position = usize::try_from(decimal_position).unwrap_or(usize::MAX);
        if decimal_position >= digits.len() {
            let padding_length = decimal_position.saturating_sub(digits.len());
            format!(
                "{sign}{}{padding}.0",
                digits,
                padding = "0".repeat(padding_length)
            )
        } else {
            format!(
                "{sign}{}.{}",
                &digits[..decimal_position],
                &digits[decimal_position..]
            )
        }
    }
}
