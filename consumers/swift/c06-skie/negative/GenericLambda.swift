import MadBSkieGaps

// Box<() -> Unit> cannot be represented by this SKIE/ObjC enhancement profile.
// A passing framework build does not make this promised API callable.
func invalid() {
    _ = UnsafeSurface.only.lambdaBox()
}
