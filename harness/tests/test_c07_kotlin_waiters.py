from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
"""Synthetic observation counterexamples; no producer/native/target execution."""
from copy import deepcopy
import unittest
from c07_kotlin_waiter_observations import EXPECTED_ENGINE_COUNTS, SCENARIOS, predicates


def frame(**overrides):
    f = [0] * 110; f[0] = 70501
    for i, value in overrides.items(): f[int(i)] = value
    return f


def control():
    f = ['0'] * 31
    f[0], f[3], f[4], f[5], f[6] = '1', '1', '9007199254740993', '9007199254740995', '-1'
    return ','.join(f)


def positive(case):
    result = {}
    if case == 'kotlin-mixed-waiters':
        p = 'kn-waiter-mixed'
        result[p + '-baseline-native'] = frame(**{'12': 2, '13': 1, '39': 1})
        held = {'12': 2, '13': 1, '24': 1, '25': 1, '30': 1, '39': 1, '41': 1}
        result[p + '-held-native'] = frame(**held)
        for name in ('full', 'closed-values'): result[p + '-' + name + '-native'] = frame(**dict(held, **{'26': 32}))
        result[p + '-parent-full-native'] = frame(**dict(held, **{'26': 32, '37': 1}))
        result[p + '-parent-control'] = [1]
        result[p + '-final-settling'] = [0] * 9
        result[p + '-held-control'] = control()
        result[p + '-settling'] = [0] * 9
        result[p + '-closed-values'] = [3, 31, 0]
        result[p + '-completed'] = [1, 10, 10, 11, 0]
        result[p + '-drained-native'] = frame(**{'12': 2, '13': 2, '41': 1})
    else:
        for kind in range(3):
            p = f'kn-waiter-distinct-{kind}'
            result[p + '-baseline-native'] = frame(**{'12': kind + 1, '13': kind, '39': 1, '41': 2 * kind})
            owner = {'24': 1, '25': 1, '30': 1}
            held = {**owner, '12': kind + 1, '13': kind, '39': 1, '41': 2 * kind + 1}
            result[p + '-held-native'] = frame(**held)
            result[p + '-held-control'] = control()
            for phase in ('full', 'denied'): result[p + '-' + phase + '-native'] = frame(**dict(held, **{'26': 32}))
            result[p + '-capacity-native'] = frame()
            result[p + '-request-effect'] = [0 if kind == 0 else 1, 0]
            result[p + '-open-before-denial'] = [5]
            if kind == 1:
                result[p + '-sub-before'] = [1, 0, 0, 1]
                result[p + '-sub-after'] = [1, 1, 0, 1]
            result[p + '-retry'] = [1, 5 if kind == 0 else 0, 0]
            result[p + '-drained-native'] = frame(**{'12': kind + 1, '13': kind + 1, '39': 0})
    return result


class WaiterOracleTests(unittest.TestCase):
    def test_two_positive_scenarios_and_exact_engine_counts(self):
        self.assertEqual(EXPECTED_ENGINE_COUNTS, {'kotlin-mixed-waiters': 2, 'kotlin-distinct-close-denied': 3})
        for case in SCENARIOS:
            self.assertEqual(predicates(case, positive(case)), [])

    def test_full_owner_and_budget_counterexamples(self):
        mutations = [
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-parent-full-native', 30, 0),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-parent-full-native', 26, 33),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-parent-full-native', 13, 2),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-final-settling', 7, 1),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-final-settling', 8, 1),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-full-native', 26, 31),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-full-native', 26, 33),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-full-native', 30, 0),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-full-native', 24, 0),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-full-native', 31, 1),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-held-native', 41, 0),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-closed-values-native', 26, 31),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-closed-values-native', 26, 33),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-0-full-native', 24, 0),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-0-held-native', 41, 0),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-1-full-native', 30, 0),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-2-full-native', 39, 2),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-1-denied-native', 26, 33),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-2-denied-native', 30, 0),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-0-capacity-native', 26, 1),
        ]
        for case, label, index, value in mutations:
            f = positive(case); f[label][index] = value
            with self.subTest(label=label, index=index): self.assertTrue(predicates(case, f))

    def test_public_effect_and_retry_counterexamples(self):
        mutations = [
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-0-open-before-denial', [0]),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-1-sub-before', [1, 1, 0, 1]),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-1-sub-after', [1, 0, 0, 1]),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-1-sub-after', [1, 1, 1, 0]),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-closed-values', [2, 31, 0]),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-completed', [1, 31, 0, 0, 0]),
            ('kotlin-mixed-waiters', 'kn-waiter-mixed-completed', [1, 10, 10, 11, 1]),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-0-retry', [1, 0, 0]),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-1-request-effect', [0, 0]),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-2-request-effect', [0, 0]),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-1-retry', [0, 0, 0]),
            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-1-retry', [1, 0, 1]),
        ]
        for case, label, value in mutations:
            f = positive(case); f[label] = value
            with self.subTest(label=label): self.assertTrue(predicates(case, f))

    def test_no_early_physical_ack_or_residual_owner(self):
        for case, label in (('kotlin-mixed-waiters', 'kn-waiter-mixed-drained-native'),
                            ('kotlin-distinct-close-denied', 'kn-waiter-distinct-2-drained-native')):
            for index in (11, 24, 25, 26, 27, 28, 29, 30, 31, 35):
                f = positive(case); f[label][index] = 1
                with self.subTest(case=case, index=index): self.assertTrue(predicates(case, f))
            f = positive(case); f[label][13] -= 1
            self.assertTrue(predicates(case, f))

    def test_identity_precision_and_missing_real_gate(self):
        case = 'kotlin-distinct-close-denied'; f = positive(case)
        original = f['kn-waiter-distinct-0-held-control']
        self.assertIn('9007199254740993', original)
        self.assertEqual(predicates(case, f), [])
        for index, value in ((3, '0'), (4, '0'), (5, '0'), (4, '9.007199254740993e15'), (5, '18446744073709551616')):
            changed = deepcopy(f); fields = original.split(','); fields[index] = value
            changed['kn-waiter-distinct-0-held-control'] = ','.join(fields)
            self.assertTrue(predicates(case, changed))

    def test_malformed_missing_extra_or_old_settlement_rejected(self):
        case = 'kotlin-mixed-waiters'
        for bad in (None, [], [True] * 110, [70501] + [2**53] * 109):
            f = positive(case); f['kn-waiter-mixed-full-native'] = bad
            self.assertTrue(predicates(case, f))
        for bad in ([0] * 7, [0] * 10, [0] * 7 + [2, 0]):
            f = positive(case); f['kn-waiter-mixed-settling'] = bad
            self.assertTrue(predicates(case, f))
        f = positive(case); del f['kn-waiter-mixed-completed']; self.assertTrue(predicates(case, f))
        f = positive(case); f['kn-waiter-unexpected'] = []; self.assertTrue(predicates(case, f))
        self.assertTrue(predicates('unknown', {}))


if __name__ == '__main__': unittest.main()
