"""Independent C07 Kn stream oracle. No producer modules, no C frame offsets.

validate(scenario, numbers, controls) checks raw observations from the public HAR.
The caller must reject duplicate labels, report consumer exceptions/timeouts, and
separately require Runtime.close plus its independently defined 110 physical ACK.
This module never equates normal Runtime.close with VM/env teardown.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCENARIOS = (
    "kotlin-state", "kotlin-state-staging-bytes", "kotlin-event-fifo-and-atomic",
    "kotlin-source-stop", "kotlin-fanout-allocation",
)
IDENTITIES = frozenset((4, 5, 8))
SAFE_MAX = (1 << 53) - 1
U64_MAX = (1 << 64) - 1
DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)\Z")


class OracleFailure(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise OracleFailure(reason)


def parse_control(csv: str) -> tuple[str, ...]:
    require(type(csv) is str, "control must be raw CSV, never a numeric array")
    tokens = tuple(csv.split(','))
    require(len(tokens) == 31 and tokens[0] == '1', "controls format must be 1/31")
    for index, token in enumerate(tokens):
        if index == 6 and token == '-1':
            continue
        require(DECIMAL.fullmatch(token) is not None, f"control[{index}] noncanonical decimal")
        # Compare magnitude textually: identity fields never convert to a numeric value.
        bound = str(U64_MAX)
        require(len(token) < len(bound) or (len(token) == len(bound) and token <= bound),
                f"control[{index}] exceeds uint64")
    require(tokens[3] in ('0', '1', '2'), "unknown work hold phase")
    require(tokens[6] in ('-1', '0', '5', '8', '10'), "unknown work terminal")
    require(tokens[7] in ('0', '1', '2', '3'), "unknown delivery state")
    require(tokens[12] in ('0', '1', '2', '3'), "unknown publication state")
    require(tokens[24] in ('0', '1', '2', '3'), "unknown transfer phase")
    return tokens


def counter(tokens: tuple[str, ...], index: int) -> int:
    require(index not in IDENTITIES, "identity tokens must stay strings")
    return int(tokens[index])


class Observations:
    def __init__(self, numbers: dict[str, list[int]], controls: dict[str, str]):
        require(type(numbers) is dict and type(controls) is dict, "observation maps required")
        self.numbers = numbers
        self.controls = controls
        self.used_numbers: set[str] = set()
        self.used_controls: set[str] = set()

    def vector(self, label: str, expected: list[int]) -> None:
        require(label in self.numbers, f"missing {label}")
        self.used_numbers.add(label)
        actual = self.numbers[label]
        require(type(actual) is list and all(type(n) is int for n in actual), f"{label}: integer vector required")
        require(actual == expected, f"{label}: expected {expected}, got {actual}")

    def native(self, label: str, expected: dict[int, int] | None = None) -> list[int]:
        require(label in self.numbers, f"missing {label}")
        self.used_numbers.add(label)
        raw = self.numbers[label]
        require(type(raw) is list and len(raw) == 110, f"{label}: native width 110")
        require(all(type(n) is int and 0 <= n <= SAFE_MAX for n in raw), f"{label}: unsafe/noninteger native counter")
        require(raw[0] == 70501 and raw[8] == 0, f"{label}: native format/owner faults")
        for index, value in (expected or {}).items():
            require(raw[index] == value, f"{label}[{index}]: expected {value}, got {raw[index]}")
        return raw

    def control(self, label: str, expected: dict[int, str] | None = None) -> tuple[str, ...]:
        require(label in self.controls, f"missing {label}")
        self.used_controls.add(label)
        tokens = parse_control(self.controls[label])
        for index, value in (expected or {}).items():
            require(tokens[index] == value, f"{label}[{index}]: expected {value}, got {tokens[index]}")
        return tokens

    def finish(self) -> None:
        require(self.used_numbers == {k for k in self.numbers if k.startswith('kn-stream-')}, "unexpected stream numeric label")
        require(self.used_controls == {k for k in self.controls if k.startswith('kn-stream-')}, "unexpected stream control label")


def same(a: list[int], b: list[int], indices: tuple[int, ...], label: str) -> None:
    for i in indices:
        require(a[i] == b[i], f"{label}: field {i} changed")


def delta(a: tuple[str, ...], b: tuple[str, ...], expected: dict[int, int], label: str) -> None:
    for i, value in expected.items():
        require(counter(b, i) - counter(a, i) == value, f"{label}: wrong field {i} delta")


def state(o: Observations) -> None:
    a = o.control('kn-stream-state-held-control', {7: '2'})
    b = o.control('kn-stream-state-replaced-control', {7: '2'})
    require(a[8] != '0' and a[8] == b[8], 'pre-entry state retains the selected subscription identity')
    delta(a, b, {9: 0, 10: 0, 11: 0}, 'same pre-entry state owner')
    for suffix in ('held', 'replaced'):
        o.native(f'kn-stream-state-{suffix}-native', {27: 3, 28: 0, 29: 1, 31: 0})
    o.vector('kn-stream-state-release-sync', [0])
    o.vector('kn-stream-state-trace', [2])
    o.native('kn-stream-state-drained-native', {27: 0, 28: 0, 29: 0, 31: 0})
    o.native('kn-stream-state-entry-replaced-native', {27: 11, 28: 0, 29: 2, 31: 1})
    o.vector('kn-stream-state-entry-current', [2, 0])
    o.native('kn-stream-state-entry-before-next-native', {27: 0, 28: 0, 29: 0, 30: 0, 31: 0})
    o.vector('kn-stream-state-entry-before-next', [2, 0])
    o.vector('kn-stream-state-entry-original-trace', [2, 4, 5])
    o.vector('kn-stream-state-entry-new-trace', [5])


def staging(o: Observations) -> None:
    full = o.native('kn-stream-staging-full-native', {27: 4096, 29: 4, 31: 0})
    rejected = o.native('kn-stream-staging-rejected-native', {27: 4096, 29: 4, 31: 0})
    same(full, rejected, (9, 10), 'replacement rejects before clone')
    o.native('kn-stream-staging-held-native', {27: 4096, 30: 4, 31: 0})
    o.control('kn-stream-staging-held-control', {12: '1', 13: '4', 14: '4096'})
    o.vector('kn-stream-staging-commit-sync', [1, 1, 1, 1])
    before = o.control('kn-stream-staging-abort-before-control', {12: '1', 13: '4', 14: '4096'})
    after = o.control('kn-stream-staging-abort-after-control', {12: '3', 14: '0'})
    delta(before, after, {16: 0, 17: 1}, 'explicit state abandon')
    o.native('kn-stream-staging-abort-native', {27: 0, 28: 0, 29: 0, 30: 0, 31: 0})
    for i in range(4):
        o.vector(f'kn-stream-staging-trace-{i}', [1, 2, 4])


def event(o: Observations) -> None:
    empty_before = o.native('kn-stream-event-empty-before-native', {27: 0, 28: 0, 30: 0})
    empty_after = o.native('kn-stream-event-empty-after-native', {27: 0, 28: 0, 30: 0})
    same(empty_before, empty_after, (9, 10), 'zero-listener event allocates no native output')
    o.control('kn-stream-event-held-control', {7: '2'})
    full = o.native('kn-stream-event-full-native', {27: 0, 28: 8, 31: 0})
    rejected = o.native('kn-stream-event-rejected-native', {27: 0, 28: 8, 31: 0})
    same(full, rejected, (9, 10), 'ninth event rejects before clone')
    o.native('kn-stream-event-entered-native', {28: 8, 31: 1})
    o.vector('kn-stream-event-release-sync', [0])
    o.vector('kn-stream-event-trace', list(range(1, 9)))
    six = o.native('kn-stream-event-fanout-six-native', {27: 6, 28: 6, 31: 0})
    rejected = o.native('kn-stream-event-fanout-rejected-native', {27: 6, 28: 6, 31: 0})
    same(six, rejected, (9, 10), 'three-recipient event admission atomic')
    for i in range(3):
        o.vector(f'kn-stream-event-fanout-trace-{i}', [1, 2])
    entered = o.native('kn-stream-event-outstanding-entered-native', {27: 0, 28: 8, 31: 1})
    rejected = o.native('kn-stream-event-outstanding-rejected-native', {27: 0, 28: 8, 31: 1})
    same(entered, rejected, (9, 10), 'reentrant two-recipient admission allocates none')
    for i in range(2):
        o.vector(f'kn-stream-event-outstanding-trace-{i}', [1, 2, 3, 4])
    o.vector('kn-stream-event-outstanding-rejections', [1])
    o.vector('kn-stream-event-isolation-state-trace', [11, 12])
    o.vector('kn-stream-event-isolation-event-trace', [21, 22])


def source_stop(o: Observations) -> None:
    for stream in (0, 1):
        prefix = f'kn-stream-source-{stream}'
        a = o.control(prefix + '-abort-before-control')
        o.native(prefix + '-abort-held-native', {27: 8, 30: 2, 31: 0})
        b = o.control(prefix + '-abort-after-control', {12: '3', 14: '0'})
        delta(a, b, {15: 1, 16: 0, 17: 1}, 'source explicit abandon')
        o.native(prefix + '-abort-released-native', {27: 0, 28: 0, 29: 0, 30: 0, 31: 0})
        o.native(prefix + '-held-native', {27: 8, 30: 2, 31: 0})
        held = o.control(prefix + '-held-control', {12: '1', 13: '2', 14: '8'})
        o.vector(prefix + '-pending', [0, 0, 0])
        o.native(prefix + '-abandoned-native', {27: 0, 28: 0, 29: 0, 30: 0, 31: 0})
        abandoned = o.control(prefix + '-abandoned-control', {12: '3', 14: '0'})
        delta(held, abandoned, {16: 0, 17: 1}, 'selected stop abandons all recipients')
        o.vector(prefix + '-stopped-trace', [])
        o.vector(prefix + '-live-trace', [8])
        prefix = f'kn-stream-delivery-stop-{stream}'
        before = o.control(prefix + '-baseline-control')
        held = o.control(prefix + '-held-control', {7: '2'})
        require(held[8] != '0', 'actual selected delivery identity required')
        o.vector(prefix + '-pending', [0, 0])
        o.native(prefix + '-pending-native', {27: 4, 28: stream, 29: 1 - stream, 31: 0})
        o.vector(prefix + '-release-sync', [0, 0])
        after = o.control(prefix + '-closed-control')
        delta(before, after, {9: 1, 10: 0, 11: 1}, 'stopped actual lease is discarded')
        o.native(prefix + '-closed-native', {27: 0, 28: 0, 29: 0, 30: 0, 31: 0})


def clones(o: Observations) -> None:
    for stream in (0, 1):
        for mode in ('pre', 'owned'):
            prefix = f'kn-stream-clone-{stream}-{mode}'
            expected = {27: 9 if stream == 0 else 0, 28: 0, 29: 3 if stream == 0 else 0, 31: 0}
            before = o.native(prefix + '-before-native', expected)
            after = o.native(prefix + '-after-native', expected)
            allocations = 2 if mode == 'owned' else 1
            require(after[9] - before[9] == allocations and after[10] - before[10] == allocations,
                    prefix + ': real error/prior output release exactly once')
            a = o.control(prefix + '-before-control')
            b = o.control(prefix + '-after-control', {23: '0'})
            delta(a, b, {18: 2, 19: 1, 20: allocations, 21: allocations, 22: 0}, prefix)
            for i in range(3):
                o.vector(prefix + f'-trace-{i}', [1, 3] if stream == 0 else [3])


def validate(scenario: str, numbers: dict[str, list[int]], controls: dict[str, str]) -> None:
    require(scenario in SCENARIOS, f'unsupported scenario {scenario!r}')
    o = Observations(numbers, controls)
    {SCENARIOS[0]: state, SCENARIOS[1]: staging, SCENARIOS[2]: event,
     SCENARIOS[3]: source_stop, SCENARIOS[4]: clones}[scenario](o)
    o.finish()


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key {key}')
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('observations', type=Path)
    args = parser.parse_args()
    raw = json.loads(args.observations.read_text(), object_pairs_hook=unique_pairs)
    require(set(raw) == {'scenario', 'numbers', 'controls'}, 'expected scenario/numbers/controls only')
    validate(raw['scenario'], raw['numbers'], raw['controls'])
    print(json.dumps({'scenario': raw['scenario'], 'stream_oracle': 'passed',
                      'runtime_close_and_target_evidence': 'caller-required'}))


if __name__ == '__main__':
    main()
