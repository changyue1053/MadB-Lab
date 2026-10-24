"""Lab-owned C06 route/case scope, independent from producer implementation code."""
from __future__ import annotations

COMMON_CASES = (
    "data", "errors", "objects", "async", "cancel", "late-callback", "capacity",
    "shutdown", "identity", "wrong-profile", "wrong-abi", "distribution",
)
ROUTES = {
    "kotlin-jvm-rust": {"route": "KJVM-RUST-UNIFFI", "provider": "rust", "consumer": "kotlin", "extra": ()},
    "kotlin-native-rust": {"route": "KN-RUST-GOBLEY", "provider": "rust", "consumer": "kotlin",
                           "extra": ("foreign-future-once", "callback-throw", "cancel-late-result")},
    "swift-rust": {"route": "SWIFT-RUST-UNIFFI", "provider": "rust", "consumer": "swift", "extra": ()},
    "swift-kotlin": {"route": "KN-SWIFT-OBJC", "provider": "kotlin", "consumer": "swift",
                     "extra": ("enhanced-api", "missing-cinterop-origin", "generic-lambda")},
}
TARGET = "aarch64-apple-darwin"


def case_names(group: str) -> tuple[str, ...]:
    return COMMON_CASES + ROUTES[group]["extra"]


def required_cases(group: str) -> set[str]:
    return {f"c06.{group}.{name}" for name in case_names(group)}
