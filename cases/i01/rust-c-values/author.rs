pub struct Reading { pub value: i32, pub label: String }
pub fn normalize(mut value: Reading) -> Reading {
    value.label = value.label.trim().to_owned(); value
}
