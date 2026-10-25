"""Hand-specified positive and counterexample observations, not producer replay.
Synthetic fixtures test oracle sensitivity only; they are never target evidence.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import json
import unittest

from c07_kotlin_stream_observations import (SCENARIOS, OracleFailure, counter, parse_control,
                                  unique_pairs, validate)


def native(**fields):
    raw = [0] * 110
    raw[0] = 70501
    for k, value in fields.items():
        raw[int(k)] = value
    return raw


def controls(**fields):
    raw = ['0'] * 31
    raw[0], raw[6] = '1', '-1'
    # Distinct identities above the JS safe-integer boundary must remain exact.
    raw[4], raw[5], raw[8] = '9007199254740993', '9007199254740995', '9007199254740997'
    for k, value in fields.items():
        raw[int(k)] = str(value)
    return ','.join(raw)


def positives():
    cases = {name: {'scenario': name, 'numbers': {}, 'controls': {}} for name in SCENARIOS}
    n, c = cases[SCENARIOS[0]]['numbers'], cases[SCENARIOS[0]]['controls']
    for suffix in ('held', 'replaced'):
        n[f'kn-stream-state-{suffix}-native'] = native(**{'27': 3, '29': 1})
        c[f'kn-stream-state-{suffix}-control'] = controls(**{'7': 2, '9': 1})
    n['kn-stream-state-release-sync'] = [0]
    n['kn-stream-state-trace'] = [2]
    n['kn-stream-state-drained-native'] = native()
    n['kn-stream-state-entry-replaced-native'] = native(**{'27': 11, '29': 2, '31': 1})
    n['kn-stream-state-entry-current'] = [2, 0]
    n['kn-stream-state-entry-before-next-native'] = native()
    n['kn-stream-state-entry-before-next'] = [2, 0]
    n['kn-stream-state-entry-original-trace'] = [2, 4, 5]
    n['kn-stream-state-entry-new-trace'] = [5]
    n, c = cases[SCENARIOS[1]]['numbers'], cases[SCENARIOS[1]]['controls']
    for suffix in ('full', 'rejected'):
        n[f'kn-stream-staging-{suffix}-native'] = native(**{'9': 4, '27': 4096, '29': 4})
    n['kn-stream-staging-held-native'] = native(**{'27': 4096, '30': 4})
    c['kn-stream-staging-held-control'] = controls(**{'12': 1, '13': 4, '14': 4096})
    n['kn-stream-staging-commit-sync'] = [1] * 4
    c['kn-stream-staging-abort-before-control'] = controls(**{'12': 1, '13': 4, '14': 4096})
    c['kn-stream-staging-abort-after-control'] = controls(**{'12': 3, '13': 4, '17': 1})
    n['kn-stream-staging-abort-native'] = native()
    for i in range(4):
        n[f'kn-stream-staging-trace-{i}'] = [1, 2, 4]
    n, c = cases[SCENARIOS[2]]['numbers'], cases[SCENARIOS[2]]['controls']
    c['kn-stream-event-held-control'] = controls(**{'7': 2})
    n['kn-stream-event-empty-before-native'] = native()
    n['kn-stream-event-empty-after-native'] = native()
    n['kn-stream-event-outstanding-entered-native'] = native(**{'28': 8, '31': 1})
    n['kn-stream-event-outstanding-rejected-native'] = native(**{'28': 8, '31': 1})
    n['kn-stream-event-outstanding-trace-0'] = [1, 2, 3, 4]
    n['kn-stream-event-outstanding-trace-1'] = [1, 2, 3, 4]
    n['kn-stream-event-outstanding-rejections'] = [1]
    n['kn-stream-event-isolation-state-trace'] = [11, 12]
    n['kn-stream-event-isolation-event-trace'] = [21, 22]
    for suffix in ('full', 'rejected'):
        n[f'kn-stream-event-{suffix}-native'] = native(**{'9': 8, '28': 8})
    n['kn-stream-event-entered-native'] = native(**{'28': 8, '31': 1})
    n['kn-stream-event-release-sync'] = [0]
    n['kn-stream-event-trace'] = list(range(1, 9))
    for suffix in ('six', 'rejected'):
        n[f'kn-stream-event-fanout-{suffix}-native'] = native(**{'9': 14, '10': 8, '27': 6, '28': 6})
    for i in range(3):
        n[f'kn-stream-event-fanout-trace-{i}'] = [1, 2]
    n, c = cases[SCENARIOS[3]]['numbers'], cases[SCENARIOS[3]]['controls']
    for stream in (0, 1):
        p = f'kn-stream-source-{stream}'
        c[p + '-abort-before-control'] = controls()
        n[p + '-abort-held-native'] = native(**{'27': 8, '30': 2})
        c[p + '-abort-after-control'] = controls(**{'12': 3, '15': 1, '17': 1})
        n[p + '-abort-released-native'] = native()
        n[p + '-held-native'] = native(**{'27': 8, '30': 2})
        c[p + '-held-control'] = controls(**{'12': 1, '13': 2, '14': 8, '17': 1})
        n[p + '-pending'] = [0, 0, 0]
        n[p + '-abandoned-native'] = native()
        c[p + '-abandoned-control'] = controls(**{'12': 3, '17': 2})
        n[p + '-stopped-trace'] = []
        n[p + '-live-trace'] = [8]
        p = f'kn-stream-delivery-stop-{stream}'
        c[p + '-baseline-control'] = controls()
        c[p + '-held-control'] = controls(**{'7': 2, '9': 1})
        n[p + '-pending'] = [0, 0]
        n[p + '-pending-native'] = native(**{'27': 4, '28': stream, '29': 1 - stream})
        n[p + '-release-sync'] = [0, 0]
        c[p + '-closed-control'] = controls(**{'7': 3, '9': 1, '11': 1})
        n[p + '-closed-native'] = native()
    n, c = cases[SCENARIOS[4]]['numbers'], cases[SCENARIOS[4]]['controls']
    for stream in (0, 1):
        for mode, alloc in (('pre', 1), ('owned', 2)):
            p = f'kn-stream-clone-{stream}-{mode}'
            before = native(**{'9': 10, '10': 7, '27': 9 if stream == 0 else 0, '29': 3 if stream == 0 else 0})
            n[p + '-before-native'] = before
            after = before.copy()
            after[9] += alloc
            after[10] += alloc
            n[p + '-after-native'] = after
            c[p + '-before-control'] = controls(**{'20': 10, '21': 7, '22': 3})
            c[p + '-after-control'] = controls(**{'18': 2, '19': 1, '20': 10 + alloc, '21': 7 + alloc, '22': 3})
            for i in range(3):
                n[p + f'-trace-{i}'] = [1, 3] if stream == 0 else [3]
    return cases


def check_case(case):
    validate(case['scenario'], case['numbers'], case['controls'])


def change_control(case, label, index, value):
    fields = case['controls'][label].split(',')
    fields[index] = str(value)
    case['controls'][label] = ','.join(fields)


class StreamOracleChecks(unittest.TestCase):
    def test_five_independent_synthetic_positive_cases(self):
        for case in positives().values():
            with self.subTest(scenario=case['scenario']):
                check_case(case)

    def test_counterexamples_each_rejected(self):
        mutations = [
            (0, 'entered old copy overwritten', 'kn-stream-state-entry-current', None, [4, 0]),
            (0, 'entered and latest merged into one ticket', 'kn-stream-state-entry-replaced-native', 29, 1),
            (0, 'entered plus two pending tickets', 'kn-stream-state-entry-replaced-native', 29, 3),
            (0, 'pending state retained intermediate3', 'kn-stream-state-entry-original-trace', None, [2, 3, 4, 5]),
            (0, 'new subscription replay callback', 'kn-stream-state-entry-new-trace', None, [4, 5]),
            (0, 'new subscription owns replay before future publish', 'kn-stream-state-entry-before-next-native', 29, 1),
            (2, 'zero-listener event owns model', 'kn-stream-event-empty-after-native', 9, 1),
            (2, 'zero-listener event owns source', 'kn-stream-event-empty-after-native', 30, 1),
            (2, 'two-recipient first entered excluded from limit', 'kn-stream-event-outstanding-entered-native', 28, 7),
            (2, 'two-recipient reentrant partial allocation', 'kn-stream-event-outstanding-rejected-native', 9, 1),
            (2, 'two-recipient missing real rejection', 'kn-stream-event-outstanding-rejections', None, [0]),
            (2, 'two-recipient partial delivery', 'kn-stream-event-outstanding-trace-1', None, [1, 2, 3, 4, 9]),
            (2, 'event leaks into state channel', 'kn-stream-event-isolation-state-trace', None, [11, 21, 12]),
            (2, 'state leaks into event channel', 'kn-stream-event-isolation-event-trace', None, [11, 21, 22]),
            (0, 'state two retained tickets before entry', 'kn-stream-state-replaced-native', 29, 2),
            (0, 'state already entered', 'kn-stream-state-held-native', 31, 1),
            (0, 'state retained old and new bytes', 'kn-stream-state-replaced-native', 27, 6),
            (0, 'state old value leaked', 'kn-stream-state-trace', None, [1, 2]),
            (0, 'state synchronous delivery', 'kn-stream-state-release-sync', None, [1]),
            (1, 'staging byte budget ignored', 'kn-stream-staging-full-native', 27, 4097),
            (1, 'rejected replacement did allocate', 'kn-stream-staging-rejected-native', 9, 5),
            (1, 'source reservation missing recipient', 'kn-stream-staging-held-native', 30, 3),
            (1, 'publication synchronously entered', 'kn-stream-staging-commit-sync', None, [2, 1, 1, 1]),
            (1, 'aborted publication delivered', 'kn-stream-staging-trace-3', None, [1, 2, 3, 4]),
            (2, 'event held lease excluded from limit', 'kn-stream-event-full-native', 28, 7),
            (2, 'entered lease excluded from limit', 'kn-stream-event-entered-native', 28, 7),
            (2, 'FIFO reordered', 'kn-stream-event-trace', None, [1, 3, 2, 4, 5, 6, 7, 8]),
            (2, 'FIFO event dropped', 'kn-stream-event-trace', None, [1, 2, 3, 4, 5, 6, 7]),
            (2, 'partial event fanout', 'kn-stream-event-fanout-trace-1', None, [1, 2, 3]),
            (3, 'source stopped ACK too early', 'kn-stream-source-0-pending', None, [1, 0, 0]),
            (3, 'source abandon leaks bytes', 'kn-stream-source-1-abandoned-native', 27, 4),
            (3, 'explicit abort leaks source', 'kn-stream-source-1-abort-released-native', 30, 1),
            (3, 'selected source partial commit', 'kn-stream-source-0-live-trace', None, [7, 8]),
            (3, 'stopped delivery still invokes', 'kn-stream-delivery-stop-1-release-sync', None, [0, 1]),
            (3, 'held delivery close early', 'kn-stream-delivery-stop-0-pending', None, [1, 0]),
            (3, 'held delivery leaked after close', 'kn-stream-delivery-stop-1-closed-native', 28, 1),
            (4, 'nonnull error output not released', 'kn-stream-clone-0-owned-after-native', 10, 8),
            (4, 'nonnull error output double released', 'kn-stream-clone-1-owned-after-native', 10, 10),
            (4, 'failed clone overwrites old state', 'kn-stream-clone-0-pre-trace-2', None, [2, 3]),
            (4, 'failed event reaches recipient', 'kn-stream-clone-1-owned-trace-0', None, [2, 3]),
        ]
        for scenario, reason, label, index, value in mutations:
            with self.subTest(reason=reason):
                case = positives()[SCENARIOS[scenario]]
                if index is None:
                    case['numbers'][label] = value
                else:
                    case['numbers'][label][index] = value
                with self.assertRaises(OracleFailure):
                    check_case(case)

    def test_control_counterexamples_each_rejected(self):
        mutations = [
            (0, 'kn-stream-state-replaced-control', 8, '9007199254740996'),
            (0, 'kn-stream-state-replaced-control', 9, '2'),
            (1, 'kn-stream-staging-abort-after-control', 17, '0'),
            (3, 'kn-stream-source-1-abandoned-control', 16, '1'),
            (3, 'kn-stream-delivery-stop-0-closed-control', 10, '1'),
            (3, 'kn-stream-delivery-stop-1-closed-control', 11, '0'),
            (4, 'kn-stream-clone-0-owned-after-control', 21, '8'),
            (4, 'kn-stream-clone-1-pre-after-control', 18, '1'),
            (4, 'kn-stream-clone-1-owned-after-control', 23, '1'),
        ]
        for scenario, label, index, value in mutations:
            with self.subTest(label=label, index=index):
                case = positives()[SCENARIOS[scenario]]
                change_control(case, label, index, value)
                with self.assertRaises(OracleFailure):
                    check_case(case)

    def test_identity_precision_and_maximum_remain_strings(self):
        frame = parse_control(controls(**{'4': '18446744073709551615'}))
        self.assertEqual(frame[4], '18446744073709551615')
        self.assertEqual(frame[8], '9007199254740997')
        with self.assertRaises(OracleFailure):
            counter(frame, 8)

    def test_invalid_wire_frames_rejected(self):
        valid = controls()
        for invalid in (valid + ',0', valid.replace('9007199254740997', '9.007199254740997e15'),
                        valid.replace('9007199254740997', '09007199254740997'),
                        valid.replace('9007199254740997', '18446744073709551616'),
                        valid.replace('9007199254740997', '-1'), valid.split(',')):
            with self.subTest(invalid=invalid):
                with self.assertRaises(OracleFailure):
                    parse_control(invalid)

    def test_missing_extra_duplicate_or_noninteger_observations_rejected(self):
        for mutation in ('missing', 'extra', 'float', 'bool', 'width', 'owner-fault'):
            case = positives()[SCENARIOS[0]]
            if mutation == 'missing':
                del case['numbers']['kn-stream-state-trace']
            elif mutation == 'extra':
                case['numbers']['kn-stream-unexpected'] = []
            elif mutation == 'float':
                case['numbers']['kn-stream-state-held-native'][29] = 1.0
            elif mutation == 'bool':
                case['numbers']['kn-stream-state-held-native'][29] = True
            elif mutation == 'width':
                case['numbers']['kn-stream-state-held-native'].append(0)
            else:
                case['numbers']['kn-stream-state-held-native'][8] = 1
            with self.subTest(mutation=mutation), self.assertRaises(OracleFailure):
                check_case(case)
        with self.assertRaises(OracleFailure):
            json.loads('{"label":1,"label":1}', object_pairs_hook=unique_pairs)


if __name__ == '__main__':
    unittest.main()
