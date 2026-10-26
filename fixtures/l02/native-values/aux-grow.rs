// Independent auxiliary author: output conversion boundary, not the trim business.
pub struct Reading {
    pub value: i32,
    pub label: String,
}
pub fn grow(mut value: Reading) -> Reading {
    value.label = "x".repeat(65);
    value
}
