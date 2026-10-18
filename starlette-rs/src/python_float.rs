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
    let decimal_position = i32::try_from(decimal_position).unwrap_or(i32::MAX) + explicit_exponent
        - i32::try_from(leading_zeroes).unwrap_or(i32::MAX);
    while digits.len() > 1 && digits.ends_with('0') {
        digits.pop();
    }

    let exponent = decimal_position - 1;
    if !(-4..16).contains(&exponent) {
        let fraction = &digits[1..];
        let significand = if fraction.is_empty() {
            String::from(&digits[..1])
        } else {
            format!("{}.{}", &digits[..1], fraction)
        };
        format!("{sign}{significand}e{exponent:+03}")
    } else if decimal_position <= 0 {
        let zeroes = usize::try_from(-decimal_position).unwrap_or(usize::MAX);
        format!("{sign}0.{}{digits}", "0".repeat(zeroes))
    } else {
        let decimal_position = usize::try_from(decimal_position).unwrap_or(usize::MAX);
        if decimal_position >= digits.len() {
            format!(
                "{sign}{}{padding}.0",
                digits,
                padding = "0".repeat(decimal_position - digits.len())
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
