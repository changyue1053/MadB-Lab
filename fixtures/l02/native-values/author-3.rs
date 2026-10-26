// Proposal author input only; not a generated binding or released SDK.
#[derive(Clone, Debug, PartialEq)]
pub struct Reading {
    pub value: i32,
    pub label: String,
    pub quality: u32,
}

#[repr(i32)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReadingError {
    Overflow = 1,
}

pub fn canonicalize(mut value: Reading) -> Reading {
    value.label = value.label.trim().to_owned();
    value
}

pub fn offset(mut value: Reading, delta: i32) -> Result<Reading, ReadingError> {
    value.value = value.value.checked_add(delta).ok_or(ReadingError::Overflow)?;
    Ok(value)
}
