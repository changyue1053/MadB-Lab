// Independent auxiliary author: a selected unwind configuration, not abort safety.
pub struct Reading {
    pub value: i32,
    pub label: String,
}
pub fn explode(value: Reading) -> Reading {
    let _owned_input = value;
    panic!("controlled independent Lab unwind");
}
