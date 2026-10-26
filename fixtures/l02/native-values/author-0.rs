// Proposal author input only; not a generated binding or released SDK.
#[derive(Clone, Debug, PartialEq)]
pub struct Reading {
    pub value: i32,
    pub label: String,
}

pub fn normalize(mut value: Reading) -> Reading {
    value.label = value.label.trim().to_owned();
    value
}
