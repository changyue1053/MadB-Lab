import MadBSkieGaps

// The fixture exports a real custom cinterop type without its Swift framework
// origin. Calling the enhanced API must be rejected at the declaration.
func invalid(token: __SkieUnknownCInteropFrameworkErrorType) {
    _ = UnsafeSurface.only.acceptCustom(token: token)
}
